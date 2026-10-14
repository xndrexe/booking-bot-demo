"""Форматирование дат, цен и телефонов для сообщений бота."""

from __future__ import annotations

import re
from datetime import date, datetime

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def day_button(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS_SHORT[day.month - 1]}"


def day_long(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"


def when(start: datetime) -> str:
    return f"{day_long(start.date())}, {start:%H:%M}"


def relative_day(start: datetime, now: datetime) -> str:
    delta = (start.date() - now.date()).days
    if delta == 0:
        return "сегодня"
    if delta == 1:
        return "завтра"
    return day_long(start.date())


def price(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"


def normalize_phone(raw: str) -> str | None:
    """Российский номер в виде +7 XXX XXX-XX-XX или None, если это не номер."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    # мобильные начинаются на 9, городские — на 3, 4 или 8
    if len(digits) != 10 or digits[0] not in "3489":
        return None
    return f"+7 {digits[:3]} {digits[3:6]}-{digits[6:8]}-{digits[8:]}"
