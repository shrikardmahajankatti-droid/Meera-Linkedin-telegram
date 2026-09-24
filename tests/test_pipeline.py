from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import CallbackQuery, Chat, Message, Update, User

from bot import gate
from bot.config import Config
from bot import pipeline
from bot.gate import GateResult

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
        gate_enabled=True,
        gate_on_auto_notes=True,
        gate_draft_threshold=70,
        gate_warn_threshold=50,
        gate_novelty_days=14,
        news_enabled=True,
        news_lookback_days=3,
        news_max_items=5,
        news_hl="en-IN",
        news_gl="IN",
        news_ceid="IN:en",
    )
    base.update(overrides)
    return Config(**base)


def _update(text, chat_id=222, update_id=1):
    chat = Chat(id=chat_id, type=Chat.PRIVATE)
    message = Message(message_id=1, date=None, chat=chat, text=text, from_user=MEERA)
    return Update(update_id=update_id, message=message)


def _callback_update(data, chat_id=222, update_id=1, message_id=50, bot=None):
    chat = Chat(id=chat_id, type=Chat.PRIVATE)
    message = Message(message_id=message_id, date=None, chat=chat, text="Skipped — ...", from_user=None)
    query = CallbackQuery(id="cbq1", from_user=MEERA, chat_instance="ci", data=data, message=message)
    # CallbackQuery is a frozen TelegramObject — .answer()/.edit_message_text()
    # delegate to whatever bot is bound via set_bot(), which is how PTB itself
    # wires it up for a real update; direct attribute assignment is blocked.
    if bot is not None:
        query.set_bot(bot)
        message.set_bot(bot)
    return Update(update_id=update_id, callback_query=query)


def _draft_result(**overrides) -> GateResult:
    base = dict(decision=gate.DRAFT, total_score=90, scores={}, reasons={}, hard_blocks=[], suggested_angle=None, news_items=[])
    base.update(overrides)
    return GateResult(**base)


def _mock_gate_db_defaults(mock_db):
    mock_db.get_recent_content_for_gate.return_value = []
    mock_db.get_recent_gate_topics.return_value = []
    mock_db.get_days_since_last_approved_draft.return_value = None
    mock_db.insert_gate_decision.return_value = {"id": 1}
    mock_db.mark_update_processed_if_new.return_value = True


@pytest.mark.asyncio
async def test_auto_mode_drafts_and_sends_on_new_note():
    config = _config(trigger_mode="auto")
    # Plain notes are only accepted from the notes channel, not the review
    # chat — classify() enforces this uniformly now (see Phase 0 bug #1 fix).
    update = _update("Customer said our serum stings for the first two uses.", chat_id=-100111)

    with (
        patch("bot.pipeline.db") as mock_db,
        patch("bot.pipeline.gemini") as mock_gemini,
        patch("bot.pipeline.gate.run_gate") as mock_run_gate,
        patch("bot.pipeline.news.search_news_rss", return_value=[]),
        patch("bot.pipeline.Bot") as mock_bot_cls,
    ):
        mock_db.insert_note_if_new.return_value = {"id": 42, "text": update.message.text}
        mock_db.get_voice_skill.return_value = "voice skill content"
        _mock_gate_db_defaults(mock_db)
        mock_run_gate.return_value = _draft_result()
        mock_gemini.generate_draft.return_value = "Drafted post text."
        mock_bot = mock_bot_cls.return_value
        mock_bot.send_message = AsyncMock()

        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_gemini.generate_draft.assert_called_once()
        _, kwargs = mock_gemini.generate_draft.call_args
        assert kwargs["voice_skill"] == "voice skill content"
        mock_db.insert_draft.assert_called_once()
        mock_bot.send_message.assert_awaited_once_with(chat_id=-100111, text="Drafted post text.")


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
    # Notes channel, not the review chat — only the channel accepts freeform notes.
    update = _update("Batch pH came back at 5.2 today.", chat_id=-100111)

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

        mock_db.insert_note_if_new.assert_called_once()  # stored...
        mock_gemini.generate_draft.assert_not_called()  # ...but silently, no draft
        mock_bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_topic_mode_draft_trigger_uses_best_matching_note():
    config = _config(trigger_mode="topic")
    update = _update("/draft niacinamide")

    with (
        patch("bot.pipeline.db") as mock_db,
        patch("bot.pipeline.gemini") as mock_gemini,
        patch("bot.pipeline.gate.run_gate") as mock_run_gate,
        patch("bot.pipeline.news.search_news_rss", return_value=[]),
        patch("bot.pipeline.Bot") as mock_bot_cls,
    ):
        mock_db.get_voice_skill.return_value = "voice skill content"
        mock_db.find_best_matching_note.return_value = {"id": 3, "text": "Niacinamide converts to niacin below pH 4."}
        _mock_gate_db_defaults(mock_db)
        mock_run_gate.return_value = _draft_result()
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
        mock_db.mark_update_processed_if_new.return_value = True
        mock_db.find_best_matching_note.return_value = None
        mock_bot = mock_bot_cls.return_value
        mock_bot.send_message = AsyncMock()

        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_gemini.generate_draft.assert_not_called()
        mock_bot.send_message.assert_awaited_once()
        assert "No notes match" in mock_bot.send_message.call_args.kwargs["text"]


# --- New coverage: trigger-text-not-a-note bug fix, gate outcomes, override idempotency ---


