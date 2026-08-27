"""SQLAlchemy ORM models for persistent storage."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    balance = Column(Float, nullable=False, default=0.0)
    total_earned = Column(Float, nullable=False, default=0.0)
    total_spent = Column(Float, nullable=False, default=0.0)
    otp_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    is_banned = Column(Boolean, nullable=False, default=False)
    is_admin = Column(Boolean, nullable=False, default=False)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_number = Column(String(50), nullable=False, index=True)
    chat_id = Column(Integer, nullable=False, index=True)
    claimed_at = Column(DateTime, nullable=False, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    otp_count = Column(Integer, nullable=False, default=0)


class MessageLog(Base):
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(100), nullable=True, index=True)
    phone_number = Column(String(50), nullable=False, index=True)
    sender = Column(String(255), nullable=True)
    body = Column(Text, nullable=True)
    otp_code = Column(String(20), nullable=True)
    service_detected = Column(String(100), nullable=True)
    delivered_to_group = Column(Boolean, nullable=False, default=False)
    delivered_to_user = Column(Boolean, nullable=False, default=False)
    delivered_to_chat_ids = Column(Text, nullable=True)  # JSON list
    raw_payload = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class AdminLog(Base):
    __tablename__ = "admin_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_chat_id = Column(Integer, nullable=False)
    action = Column(String(100), nullable=False)
    target = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False, default=0.0)
    tx_type = Column(String(50), nullable=False)  # credit, debit, deposit, withdrawal, refund
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    method = Column(String(50), nullable=False)  # usdt, ltc, local
    address = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, approved, rejected, completed
    reviewed_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    reviewed_at = Column(DateTime, nullable=True)


class DeadLetterQueue(Base):
    """Malformed frames quarantined for inspection."""
    __tablename__ = "dead_letter_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_payload = Column(Text, nullable=False)
    error_reason = Column(String(255), nullable=False)
    retry_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    resolved = Column(Boolean, nullable=False, default=False)


class BlockedEntry(Base):
    """Unified blocked services, countries, and users."""
    __tablename__ = "blocked_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_type = Column(String(20), nullable=False, index=True)  # service, country, user
    entry_value = Column(String(100), nullable=False)
    blocked_by = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
