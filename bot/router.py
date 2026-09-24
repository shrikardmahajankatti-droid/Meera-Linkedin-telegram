"""Trigger router: decides whether an incoming Telegram update should produce a
reply, and if so what kind. This uses no AI — it must stay cheap, predictable,
and fully unit-testable. `classify` never sends anything itself.
"""
from __future__ import annotations

import re
from enum import Enum

from telegram import Update

EDIT_PROMPT_PREFIX = "Send your edited version"

_TOPIC_PREFIX_RE = re.compile(r"^/topic\b", re.IGNORECASE)
_TOPIC_LABEL_RE = re.compile(r"^topic:", re.IGNORECASE)
_DRAFT_PREFIX_RE = re.compile(r"^/draft\b", re.IGNORECASE)
_DRAFT_LABEL_RE = re.compile(r"^draft:", re.IGNORECASE)
_DRAFT_NL_RE = re.compile(r"^(draft|write)\b.*\b(post|linkedin)\b", re.IGNORECASE | re.DOTALL)
_START_RE = re.compile(r"^/start\b", re.IGNORECASE)
_HELP_RE = re.compile(r"^/help\b", re.IGNORECASE)
_OVERRIDE_RE = re.compile(r"^/override\b", re.IGNORECASE)


class Classification(str, Enum):
    IGNORE = "ignore"
    NOTE = "note"
    TOPIC = "topic"
    DRAFT = "draft"
    REVIEW = "review"
    HELP = "help"
    SETUP = "setup"
    OVERRIDE = "override"


def _is_topic_trigger(text: str) -> bool:
    return bool(_TOPIC_PREFIX_RE.match(text) or _TOPIC_LABEL_RE.match(text))


def _is_draft_trigger(text: str) -> bool:
    return bool(
        _DRAFT_PREFIX_RE.match(text)
        or _DRAFT_LABEL_RE.match(text)
        or _DRAFT_NL_RE.match(text)
    )


def _is_override_trigger(text: str) -> bool:
    return bool(_OVERRIDE_RE.match(text))


def is_trigger_text(text: str) -> bool:
    """True if this text is a /topic, /draft, /override, Topic: or Draft:
    trigger. Used by callers to decide a message must NOT be stored as a note."""
    text = text.strip()
    return _is_topic_trigger(text) or _is_draft_trigger(text) or _is_override_trigger(text)


def _is_reply_to_edit_prompt(update: Update) -> bool:
    message = update.effective_message
    if message is None or message.reply_to_message is None:
        return False
    replied = message.reply_to_message
    if replied.from_user is None or not replied.from_user.is_bot:
        return False
    replied_text = replied.text or replied.caption or ""
    return replied_text.startswith(EDIT_PROMPT_PREFIX)


def classify(update: Update, *, review_chat_id: str, notes_channel_id: str) -> Classification:
    """Pure, side-effect-free classification of an incoming update.

    review_chat_id: the configured REVIEW_CHAT_ID as a string, or "" if unset.
    notes_channel_id: the configured NOTES_CHANNEL_ID as a string.
    """
    if update.callback_query is not None:
        chat = update.effective_chat
        chat_id = str(chat.id) if chat else ""
        if review_chat_id and chat_id == review_chat_id:
            return Classification.REVIEW
        return Classification.IGNORE

    message = update.effective_message
    if message is None:
        return Classification.IGNORE

    chat = update.effective_chat
    if chat is None:
        return Classification.IGNORE

    chat_id = str(chat.id)
    is_review_chat = bool(review_chat_id) and chat_id == review_chat_id
    is_notes_channel = chat_id == notes_channel_id
    is_private = chat.type == "private"

    text = (message.text or message.caption or "").strip()

    # Setup: REVIEW_CHAT_ID not yet configured, first /start in any private chat.
    if not review_chat_id and is_private and _START_RE.match(text):
        return Classification.SETUP

    if is_review_chat:
        if _START_RE.match(text) or _HELP_RE.match(text):
            return Classification.HELP
        if _is_reply_to_edit_prompt(update):
            return Classification.REVIEW
        if _is_override_trigger(text):
            return Classification.OVERRIDE
        if _is_draft_trigger(text):
            return Classification.DRAFT
        if _is_topic_trigger(text):
            return Classification.TOPIC
        return Classification.IGNORE

    if is_notes_channel:
        # Overrides only work from the review chat — a stray /override in the
        # channel is a no-op, not a note and not an override.
        if _is_override_trigger(text):
            return Classification.IGNORE
        if _is_draft_trigger(text):
            return Classification.DRAFT
        if _is_topic_trigger(text):
            return Classification.TOPIC
        # A note needs actual content: text/caption, or a voice message.
        if text or message.voice is not None:
            return Classification.NOTE
        return Classification.IGNORE

    # Any other chat (a stranger, or a private chat once REVIEW_CHAT_ID is
    # already configured) is silently ignored.
    return Classification.IGNORE
