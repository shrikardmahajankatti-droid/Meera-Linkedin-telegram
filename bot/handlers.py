from __future__ import annotations

import logging
import sys

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from bot import db
from bot.config import Config
from bot.router import Classification, classify

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Skinstinct content bot.\n"
    "/topic <subject> — 3 post ideas from your notes\n"
    "/draft <subject> — one LinkedIn draft\n"
    "Drop notes in the channel any time — I store them silently.\n"
    "/notes <keyword> and /stats also work."
)


async def startup_checks(config: Config, bot) -> None:
    """Run once before polling starts. Never sends a Telegram message — any
    problem is reported to the terminal only."""
    try:
        me = await bot.get_me()
        logger.info("Connected as @%s", me.username)
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: could not authenticate with TELEGRAM_BOT_TOKEN: {exc}", file=sys.stderr)
        raise SystemExit(1)

    try:
        chat = await bot.get_chat(config.notes_channel_id_int)
    except Exception as exc:  # noqa: BLE001
        print(
            f"FATAL: could not access NOTES_CHANNEL_ID={config.notes_channel_id}: {exc}\n"
            "Fix: check the channel ID is correct (must include the -100 prefix) "
            "and that the bot has been added to the channel.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        member = await bot.get_chat_member(chat.id, me.id)
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: could not check bot's membership in the notes channel: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if member.status not in ("administrator", "creator"):
        print(
            f"FATAL: @{me.username} is not an admin of the notes channel "
            f"(current status: {member.status}).\n"
            "Fix: open the channel in Telegram, go to Administrators, and add the bot "
            "as an admin (it needs to read every post, not just be a member).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    logger.info("Startup checks passed: bot is admin of the notes channel.")


def _target_chat_id(config: Config, source_chat_id: int) -> int:
    if config.reply_in == "same_chat":
        return source_chat_id
    return config.review_chat_id_int


async def on_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.bot_data["config"]
    classification = classify(
        update,
        review_chat_id=config.review_chat_id,
        notes_channel_id=config.notes_channel_id,
    )

    if classification is Classification.NOTE:
        message = update.effective_message
        text = message.text or message.caption or ""
        is_voice = message.voice is not None
        stored_text = text if text else "[voice message]"
        db.insert_note(
            config.db_path,
            source="telegram",
            source_id=str(message.message_id),
            text=stored_text,
            needs_transcript=is_voice,
        )
        return  # silent: no reply, no reaction

    if classification is Classification.SETUP:
        chat = update.effective_chat
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                f"This chat's ID is {chat.id}.\n"
                "Add it to .env as REVIEW_CHAT_ID, then restart the bot."
            ),
        )
        return

    if classification is Classification.HELP:
        await context.bot.send_message(chat_id=config.review_chat_id_int, text=HELP_TEXT)
        return

    if classification is Classification.TOPIC:
        # Implemented in Phase 2/3: matching + ideas.
        return

    if classification is Classification.DRAFT:
        # Implemented in Phase 2/3: matching + drafting.
        return

    if classification is Classification.REVIEW:
        # Implemented in Phase 3: Approve/Edit/Skip/Redraft handling.
        return

    # Classification.IGNORE: do nothing, silently.
    return


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.bot_data["config"]
    classification = classify(
        update,
        review_chat_id=config.review_chat_id,
        notes_channel_id=config.notes_channel_id,
    )
    await update.callback_query.answer()
    if classification is Classification.REVIEW:
        # Implemented in Phase 3.
        return
    return


def build_application(config: Config) -> Application:
    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config
    app.add_handler(MessageHandler(filters.ALL, on_update))
    app.add_handler(CallbackQueryHandler(on_callback))
    return app
