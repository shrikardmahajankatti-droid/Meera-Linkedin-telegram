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
    gate_enabled: bool
    gate_on_auto_notes: bool
    gate_draft_threshold: int
    gate_warn_threshold: int
    gate_novelty_days: int
    news_enabled: bool
    news_lookback_days: int
    news_max_items: int
    news_hl: str
    news_gl: str
    news_ceid: str

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


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off"):
        return False
    raise RuntimeError(f"{name} must be a boolean (true/false), got {value!r}")


def _int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {value!r}") from exc


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

    gate_draft_threshold = _int("GATE_DRAFT_THRESHOLD", 70)
    gate_warn_threshold = _int("GATE_WARN_THRESHOLD", 50)
    if not (gate_warn_threshold < gate_draft_threshold <= 100):
        raise RuntimeError(
            "GATE_WARN_THRESHOLD must be < GATE_DRAFT_THRESHOLD <= 100, got "
            f"warn={gate_warn_threshold} draft={gate_draft_threshold}"
        )

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
        gate_enabled=_bool("GATE_ENABLED", True),
        gate_on_auto_notes=_bool("GATE_ON_AUTO_NOTES", True),
        gate_draft_threshold=gate_draft_threshold,
        gate_warn_threshold=gate_warn_threshold,
        gate_novelty_days=_int("GATE_NOVELTY_DAYS", 14),
        news_enabled=_bool("NEWS_ENABLED", True),
        news_lookback_days=_int("NEWS_LOOKBACK_DAYS", 3),
        news_max_items=_int("NEWS_MAX_ITEMS", 5),
        news_hl=os.environ.get("NEWS_HL", "en-IN").strip(),
        news_gl=os.environ.get("NEWS_GL", "IN").strip(),
        news_ceid=os.environ.get("NEWS_CEID", "IN:en").strip(),
    )
