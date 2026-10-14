"""Адаптер Telegram на aiogram 3."""

from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from booking.flow import BookingBot, Reply

PLATFORM = "tg"


def keyboard(reply: Reply) -> InlineKeyboardMarkup | None:
    if not reply.buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b.text, callback_data=b.data) for b in row] for row in reply.buttons
        ]
    )


async def send(bot: Bot, chat_id: int | str, reply: Reply) -> None:
    if reply.file_bytes is not None:
        await bot.send_document(
            chat_id,
            BufferedInputFile(reply.file_bytes, filename=reply.file_name or "file"),
            caption=reply.text,
            reply_markup=keyboard(reply),
        )
        return
    await bot.send_message(chat_id, reply.text, reply_markup=keyboard(reply))


def build(core: BookingBot, token: str) -> tuple[Bot, Dispatcher]:
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    router = Router()

    @router.message(F.text)
    async def on_text(message: Message) -> None:
        for reply in await core.handle_text(PLATFORM, str(message.from_user.id), message.text):
            await send(bot, message.chat.id, reply)

    @router.callback_query(F.data)
    async def on_button(query: CallbackQuery) -> None:
        await query.answer()
        for reply in await core.handle_callback(PLATFORM, str(query.from_user.id), query.data):
            await send(bot, query.from_user.id, reply)

    async def send_to_user(user_id: str, reply: Reply) -> None:
        await send(bot, int(user_id), reply)

    core.senders[PLATFORM] = send_to_user
    dp = Dispatcher()
    dp.include_router(router)
    return bot, dp
