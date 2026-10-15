"""Форматирование дат, цен и телефонов."""

from datetime import date, datetime

import pytest

from booking import texts


def test_day_formats():
    thursday = date(2026, 10, 15)
    assert texts.day_button(thursday) == "Чт, 15 окт"
    assert texts.day_long(thursday) == "Чт, 15 октября"
    assert texts.day_button(date(2026, 5, 3)) == "Вс, 3 мая"
    assert texts.when(datetime(2026, 10, 15, 9, 5)) == "Чт, 15 октября, 09:05"


def test_relative_day():
    now = datetime(2026, 10, 14, 23, 59)
    assert texts.relative_day(datetime(2026, 10, 14, 23, 59), now) == "сегодня"
    # «завтра» считается по календарю, а не по 24 часам
    assert texts.relative_day(datetime(2026, 10, 15, 0, 1), now) == "завтра"
    assert texts.relative_day(datetime(2026, 10, 16, 10, 0), now) == "Пт, 16 октября"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 ₽"), (900, "900 ₽"), (1800, "1 800 ₽"), (1234567, "1 234 567 ₽")],
)
def test_price(value, expected):
    assert texts.price(value) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+7 812 123-45-67", "+7 812 123-45-67"),  # городской Петербург
        ("8 (495) 123 45 67", "+7 495 123-45-67"),
        ("8 800 555 35 35", "+7 800 555-35-35"),
        ("тел. 7-900-123-45-67", "+7 900 123-45-67"),
        ("", None),
        ("+7 900 123 45 6", None),  # не хватает цифры
        ("+7 900 123 45 678", None),  # лишняя цифра
        ("19001234567", None),  # 11 цифр, но не с 7 или 8
        ("5001234567", None),  # код на 5 — не российский
    ],
)
def test_normalize_phone_more(raw, expected):
    assert texts.normalize_phone(raw) == expected
