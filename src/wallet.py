"""Credit/wallet system: balance tracking, OTP accrual, withdrawals, anti-fraud."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import async_session_factory
from .models import Transaction, User, WithdrawalRequest

logger = logging.getLogger(__name__)


class WalletService:
    """Manages user balances, OTP credit accrual, and withdrawal processing."""

    async def get_or_create_user(
        self,
        chat_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> User:
        """Get existing user or create new one with initial balance."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(User).where(User.chat_id == chat_id)
            )
            user = result.scalar_one_or_none()

            if user is None:
                user = User(
                    chat_id=chat_id,
                    username=username,
                    first_name=first_name,
                    balance=settings.initial_user_balance,
                    is_active=True,
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                logger.info("Created new user %s with $%.2f balance", chat_id, settings.initial_user_balance)
            elif username and user.username != username:
                user.username = username
                await session.commit()

            return user

    async def get_balance(self, chat_id: int) -> float:
        """Get current user balance."""
        user = await self.get_or_create_user(chat_id)
        return user.balance

    async def deduct_otp_cost(self, chat_id: int, phone: str) -> bool:
        """
        Deduct OTP cost from user balance. Returns True if sufficient funds.
        """
        cost = settings.cost_per_otp_credits
        async with async_session_factory() as session:
            result = await session.execute(
                select(User).where(User.chat_id == chat_id)
            )
            user = result.scalar_one_or_none()
            if user is None or user.balance < cost:
                return False

            user.balance -= cost
            user.total_spent += cost
            user.otp_count += 1

            tx = Transaction(
                chat_id=chat_id,
                amount=-cost,
                balance_after=user.balance,
                tx_type="debit",
                description=f"OTP received on +{phone}",
            )
            session.add(tx)
            await session.commit()
            return True

    async def credit_earnings(self, chat_id: int, phone: str) -> float:
        """
        Credit earnings for receiving an OTP. Returns amount credited.
        """
        earnings = settings.cost_per_otp_credits
        async with async_session_factory() as session:
            result = await session.execute(
                select(User).where(User.chat_id == chat_id)
            )
            user = result.scalar_one_or_none()
            if user is None:
                return 0.0

            user.balance += earnings
            user.total_earned += earnings

            tx = Transaction(
                chat_id=chat_id,
                amount=earnings,
                balance_after=user.balance,
                tx_type="credit",
                description=f"Earnings from +{phone} OTP",
            )
            session.add(tx)
            await session.commit()
            return earnings

    async def add_deposit(self, chat_id: int, amount: float, method: str = "manual") -> bool:
        """Add deposit to user balance."""
        if amount <= 0:
            return False

        async with async_session_factory() as session:
            result = await session.execute(
                select(User).where(User.chat_id == chat_id)
            )
            user = result.scalar_one_or_none()
            if user is None:
                return False

            user.balance += amount

            tx = Transaction(
                chat_id=chat_id,
                amount=amount,
                balance_after=user.balance,
                tx_type="deposit",
                description=f"Deposit via {method}",
            )
            session.add(tx)
            await session.commit()
            return True

    async def request_withdrawal(
        self, chat_id: int, amount: float, method: str, address: str | None = None
    ) -> tuple[bool, str]:
        """
        Submit a withdrawal request. Returns (success, message).
        """
        if amount < settings.min_withdrawal_amount:
            return False, f"Minimum withdrawal is ${settings.min_withdrawal_amount:.2f}"

        balance = await self.get_balance(chat_id)
        if balance < amount:
            return False, f"Insufficient balance (${balance:.2f})"

        async with async_session_factory() as session:
            # Deduct from balance immediately
            result = await session.execute(
                select(User).where(User.chat_id == chat_id)
            )
            user = result.scalar_one_or_none()
            if user is None or user.balance < amount:
                return False, "Insufficient balance"

            user.balance -= amount

            withdrawal = WithdrawalRequest(
                chat_id=chat_id,
                amount=amount,
                method=method,
                address=address,
                status="pending",
            )
            session.add(withdrawal)

            tx = Transaction(
                chat_id=chat_id,
                amount=-amount,
                balance_after=user.balance,
                tx_type="withdrawal",
                description=f"Withdrawal request ({method})",
            )
            session.add(tx)
            await session.commit()

        logger.info("Withdrawal requested: $%.2f by %s via %s", amount, chat_id, method)
        return True, f"Withdrawal of ${amount:.2f} submitted for review."

    async def get_transaction_history(self, chat_id: int, limit: int = 10) -> list[dict]:
        """Get recent transactions for a user."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(Transaction)
                .where(Transaction.chat_id == chat_id)
                .order_by(Transaction.created_at.desc())
                .limit(limit)
            )
            txs = result.scalars().all()
            return [
                {
                    "amount": tx.amount,
                    "type": tx.tx_type,
                    "description": tx.description,
                    "balance_after": tx.balance_after,
                    "date": tx.created_at.strftime("%Y-%m-%d %H:%M") if tx.created_at else "",
                }
                for tx in txs
            ]

    async def get_withdrawal_requests(self, status: str = "pending") -> list[dict]:
        """Get withdrawal requests for admin review."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(WithdrawalRequest)
                .where(WithdrawalRequest.status == status)
                .order_by(WithdrawalRequest.created_at.desc())
            )
            reqs = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "chat_id": r.chat_id,
                    "amount": r.amount,
                    "method": r.method,
                    "address": r.address,
                    "status": r.status,
                    "date": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
                }
                for r in reqs
            ]

    async def approve_withdrawal(self, request_id: int, admin_chat_id: int) -> bool:
        """Approve a withdrawal request."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(WithdrawalRequest).where(WithdrawalRequest.id == request_id)
            )
            req = result.scalar_one_or_none()
            if req is None or req.status != "pending":
                return False
            req.status = "approved"
            req.reviewed_by = admin_chat_id
            req.reviewed_at = datetime.now(timezone.utc)
            await session.commit()
        return True

    async def reject_withdrawal(self, request_id: int, admin_chat_id: int) -> bool:
        """Reject a withdrawal request and refund the user."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(WithdrawalRequest).where(WithdrawalRequest.id == request_id)
            )
            req = result.scalar_one_or_none()
            if req is None or req.status != "pending":
                return False

            # Refund the user
            user_result = await session.execute(
                select(User).where(User.chat_id == req.chat_id)
            )
            user = user_result.scalar_one_or_none()
            if user:
                user.balance += req.amount
                tx = Transaction(
                    chat_id=req.chat_id,
                    amount=req.amount,
                    balance_after=user.balance,
                    tx_type="refund",
                    description=f"Withdrawal #{req.id} rejected — refund",
                )
                session.add(tx)

            req.status = "rejected"
            req.reviewed_by = admin_chat_id
            req.reviewed_at = datetime.now(timezone.utc)
            await session.commit()
        return True


wallet_service = WalletService()
