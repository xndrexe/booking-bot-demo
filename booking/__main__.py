"""Запуск: python -m booking — поднимает Telegram и/или MAX, у кого есть токен."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from booking.catalog import load_catalog
from booking.config import load_settings
from booking.db import Storage
from booking.flow import BookingBot

log = logging.getLogger("booking")
REMINDER_PERIOD_S = 60


async def reminder_loop(core: BookingBot) -> None:
    while True:
        try:
            sent = await core.send_due_reminders()
            if sent:
                log.info("reminders sent: %s", sent)
        except Exception:
            log.exception("reminder loop failed")
        await asyncio.sleep(REMINDER_PERIOD_S)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    if not settings.tg_token and not settings.max_token:
        raise SystemExit("Нет токенов: задайте TG_BOT_TOKEN и/или MAX_BOT_TOKEN в .env")
    catalog = load_catalog(settings.catalog_path)
    tz = ZoneInfo(catalog.business.timezone)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    sheet = None
    if settings.gsheet_id and settings.google_credentials:
        from booking.gsheet import GoogleSheet

        sheet = GoogleSheet(settings.gsheet_id, settings.google_credentials)
        log.info("google sheet: on")
    core = BookingBot(
        catalog,
        Storage(settings.db_path),
        admins=settings.admins,
        clock=lambda: datetime.now(tz).replace(tzinfo=None),
        sheet=sheet,
    )

    runners = []
    if settings.tg_token:
        from booking import tg

        bot, dp = tg.build(core, settings.tg_token)
        runners.append(dp.start_polling(bot, handle_signals=False))
        log.info("telegram: on")
    if settings.max_token:
        from booking import maxbot

        bot, dp = maxbot.build(core, settings.max_token)
        runners.append(dp.start_polling(bot))
        log.info("max: on")
    await asyncio.gather(reminder_loop(core), *runners)


if __name__ == "__main__":
    asyncio.run(main())
