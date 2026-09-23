from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

VALID_TRIGGER_MODES = ("auto", "topic")
VALID_DRAFT_MODELS = ("gemini", "claude")


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    gemini_api_key: str
    supabase_url: str
    supabase_key: str
    notes_channel_id: str
    review_chat_id: str
    trigger_mode: str
    draft_model: str
    anthropic_api_key: str
    telegram_webhook_secret: str

    @property
    def review_chat_id_int(self) -> int | None:
        return int(self.review_chat_id) if self.review_chat_id else None

    @property
    def notes_channel_id_int(self) -> int:
        return int(self.notes_channel_id)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set in .env")
    return value


def load_config() -> Config:
    trigger_mode = os.environ.get("TRIGGER_MODE", "auto").strip().lower()
    if trigger_mode not in VALID_TRIGGER_MODES:
        raise RuntimeError(f"TRIGGER_MODE must be one of {VALID_TRIGGER_MODES}, got {trigger_mode!r}")

    draft_model = os.environ.get("DRAFT_MODEL", "gemini").strip().lower()
    if draft_model not in VALID_DRAFT_MODELS:
        raise RuntimeError(f"DRAFT_MODEL must be one of {VALID_DRAFT_MODELS}, got {draft_model!r}")

    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if draft_model == "claude" and not anthropic_api_key:
        raise RuntimeError("DRAFT_MODEL=claude requires ANTHROPIC_API_KEY to be set")

    return Config(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        gemini_api_key=_require("GEMINI_API_KEY"),
        supabase_url=_require("SUPABASE_URL"),
        supabase_key=_require("SUPABASE_KEY"),
        notes_channel_id=_require("NOTES_CHANNEL_ID"),
        review_chat_id=os.environ.get("REVIEW_CHAT_ID", "").strip(),
        trigger_mode=trigger_mode,
        draft_model=draft_model,
        anthropic_api_key=anthropic_api_key,
        telegram_webhook_secret=_require("TELEGRAM_WEBHOOK_SECRET"),
    )
