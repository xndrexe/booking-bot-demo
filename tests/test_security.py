"""Дыры, найденные проверкой безопасности: на каждую — тест."""

import io
import sys
import types

from openpyxl import load_workbook
from test_flow import CLIENT, book_haircut, datas, press, say

from booking.gsheet import GoogleSheet

OWNER = ("tg", "1")


async def test_forged_button_cannot_book_past_horizon(bot, storage):
    # горизонт — 14 дней от среды 14.10; четверг 29.10 уже за ним, 17.12 — тем более
    for start in ("202610291200", "202612171200"):
        times = await press(bot, f"d:1:1:{start[:8]}")
        assert not any(d.startswith("t:") for d in datas(times))
        await book_haircut(bot, start=start)
        await press(bot, "ok")
    assert storage.all_appointments() == []


async def test_day_inside_horizon_still_bookable(bot, storage):
    await book_haircut(bot, start="202610221200")
    await press(bot, "ok")
    assert len(storage.all_appointments()) == 1


async def test_huge_id_in_button_returns_menu(bot):
    for data in ("c:99999999999999999999999", "cy:99999999999999999999999"):
        assert "book" in datas(await press(bot, data))


async def test_formula_in_name_is_text_in_excel(bot):
    await book_haircut(bot, name='=HYPERLINK("http://evil","Жми")')
    await press(bot, "ok")
    export = await press(bot, "x", OWNER)
    cell = load_workbook(io.BytesIO(export.file_bytes)).active["F2"]
    assert cell.data_type == "s"
    assert cell.value == '=HYPERLINK("http://evil","Жми")'


def test_formula_in_name_is_text_in_google_sheet(monkeypatch):
    sent = {}

    class Ws:
        def clear(self):
            pass

        def update(self, values, value_input_option):
            sent["values"] = values

        def freeze(self, rows):
            pass

    book = types.SimpleNamespace(worksheet=lambda title: Ws())
    monkeypatch.setitem(
        sys.modules,
        "gspread",
        types.SimpleNamespace(
            service_account=lambda filename: types.SimpleNamespace(open_by_key=lambda key: book),
            WorksheetNotFound=Exception,
        ),
    )
    row = ["=IMPORTXML(1)", "+7 900 111-22-33", "-1", "@x", "Мария", 2500]
    GoogleSheet("S", "k.json").push([row])
    assert sent["values"][1] == ["'=IMPORTXML(1)", "'+7 900 111-22-33", "'-1", "'@x", "Мария", 2500]


async def test_forged_numbers_in_any_button_return_menu(bot):
    huge = "9" * 25
    forged = [
        f"s:{huge}",
        f"m:1:{huge}",
        f"d:1:1:{huge}",
        f"t:1:1:{huge}",
        f"c:{huge}",
        f"cy:{huge}",
        "s:-1",
        "m:x:1",
        "d:1:1:20261399",
        "t:1:1:2026101512",
        "c:",
    ]
    for data in forged:
        replies = await bot.handle_callback(*CLIENT, data)
        assert replies, data


async def test_invisible_and_rtl_chars_removed_from_name(bot, storage):
    await book_haircut(bot, name="\u202eМария\u200b\u2066 Ива\u200dнова\u2069")
    await press(bot, "ok")
    assert [a.client_name for a in storage.all_appointments()] == ["Мария Иванова"]


async def test_name_of_only_invisible_chars_rejected(bot):
    await press(bot, "book")
    await press(bot, "s:1")
    await press(bot, "m:1:1")
    await press(bot, "d:1:1:20261015")
    await press(bot, "t:1:1:202610151200")
    reply = await say(bot, "\u200b\u200b\u202e\u200b")
    assert "от 2 до 40" in reply.text
