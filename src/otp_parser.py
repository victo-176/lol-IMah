"""OTP / Verification code extraction pipeline with expanded patterns."""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── OTP patterns (ordered by specificity) ────────────────────────

# Standard numeric OTPs (4-8 digits) with keyword context
_NUMERIC_OTP = re.compile(
    r"(?:(?:code|otp|pin|验证码|код|key|token|verify|verification|auth)[\s:：\-]*"
    r"|(?:is|are)\s+)"
    r"(\d{4,8})",
    re.IGNORECASE,
)

# "Your X code is 123456" / "123456 is your X code"
_CONTEXTUAL_OTP = re.compile(
    r"(\d{4,8})\s+(?:is\s+your|is\s+the|for\s+your)\s+",
    re.IGNORECASE,
)

# "Enter 123456" / "use 123456"
_IMPERATIVE_OTP = re.compile(
    r"(?:enter|use|input|dial|type)\s+(\d{4,8})",
    re.IGNORECASE,
)

# Standalone 4-8 digit code in short messages (<200 chars)
_STANDALONE_OTP = re.compile(r"\b(\d{4,8})\b")

# Alphanumeric verification keys (e.g., ABC-123456, AB12CD34)
_ALPHA_OTP = re.compile(
    r"\b([A-Z0-9]{2,4}[\-]?[A-Z0-9]{4,8})\b",
    re.IGNORECASE,
)

# Known service/brand names that should NOT be matched as OTP codes
_SERVICE_NAMES = frozenset({
    "openai", "google", "whatsapp", "telegram", "instagram",
    "facebook", "tiktok", "discord", "microsoft", "netflix",
    "amazon", "paypal", "binance", "coinbase", "uber",
    "apple", "steam", "reddit", "snapchat", "linkedin",
    "signal", "viber", "shopify", "twitch", "youtube",
    "chatgpt", "claude", "gemini", "copilot", "grok",
    "claudeai", "perplexity", "mistral", "deepseek", "qwen",
    "nvidia", "xiaomi", "tencent", "openrouter", "minimax",
})

# Magic links
_MAGIC_LINK = re.compile(
    r"(https?://\S+(?:verify|confirm|auth|login|activate|code|otp)\S*)",
    re.IGNORECASE,
)

# Code with separators: 482-910, 482.910, 482 910
_SEPARATOR_CODE = re.compile(r"\b(\d{3}[\-.\s]\d{3,4})\b")


# ── Service detection patterns ───────────────────────────────────

_SERVICE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("WhatsApp", re.compile(r"whatsapp", re.IGNORECASE)),
    ("Telegram", re.compile(r"telegram|tg\s|telegra", re.IGNORECASE)),
    ("Google", re.compile(r"google|gmail|g-\d|gcode", re.IGNORECASE)),
    ("Instagram", re.compile(r"instagram|insta", re.IGNORECASE)),
    ("Facebook", re.compile(r"facebook|fb\s", re.IGNORECASE)),
    ("TikTok", re.compile(r"tiktok|tik\s*tok", re.IGNORECASE)),
    ("X (Twitter)", re.compile(r"(?:twitter|x\.com|@x\b)", re.IGNORECASE)),
    ("Discord", re.compile(r"discord", re.IGNORECASE)),
    ("Microsoft", re.compile(r"microsoft|outlook|office365", re.IGNORECASE)),
    ("Apple", re.compile(r"apple|icloud|imessage", re.IGNORECASE)),
    ("OpenAI", re.compile(r"openai|chatgpt", re.IGNORECASE)),
    ("Claude", re.compile(r"\bclaude\b", re.IGNORECASE)),
    ("Steam", re.compile(r"steam", re.IGNORECASE)),
    ("Uber", re.compile(r"\buber\b", re.IGNORECASE)),
    ("Amazon", re.compile(r"amazon", re.IGNORECASE)),
    ("Netflix", re.compile(r"netflix", re.IGNORECASE)),
    ("PayPal", re.compile(r"paypal", re.IGNORECASE)),
    ("Binance", re.compile(r"binance", re.IGNORECASE)),
    ("Coinbase", re.compile(r"coinbase", re.IGNORECASE)),
    ("Shopify", re.compile(r"shopify", re.IGNORECASE)),
    ("Snapchat", re.compile(r"snapchat|snap", re.IGNORECASE)),
    ("LinkedIn", re.compile(r"linkedin", re.IGNORECASE)),
    ("Reddit", re.compile(r"reddit", re.IGNORECASE)),
    ("Signal", re.compile(r"\bsignal\b", re.IGNORECASE)),
    ("Viber", re.compile(r"\bviber\b", re.IGNORECASE)),
    ("Bank OTP", re.compile(r"(?:bank|transaction|payment|transfer|debit|credit\s*card)", re.IGNORECASE)),
    ("Gemini", re.compile(r"\bgemini\b", re.IGNORECASE)),
    ("Grok", re.compile(r"\bgrok\b", re.IGNORECASE)),
    ("Perplexity", re.compile(r"perplexity", re.IGNORECASE)),
]


@dataclass(frozen=True)
class ParsedOTP:
    """Result of OTP extraction from an SMS body."""

    code: str | None
    service: str
    raw_text: str
    is_magic_link: bool = False


def detect_service(text: str) -> str:
    """Identify the target service from SMS content."""
    for name, pattern in _SERVICE_PATTERNS:
        if pattern.search(text):
            return name
    return "Unknown"


def extract_otp(text: str) -> ParsedOTP:
    """
    Parse an SMS body and extract the OTP / verification code.

    Returns a ParsedOTP with the extracted code (or None), detected service,
    and whether the payload is a magic link.
    """
    service = detect_service(text)

    # 1. Contextual pattern with explicit OTP keywords
    match = _NUMERIC_OTP.search(text)
    if match:
        return ParsedOTP(code=match.group(1), service=service, raw_text=text)

    # 2. "X is your code" pattern
    match = _CONTEXTUAL_OTP.search(text)
    if match:
        return ParsedOTP(code=match.group(1), service=service, raw_text=text)

    # 3. Imperative pattern ("Enter 123456")
    match = _IMPERATIVE_OTP.search(text)
    if match:
        return ParsedOTP(code=match.group(1), service=service, raw_text=text)

    # 4. Separated code (482-910)
    match = _SEPARATOR_CODE.search(text)
    if match:
        code = match.group(1).replace("-", "").replace(".", "").replace(" ", "")
        return ParsedOTP(code=code, service=service, raw_text=text)

    # 5. Magic links
    match = _MAGIC_LINK.search(text)
    if match:
        return ParsedOTP(
            code=None, service=service, raw_text=text, is_magic_link=True
        )

    # 6. Alphanumeric keys (skip service name matches)
    for match in _ALPHA_OTP.finditer(text):
        candidate = match.group(1)
        if candidate.lower() not in _SERVICE_NAMES:
            return ParsedOTP(code=candidate, service=service, raw_text=text)

    # 7. Standalone numeric (only if message is short)
    if len(text) < 200:
        match = _STANDALONE_OTP.search(text)
        if match:
            return ParsedOTP(code=match.group(1), service=service, raw_text=text)

    # 8. No OTP found
    return ParsedOTP(code=None, service=service, raw_text=text)
