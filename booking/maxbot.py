"""Адаптер мессенджера MAX на библиотеке maxapi (API в стиле aiogram)."""

from __future__ import annotations

from maxapi import Bot, Dispatcher
from maxapi.enums.chat_type import ChatType
from maxapi.enums.parse_mode import ParseMode
from maxapi.types import BotStarted, CallbackButton, MessageCallback, MessageCreated
from maxapi.types.input_media import InputMediaBuffer
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from booking.flow import BookingBot, Reply

PLATFORM = "max"


def attachments(reply: Reply) -> list:
    result: list = []
    if reply.file_bytes is not None:
        result.append(InputMediaBuffer(reply.file_bytes, filename=reply.file_name))
    if reply.buttons:
        builder = InlineKeyboardBuilder()
        for row in reply.buttons:
            builder.row(*(CallbackButton(text=b.text, payload=b.data) for b in row))
        result.append(builder.as_markup())
    return result


async def send(bot: Bot, user_id: int, reply: Reply) -> None:
    await bot.send_message(
        user_id=user_id,
        text=reply.text,
        attachments=attachments(reply) or None,
        format=ParseMode.HTML,
    )


def build(core: BookingBot, token: str) -> tuple[Bot, Dispatcher]:
    bot = Bot(token)
    dp = Dispatcher()

    @dp.bot_started()
    async def on_started(event: BotStarted) -> None:
        user_id = event.user.user_id
        for reply in await core.handle_text(PLATFORM, str(user_id), "/start"):
            await send(bot, user_id, reply)

    @dp.message_created()
    async def on_text(event: MessageCreated) -> None:
        message = event.message
        if message.sender is None or message.sender.is_bot or message.body is None or not message.body.text:
            return
        # только личный диалог: реплика из группы не должна попадать в запись (например, стать именем)
        if message.recipient.chat_type != ChatType.DIALOG:
            return
        user_id = message.sender.user_id
        for reply in await core.handle_text(PLATFORM, str(user_id), message.body.text):
            await send(bot, user_id, reply)

    @dp.message_callback()
    async def on_button(event: MessageCallback) -> None:
        await event.ack()
        user_id = event.callback.user.user_id
        for reply in await core.handle_callback(PLATFORM, str(user_id), event.callback.payload or ""):
            await send(bot, user_id, reply)

    async def send_to_user(user_id: str, reply: Reply) -> None:
        await send(bot, int(user_id), reply)

    core.senders[PLATFORM] = send_to_user
    return bot, dp
