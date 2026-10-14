"""Адаптеры без сети: настоящие диспетчеры aiogram и maxapi, подменена только отправка."""

from datetime import datetime

from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendDocument, SendMessage
from aiogram.types import Chat, Message, Update
from maxapi.types import MessageCallback, MessageCreated

from booking import maxbot, tg
from booking.flow import Button, Reply

USER = {"id": 42, "is_bot": False, "first_name": "Мария"}


class FakeTelegram(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, SendDocument)):
            return Message(
                message_id=len(self.calls), date=datetime.now(), chat=Chat(id=method.chat_id, type="private")
            )
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError


def tg_message(text):
    return Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "text": text,
                "chat": {"id": 42, "type": "private"},
                "from": USER,
            },
        }
    )


def tg_button(data):
    return Update.model_validate(
        {
            "update_id": 2,
            "callback_query": {"id": "cb1", "chat_instance": "x", "data": data, "from": USER},
        }
    )


async def test_telegram_dialog_and_owner_file(bot):
    tg_bot, dp = tg.build(bot, "42:TEST")
    session = FakeTelegram()
    tg_bot.session = session

    await dp.feed_update(tg_bot, tg_message("/start"))
    (sent,) = session.calls
    assert isinstance(sent, SendMessage) and "Лаванда" in sent.text
    first_row = sent.reply_markup.inline_keyboard[0]
    assert first_row[0].callback_data == "book"

    session.calls.clear()
    await dp.feed_update(tg_bot, tg_button("s:1"))
    answer, masters = session.calls
    assert isinstance(answer, AnswerCallbackQuery)
    assert "к кому записать" in masters.text

    bot.admins.add("tg:42")
    session.calls.clear()
    await dp.feed_update(tg_bot, tg_button("x"))
    assert isinstance(session.calls[-1], SendDocument)


async def test_callback_data_fits_telegram_limit(bot):
    """В Telegram данные кнопки — не больше 64 байт."""
    longest = Reply("", [[Button("x", "t:999:999:202612312330")], [Button("x", "cy:99999999")]])
    for row in tg.keyboard(longest).inline_keyboard:
        assert all(len(b.callback_data.encode()) <= 64 for b in row)


def max_text(text):
    return MessageCreated.model_validate(
        {
            "update_type": "message_created",
            "timestamp": 0,
            "message": {
                "sender": {"user_id": 77, "first_name": "Мария", "is_bot": False, "last_activity_time": 0},
                "recipient": {"chat_id": 5, "chat_type": "dialog"},
                "timestamp": 0,
                "body": {"mid": "m1", "seq": 1, "text": text},
            },
        }
    )


def max_button(payload):
    return MessageCallback.model_validate(
        {
            "update_type": "message_callback",
            "timestamp": 0,
            "callback": {
                "timestamp": 0,
                "callback_id": "cb1",
                "payload": payload,
                "user": {"user_id": 77, "first_name": "Мария", "is_bot": False, "last_activity_time": 0},
            },
        }
    )


async def test_max_dialog(bot, monkeypatch):
    max_bot, dp = maxbot.build(bot, "TEST")
    sent, acks = [], []

    async def fake_send_message(**kwargs):
        sent.append(kwargs)

    async def fake_send_callback(**kwargs):
        acks.append(kwargs)

    monkeypatch.setattr(max_bot, "send_message", fake_send_message)
    monkeypatch.setattr(max_bot, "send_callback", fake_send_callback)

    async def no_network():
        pass

    monkeypatch.setattr(dp, "check_me", no_network)
    await dp.startup(max_bot)

    await dp.handle(max_text("/start"))
    assert sent[0]["user_id"] == 77
    assert "Лаванда" in sent[0]["text"]
    keyboard = sent[0]["attachments"][-1]
    assert keyboard.payload.buttons[0][0].payload == "book"

    event = max_button("s:1")
    event.bot = max_bot
    await dp.handle(event)
    assert acks and "к кому записать" in sent[-1]["text"]


def test_max_attachments_with_file():
    reply = Reply("Выгрузка", [[Button("« Назад", "menu")]], file_name="a.xlsx", file_bytes=b"PK\x03\x04")
    file_part, keyboard = maxbot.attachments(reply)
    assert file_part.filename == "a.xlsx"
    assert keyboard.payload.buttons[0][0].text == "« Назад"
