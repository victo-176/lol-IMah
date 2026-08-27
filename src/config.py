"""Centralized configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _int(key: str, default: int) -> int:
    try:
        return int(os.environ[key])
    except (KeyError, ValueError):
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.environ[key])
    except (KeyError, ValueError):
        return default


def _bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes")


def _list_int(key: str) -> list[int]:
    raw = os.environ.get(key, "")
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


@dataclass(frozen=True)
class Settings:
    # ── Telegram ──────────────────────────────────────
    telegram_bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_group_id: int = _int("TELEGRAM_GROUP_ID", 0)
    telegram_admin_ids: list[int] = field(default_factory=lambda: _list_int("TELEGRAM_ADMIN_IDS"))

    # ── IVASMS WSS ────────────────────────────────────
    ivasms_wss_url: str = os.environ.get("IVASMS_WSS_URL", "")
    ivasms_auth_token: str = os.environ.get("IVASMS_AUTH_TOKEN", "")
    ivasms_user_id: str = os.environ.get("IVASMS_USER_ID", "")
    ivasms_api_key: str = os.environ.get("IVASMS_API_KEY", "")

    # ── Redis ─────────────────────────────────────────
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # ── Database ──────────────────────────────────────
    database_url: str = os.environ.get(
        "DATABASE_URL", "sqlite+aiosqlite:///data/ivasms_bot.db"
    )

    # ── Claim / Session ───────────────────────────────
    claim_ttl_minutes: int = _int("DEFAULT_CLAIM_TTL_MINUTES", 15)
    exclusive_claim_mode: bool = _bool("EXCLUSIVE_CLAIM_MODE", True)

    # ── WSS Resilience ────────────────────────────────
    heartbeat_interval: int = _int("HEARTBEAT_INTERVAL", 20)
    reconnect_max_delay: int = _int("RECONNECT_MAX_DELAY", 60)
    reconnect_base_delay: float = _float("RECONNECT_BASE_DELAY", 1.0)

    # ── Rate Limiting ─────────────────────────────────
    telegram_rate_limit_global: int = _int("TELEGRAM_RATE_LIMIT_GLOBAL", 25)
    telegram_rate_limit_user: int = _int("TELEGRAM_RATE_LIMIT_USER", 1)

    # ── Credit / Wallet System ────────────────────────
    cost_per_otp_credits: float = _float("COST_PER_OTP_CREDITS", 1.0)
    initial_user_balance: float = _float("INITIAL_USER_BALANCE", 10.0)
    min_withdrawal_amount: float = _float("MIN_WITHDRAWAL_AMOUNT", 5.0)
    max_daily_earnings: float = _float("MAX_DAILY_EARNINGS", 50.0)
    max_daily_claims: int = _int("MAX_DAILY_CLAIMS", 10)

    # ── Anti-Fraud ────────────────────────────────────
    max_claims_per_ip: int = _int("MAX_CLAIMS_PER_IP", 3)
    fraud_window_hours: int = _int("FRAUD_WINDOW_HOURS", 24)

    # ── Derived ───────────────────────────────────────
    data_dir: Path = field(default_factory=lambda: Path("data"))

    def __post_init__(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def wss_base_url(self) -> str:
        """Return WSS base URL without transport params."""
        url = self.ivasms_wss_url
        for param in ("&EIO=4", "&transport=websocket"):
            url = url.replace(param, "")
        return url

    def build_wss_url(self, token: str | None = None) -> str:
        """Build a fresh WSS URL with an updated token."""
        base = self.wss_base_url
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}EIO=4&transport=websocket"


settings = Settings()
