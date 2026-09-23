from telegram import Chat, Message, MessageEntity, Update, User

from bot.router import Classification, classify, is_trigger_text

REVIEW_CHAT_ID = "111"
NOTES_CHANNEL_ID = "-1004434074659"

MEERA = User(id=999, is_bot=False, first_name="Meera")
BOT_USER = User(id=1, is_bot=True, first_name="SkinBot")
STRANGER = User(id=555, is_bot=False, first_name="Rando")


def _private_chat(chat_id=int(REVIEW_CHAT_ID)):
    return Chat(id=chat_id, type=Chat.PRIVATE)


def _channel_chat():
    return Chat(id=int(NOTES_CHANNEL_ID), type=Chat.CHANNEL)


def _msg(text, chat, user=MEERA, message_id=1, is_channel_post=False, reply_to_message=None, voice=None):
    kwargs = dict(
        message_id=message_id,
        date=None,
        chat=chat,
        text=text,
        from_user=None if is_channel_post else user,
        reply_to_message=reply_to_message,
        voice=voice,
    )
    if text and text.startswith("/"):
        cmd_len = len(text.split()[0])
        kwargs["entities"] = [MessageEntity(type=MessageEntity.BOT_COMMAND, offset=0, length=cmd_len)]
    return Message(**kwargs)


def _update_from_message(message, is_channel_post=False):
    if is_channel_post:
        return Update(update_id=1, channel_post=message)
    return Update(update_id=1, message=message)


def classify_(update):
    return classify(update, review_chat_id=REVIEW_CHAT_ID, notes_channel_id=NOTES_CHANNEL_ID)


def test_normal_channel_note_is_note():
    msg = _msg("Customer told me our serum smells too clinical today.", _channel_chat(), is_channel_post=True)
    update = _update_from_message(msg, is_channel_post=True)
    assert classify_(update) == Classification.NOTE


def test_sticker_in_channel_is_ignored():
    msg = _msg(None, _channel_chat(), is_channel_post=True)
    update = _update_from_message(msg, is_channel_post=True)
    assert classify_(update) == Classification.IGNORE


def test_stranger_private_chat_is_ignored():
    msg = _msg("hey what does this bot do", _private_chat(chat_id=777), user=STRANGER)
    update = _update_from_message(msg)
    assert classify_(update) == Classification.IGNORE


def test_slash_topic_in_review_chat():
    msg = _msg("/topic niacinamide", _private_chat())
    update = _update_from_message(msg)
    assert classify_(update) == Classification.TOPIC


def test_topic_label_form():
    msg = _msg("Topic: sunscreen myths", _private_chat())
    update = _update_from_message(msg)
    assert classify_(update) == Classification.TOPIC


def test_slash_draft():
    msg = _msg("/draft niacinamide", _private_chat())
    update = _update_from_message(msg)
    assert classify_(update) == Classification.DRAFT


def test_draft_label_form():
    msg = _msg("Draft: pH myths", _private_chat())
    update = _update_from_message(msg)
    assert classify_(update) == Classification.DRAFT


def test_natural_language_draft_request():
    msg = _msg("write a post about our pH testing process", _private_chat())
    update = _update_from_message(msg)
    assert classify_(update) == Classification.DRAFT


def test_natural_language_draft_linkedin_variant():
    msg = _msg("draft a linkedin post on sunscreen", _private_chat())
    update = _update_from_message(msg)
    assert classify_(update) == Classification.DRAFT


def test_draft_idea_n_form():
    msg = _msg("/draft idea 2", _private_chat())
    update = _update_from_message(msg)
    assert classify_(update) == Classification.DRAFT


def test_trigger_in_channel_is_not_a_note():
    msg = _msg("/topic niacinamide", _channel_chat(), is_channel_post=True)
    update = _update_from_message(msg, is_channel_post=True)
    result = classify_(update)
    assert result == Classification.TOPIC
    assert result != Classification.NOTE


def test_draft_trigger_in_channel():
    msg = _msg("Draft: sunscreen", _channel_chat(), is_channel_post=True)
    update = _update_from_message(msg, is_channel_post=True)
    assert classify_(update) == Classification.DRAFT


def test_plain_note_mentioning_write_is_not_a_draft_trigger():
    msg = _msg("wrote up the batch notes for today, nothing special", _private_chat())
    update = _update_from_message(msg)
    assert classify_(update) == Classification.IGNORE


def test_help_command_in_review_chat():
    msg = _msg("/help", _private_chat())
    update = _update_from_message(msg)
    assert classify_(update) == Classification.HELP


def test_start_command_in_review_chat_once_configured():
    msg = _msg("/start", _private_chat())
    update = _update_from_message(msg)
    assert classify_(update) == Classification.HELP


def test_start_in_other_private_chat_is_ignored_once_configured():
    msg = _msg("/start", _private_chat(chat_id=42), user=STRANGER)
    update = _update_from_message(msg)
    assert classify_(update) == Classification.IGNORE


def test_setup_when_review_chat_id_unset():
    msg = _msg("/start", _private_chat(chat_id=42), user=STRANGER)
    update = _update_from_message(msg)
    result = classify(update, review_chat_id="", notes_channel_id=NOTES_CHANNEL_ID)
    assert result == Classification.SETUP


def test_reply_to_edit_prompt_is_review():
    bot_prompt = _msg("Send your edited version", _private_chat(), user=BOT_USER, message_id=10)
    reply = _msg("Here is my rewritten version of the post.", _private_chat(), message_id=11, reply_to_message=bot_prompt)
    update = _update_from_message(reply)
    assert classify_(update) == Classification.REVIEW


def test_reply_to_unrelated_bot_message_is_ignored():
    bot_prompt = _msg("Working on 'niacinamide'...", _private_chat(), user=BOT_USER, message_id=10)
    reply = _msg("thanks", _private_chat(), message_id=11, reply_to_message=bot_prompt)
    update = _update_from_message(reply)
    assert classify_(update) == Classification.IGNORE


def test_is_trigger_text_helper():
    assert is_trigger_text("/topic niacinamide")
    assert is_trigger_text("Topic: pH")
    assert is_trigger_text("/draft idea 2")
    assert is_trigger_text("Draft: sunscreen")
    assert is_trigger_text("write a linkedin post about pH")
    assert not is_trigger_text("just a normal note about the batch")
