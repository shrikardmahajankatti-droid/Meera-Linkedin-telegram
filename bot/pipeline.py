"""Core update-processing pipeline, shared by the Vercel webhook (api/webhook.py)
and the local polling runner (bot/local.py) so the two entrypoints can never
drift apart. No LinkedIn integration, no auto-posting: the only thing this
ever does with a draft is send it back to Meera in Telegram.
"""
from __future__ import annotations

import logging
import re

from supabase import Client
from telegram import Bot, Update

from bot import db, gemini
from bot.config import Config
from bot.router import Classification, classify

logger = logging.getLogger(__name__)

_TRIGGER_PREFIX_RE = re.compile(r"^(/topic|/draft|topic:|draft:)\s*", re.IGNORECASE)


def _allowed_chat(chat_id: int, config: Config) -> bool:
    chat_id_str = str(chat_id)
    return chat_id_str == config.review_chat_id or chat_id_str == config.notes_channel_id


def _extract_subject(text: str) -> str:
    """Strip a leading /topic, /draft, Topic: or Draft: prefix to get the bare
    subject, e.g. 'Topic: niacinamide' -> 'niacinamide'."""
    stripped = _TRIGGER_PREFIX_RE.sub("", text).strip()
    return stripped or text


async def process_update(update: Update, config: Config, supabase_client: Client) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    if not _allowed_chat(chat.id, config):
        return

    text = (message.text or message.caption or "").strip()
    if not text:
        return  # voice/stickers are a later concern

    note_row = db.insert_note_if_new(
        supabase_client,
        telegram_update_id=update.update_id,
        chat_id=chat.id,
        text=text,
    )
    if note_row is None:
        logger.info("update_id %s already processed — Telegram retry, ignoring.", update.update_id)
        return

    voice_skill = db.get_voice_skill(supabase_client)
    if not voice_skill:
        logger.error("voice_skill table is empty — run `python -m bot.seed_voice_skill` first.")
        return

    # Bot() self-initializes its HTTP client on first call; no need for the
    # `async with Bot(...)` pattern, which would add an extra get_me() round
    # trip on every single webhook invocation just to validate the token.
    bot = Bot(config.telegram_bot_token)

    if config.trigger_mode == "auto":
        await _handle_auto_note(note_row, text, voice_skill, config, supabase_client, bot, chat.id)
        return

    classification = classify(
        update,
        review_chat_id=config.review_chat_id,
        notes_channel_id=config.notes_channel_id,
    )
    if classification in (Classification.TOPIC, Classification.DRAFT):
        await _handle_topic_or_draft(text, voice_skill, config, supabase_client, bot, chat.id)
    # Classification.NOTE: already stored above — stay silent, as designed.
    # HELP / SETUP / REVIEW / IGNORE: wired up in a later step.


async def _handle_auto_note(note_row, text, voice_skill, config, supabase_client, bot, chat_id) -> None:
    draft_text = gemini.generate_draft(config.gemini_api_key, note_text=text, voice_skill=voice_skill)
    db.insert_draft(supabase_client, note_id=note_row["id"], draft_text=draft_text, model="gemini")
    await bot.send_message(chat_id=chat_id, text=draft_text)


async def _handle_topic_or_draft(text, voice_skill, config, supabase_client, bot, chat_id) -> None:
    subject = _extract_subject(text)
    match = db.find_best_matching_note(supabase_client, keywords=subject.split())
    if match is None:
        await bot.send_message(chat_id=chat_id, text=f"No notes match '{subject}'.")
        return
    draft_text = gemini.generate_draft(config.gemini_api_key, note_text=match["text"], voice_skill=voice_skill)
    db.insert_draft(supabase_client, note_id=match["id"], draft_text=draft_text, model="gemini")
    await bot.send_message(chat_id=chat_id, text=draft_text)
