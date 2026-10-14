"""Копия записей в Google Таблице: без сети, gspread подменён."""

import sys
import types

from test_flow import book_haircut, press

from booking.export import COLUMNS
from booking.gsheet import GoogleSheet


class Sink:
    def __init__(self, fail=False):
        self.pushes, self.fail = [], fail

    def push(self, rows):
        if self.fail:
            raise ConnectionError("google down")
        self.pushes.append(rows)


async def test_sheet_follows_booking_and_cancel(bot, storage):
    bot.sheet = sink = Sink()
    await book_haircut(bot)
    await press(bot, "ok")
    (row,) = sink.pushes[-1]
    assert row[3:7] == ["Женская стрижка", "Анна", "Мария", "+7 900 111-22-33"]
    assert row[9] == "активна"

    (appt,) = storage.all_appointments()
    await press(bot, f"c:{appt.id}")
    await press(bot, f"cy:{appt.id}")
    assert sink.pushes[-1][0][9] == "отменена"
    assert len(sink.pushes) == 2


async def test_google_failure_does_not_break_booking(bot, storage, outbox):
    bot.sheet = Sink(fail=True)
    await book_haircut(bot)
    done = await press(bot, "ok")
    assert "записаны" in done.text
    assert len(storage.all_appointments()) == 1
    assert "Новая запись" in outbox.sent[-1][2].text  # владелец всё равно узнал


class FakeWs:
    def __init__(self):
        self.data = None
        self.cleared = False

    def clear(self):
        self.cleared = True

    def update(self, values, value_input_option):
        self.data = values

    def freeze(self, rows):
        pass


class NotFound(Exception):
    pass


def test_google_sheet_push(monkeypatch):
    ws = FakeWs()
    opened = {}

    class Book:
        def worksheet(self, title):
            raise NotFound(title)

        def add_worksheet(self, title, rows, cols):
            opened["title"] = title
            return ws

    def service_account(filename):
        opened["creds"] = filename
        return types.SimpleNamespace(open_by_key=lambda key: opened.setdefault("key", key) and Book())

    monkeypatch.setitem(
        sys.modules,
        "gspread",
        types.SimpleNamespace(service_account=service_account, WorksheetNotFound=NotFound),
    )
    from datetime import date

    GoogleSheet("SHEET1", "/keys/sa.json").push([[1, date(2026, 10, 15), "12:00", "Стрижка"]])
    assert opened == {"creds": "/keys/sa.json", "key": "SHEET1", "title": "Записи"}
    assert ws.cleared
    assert ws.data[0] == [t for t, _ in COLUMNS]
    assert ws.data[1] == [1, "15.10.2026", "12:00", "Стрижка"]  # дата — строкой, gspread не берёт date
