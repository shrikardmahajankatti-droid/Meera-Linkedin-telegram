from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, Message, Update, User

from bot.config import Config
from bot import pipeline

MEERA = User(id=999, is_bot=False, first_name="Meera")


def _config(**overrides) -> Config:
    base = dict(
        telegram_bot_token="TEST:TOKEN",
        gemini_api_key="gemini-key",
        supabase_url="https://example.supabase.co",
        supabase_key="supabase-key",
        notes_channel_id="-100111",
        review_chat_id="222",
        trigger_mode="auto",
        draft_model="gemini",
        anthropic_api_key="",
        telegram_webhook_secret="secret",
    )
    base.update(overrides)
    return Config(**base)


def _update(text, chat_id=222, update_id=1):
    chat = Chat(id=chat_id, type=Chat.PRIVATE)
    message = Message(message_id=1, date=None, chat=chat, text=text, from_user=MEERA)
    return Update(update_id=update_id, message=message)


@pytest.mark.asyncio
async def test_auto_mode_drafts_and_sends_on_new_note():
    config = _config(trigger_mode="auto")
    update = _update("Customer said our serum stings for the first two uses.")

    with (
        patch("bot.pipeline.db") as mock_db,
        patch("bot.pipeline.gemini") as mock_gemini,
        patch("bot.pipeline.Bot") as mock_bot_cls,
    ):
        mock_db.insert_note_if_new.return_value = {"id": 42, "text": update.message.text}
        mock_db.get_voice_skill.return_value = "voice skill content"
        mock_gemini.generate_draft.return_value = "Drafted post text."
        mock_bot = mock_bot_cls.return_value
        mock_bot.send_message = AsyncMock()

        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_gemini.generate_draft.assert_called_once()
        _, kwargs = mock_gemini.generate_draft.call_args
        assert kwargs["voice_skill"] == "voice skill content"
        mock_db.insert_draft.assert_called_once()
        mock_bot.send_message.assert_awaited_once_with(chat_id=222, text="Drafted post text.")


@pytest.mark.asyncio
async def test_duplicate_update_id_is_skipped_no_gemini_call():
    config = _config(trigger_mode="auto")
    update = _update("Same note, retried by Telegram.", update_id=7)

    with (
        patch("bot.pipeline.db") as mock_db,
        patch("bot.pipeline.gemini") as mock_gemini,
        patch("bot.pipeline.Bot") as mock_bot_cls,
    ):
        mock_db.insert_note_if_new.return_value = None  # already exists -> dedup hit
        mock_bot = mock_bot_cls.return_value
        mock_bot.send_message = AsyncMock()

        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_gemini.generate_draft.assert_not_called()
        mock_bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_disallowed_chat_is_ignored_no_db_write():
    config = _config(trigger_mode="auto")
    update = _update("random stranger message", chat_id=999999)

    with patch("bot.pipeline.db") as mock_db, patch("bot.pipeline.gemini") as mock_gemini:
        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_db.insert_note_if_new.assert_not_called()
        mock_gemini.generate_draft.assert_not_called()


@pytest.mark.asyncio
async def test_topic_mode_plain_note_is_silent():
    config = _config(trigger_mode="topic")
    update = _update("Batch pH came back at 5.2 today.")

    with (
        patch("bot.pipeline.db") as mock_db,
        patch("bot.pipeline.gemini") as mock_gemini,
        patch("bot.pipeline.Bot") as mock_bot_cls,
    ):
        mock_db.insert_note_if_new.return_value = {"id": 1, "text": update.message.text}
        mock_db.get_voice_skill.return_value = "voice skill content"
        mock_bot = mock_bot_cls.return_value
        mock_bot.send_message = AsyncMock()

        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_gemini.generate_draft.assert_not_called()
        mock_bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_topic_mode_draft_trigger_uses_best_matching_note():
    config = _config(trigger_mode="topic")
    update = _update("/draft niacinamide")

    with (
        patch("bot.pipeline.db") as mock_db,
        patch("bot.pipeline.gemini") as mock_gemini,
        patch("bot.pipeline.Bot") as mock_bot_cls,
    ):
        mock_db.insert_note_if_new.return_value = {"id": 5, "text": "/draft niacinamide"}
        mock_db.get_voice_skill.return_value = "voice skill content"
        mock_db.find_best_matching_note.return_value = {"id": 3, "text": "Niacinamide converts to niacin below pH 4."}
        mock_gemini.generate_draft.return_value = "Drafted from stored note."
        mock_bot = mock_bot_cls.return_value
        mock_bot.send_message = AsyncMock()

        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_gemini.generate_draft.assert_called_once()
        _, kwargs = mock_gemini.generate_draft.call_args
        assert kwargs["note_text"] == "Niacinamide converts to niacin below pH 4."
        mock_bot.send_message.assert_awaited_once_with(chat_id=222, text="Drafted from stored note.")


@pytest.mark.asyncio
async def test_topic_mode_no_match_says_so_and_drafts_nothing():
    config = _config(trigger_mode="topic")
    update = _update("Topic: astrophysics")

    with (
        patch("bot.pipeline.db") as mock_db,
        patch("bot.pipeline.gemini") as mock_gemini,
        patch("bot.pipeline.Bot") as mock_bot_cls,
    ):
        mock_db.insert_note_if_new.return_value = {"id": 6, "text": "Topic: astrophysics"}
        mock_db.get_voice_skill.return_value = "voice skill content"
        mock_db.find_best_matching_note.return_value = None
        mock_bot = mock_bot_cls.return_value
        mock_bot.send_message = AsyncMock()

        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_gemini.generate_draft.assert_not_called()
        mock_bot.send_message.assert_awaited_once()
        assert "No notes match" in mock_bot.send_message.call_args.kwargs["text"]
