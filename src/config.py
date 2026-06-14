"""Configuration management for AI News Daily system."""

import os
import pytz
from datetime import datetime, timezone
from dotenv import load_dotenv
from dataclasses import dataclass, field
from typing import Optional

load_dotenv()

# ============================================================
# Core constants — adjust here only
# ============================================================
BEIJING_TZ = pytz.timezone("Asia/Shanghai")
UTC = timezone.utc


def now_beijing() -> datetime:
    return datetime.now(BEIJING_TZ)


def now_utc() -> datetime:
    return datetime.now(UTC)


# GitHub Actions UTC 12:00 = Beijing 20:00
GITHUB_CRON_UTC = "0 12 * * *"


# ============================================================
# Env-backed config
# ============================================================
@dataclass
class Settings:
    # === push channels ===
    FEISHU_WEBHOOK_URL: Optional[str] = os.getenv("FEISHU_WEBHOOK_URL", "")
    WECOM_WEBHOOK_URL: Optional[str] = os.getenv("WECOM_WEBHOOK_URL", "")
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_CHAT_ID", "")
    EMAIL_TO: Optional[str] = os.getenv("EMAIL_TO", "")
    EMAIL_USER: Optional[str] = os.getenv("EMAIL_USER", "")
    EMAIL_PASSWORD: Optional[str] = os.getenv("EMAIL_PASSWORD", "")

    # === LLM ===
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")

    # === optional RSS / API tokens ===
    REDDIT_CLIENT_ID: Optional[str] = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: Optional[str] = os.getenv("REDDIT_CLIENT_SECRET", "")
    YOUTUBE_API_KEY: Optional[str] = os.getenv("YOUTUBE_API_KEY", "")
    PRODUCT_HUNT_TOKEN: Optional[str] = os.getenv("PRODUCT_HUNT_TOKEN", "")

    # === behaviour ===
    DATA_DIR: str = os.getenv("DATA_DIR", "data")
    MAX_ITEMS_PER_SECTION: int = 10
    DEDUP_SIMILARITY_THRESHOLD: float = 0.75
    LLM_TIMEOUT_SECONDS: int = 120

    # Push channel order of preference
    PUSH_CHANNELS: list[str] = field(default_factory=lambda: ["feishu", "wecom"])

    def active_push_channel(self) -> Optional[str]:
        for ch in self.PUSH_CHANNELS:
            if ch == "feishu" and self.FEISHU_WEBHOOK_URL:
                return "feishu"
            if ch == "wecom" and self.WECOM_WEBHOOK_URL:
                return "wecom"
            if ch == "telegram" and self.TELEGRAM_BOT_TOKEN:
                return "telegram"
            if ch == "email" and self.EMAIL_TO:
                return "email"
        return None


settings = Settings()