@pytest.mark.asyncio
async def test_trigger_text_is_never_stored_as_a_note():
    config = _config(trigger_mode="auto")
    update = _update("/topic niacinamide pH")

    with (
        patch("bot.pipeline.db") as mock_db,
        patch("bot.pipeline.gemini") as mock_gemini,
        patch("bot.pipeline.gate.run_gate") as mock_run_gate,
        patch("bot.pipeline.news.search_news_rss", return_value=[]),
        patch("bot.pipeline.Bot") as mock_bot_cls,
    ):
        mock_db.get_voice_skill.return_value = "voice skill content"
        mock_db.find_best_matching_note.return_value = {"id": 3, "text": "Niacinamide converts to niacin below pH 4."}
        _mock_gate_db_defaults(mock_db)
        mock_run_gate.return_value = _draft_result()
        mock_gemini.generate_draft.return_value = "Drafted."
        mock_bot_cls.return_value.send_message = AsyncMock()

        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_db.insert_note_if_new.assert_not_called()
        mock_db.mark_update_processed_if_new.assert_called_once_with(mock_db.mark_update_processed_if_new.call_args[0][0], update.update_id)


@pytest.mark.asyncio
async def test_gate_blocked_sends_message_with_buttons_no_draft():
    config = _config(trigger_mode="topic")
    update = _update("/topic a rival's lawsuit")

    with (
        patch("bot.pipeline.db") as mock_db,
        patch("bot.pipeline.gemini") as mock_gemini,
        patch("bot.pipeline.gate.run_gate") as mock_run_gate,
        patch("bot.pipeline.news.search_news_rss", return_value=[]),
        patch("bot.pipeline.Bot") as mock_bot_cls,
    ):
        mock_db.get_voice_skill.return_value = "voice skill content"
        mock_db.find_best_matching_note.return_value = {"id": 3, "text": "some note"}
        _mock_gate_db_defaults(mock_db)
        mock_run_gate.return_value = GateResult(
            decision=gate.BLOCKED,
            total_score=0,
            scores={},
            reasons={},
            hard_blocks=[{"code": "legal_allegation", "evidence": "lawsuit"}],
            suggested_angle=None,
            news_items=[],
        )
        mock_bot = mock_bot_cls.return_value
        sent = MagicMock()
        sent.message_id = 77
        mock_bot.send_message = AsyncMock(return_value=sent)

        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_gemini.generate_draft.assert_not_called()
        mock_db.insert_draft.assert_not_called()
        mock_bot.send_message.assert_awaited_once()
        _, kwargs = mock_bot.send_message.call_args
        assert "reply_markup" in kwargs
        assert "Blocked" in kwargs["text"]
        mock_db.set_gate_decision_message_id.assert_called_once()


def _bound_mock_bot() -> MagicMock:
    """A MagicMock standing in for telegram.Bot, with the async methods that
    PTB's CallbackQuery.answer()/.edit_message_text() delegate to via set_bot()."""
    bot = MagicMock()
    bot.answer_callback_query = AsyncMock()
    bot.edit_message_text = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.mark.asyncio
async def test_callback_double_press_creates_exactly_one_draft():
    config = _config(trigger_mode="topic")
    mock_bot = _bound_mock_bot()
    update = _callback_update("ovr:5", bot=mock_bot)

    stored_decision = {
        "id": 5,
        "decision": gate.SKIP,
        "note_id": 3,
        "topic": "weak fit topic",
        "hard_blocks": [],
        "news_items": [],
        "override_status": None,
        "draft_id": None,
        "suggested_angle": None,
    }

    with (
        patch("bot.pipeline.db") as mock_db,
        patch("bot.pipeline.gemini") as mock_gemini,
        patch("bot.pipeline.Bot", return_value=mock_bot),
    ):
        mock_db.get_gate_decision.return_value = stored_decision
        mock_db.get_voice_skill.return_value = "voice skill content"
        mock_db.get_note.return_value = {"id": 3, "text": "the note"}
        mock_gemini.generate_draft.return_value = "Overridden draft."
        mock_db.insert_draft.return_value = {"id": 200}
        # First press wins the compare-and-swap; a second (retried) press must lose it.
        mock_db.update_gate_decision_override.side_effect = [True, False]

        await pipeline.process_update(update, config, supabase_client=MagicMock())
        await pipeline.process_update(update, config, supabase_client=MagicMock())  # Telegram retry of the same press

        assert mock_db.insert_draft.call_count == 1
        assert mock_bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_callback_already_handled_answers_and_does_nothing():
    config = _config(trigger_mode="topic")
    mock_bot = _bound_mock_bot()
    update = _callback_update("ovr:5", bot=mock_bot)

    with patch("bot.pipeline.db") as mock_db, patch("bot.pipeline.gemini") as mock_gemini, patch("bot.pipeline.Bot", return_value=mock_bot):
        mock_db.get_gate_decision.return_value = {"id": 5, "decision": gate.SKIP, "override_status": "overridden", "draft_id": 9}

        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_bot.answer_callback_query.assert_awaited_once()
        assert "Already handled" in str(mock_bot.answer_callback_query.call_args)
        mock_gemini.generate_draft.assert_not_called()
        mock_db.insert_draft.assert_not_called()


@pytest.mark.asyncio
async def test_callback_from_non_review_chat_is_ignored():
    config = _config(trigger_mode="topic")
    mock_bot = _bound_mock_bot()
    update = _callback_update("ovr:5", chat_id=999999, bot=mock_bot)  # not REVIEW_CHAT_ID ("222")

    with patch("bot.pipeline.db") as mock_db, patch("bot.pipeline.Bot", return_value=mock_bot):
        await pipeline.process_update(update, config, supabase_client=MagicMock())

        mock_db.get_gate_decision.assert_not_called()
