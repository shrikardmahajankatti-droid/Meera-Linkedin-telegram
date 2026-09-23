from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    notes_channel_id: str
    review_chat_id: str
    gemini_api_key: str
    gemini_model: str
    timezone: str
    reply_in: str
    db_path: str

    @property
    def review_chat_id_int(self) -> int | None:
        return int(self.review_chat_id) if self.review_chat_id else None

    @property
    def notes_channel_id_int(self) -> int:
        return int(self.notes_channel_id)


def load_config() -> Config:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    notes_channel_id = os.environ.get("NOTES_CHANNEL_ID", "").strip()
    if not notes_channel_id:
        raise RuntimeError("NOTES_CHANNEL_ID is not set in .env")

    return Config(
        telegram_bot_token=token,
        notes_channel_id=notes_channel_id,
        review_chat_id=os.environ.get("REVIEW_CHAT_ID", "").strip(),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        timezone=os.environ.get("TIMEZONE", "Asia/Kolkata").strip(),
        reply_in=os.environ.get("REPLY_IN", "private").strip().lower(),
        db_path=os.environ.get("DB_PATH", "skinstinct.db").strip(),
    )
