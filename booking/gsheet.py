"""Копия записей в Google Таблице: обновляется после каждой записи и отмены."""

from __future__ import annotations

from datetime import date

from booking.export import COLUMNS

SHEET_TITLE = "Записи"
# с этих знаков Google Таблица в режиме USER_ENTERED начинает формулу
FORMULA_START = ("=", "+", "-", "@")


def _cell(value):
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, str) and value.startswith(FORMULA_START):
        # апостроф велит таблице хранить строку как текст; сам он в ячейке не виден
        return "'" + value
    return value


class GoogleSheet:
    """credentials — путь к ключу сервисного аккаунта Google; таблицу нужно
    расшарить на его почту с правом редактирования."""

    def __init__(self, sheet_id: str, credentials: str):
        self.sheet_id = sheet_id
        self.credentials = credentials
        self._ws = None

    def _worksheet(self):
        if self._ws is None:
            import gspread  # нужен только при выгрузке в Google

            book = gspread.service_account(filename=self.credentials).open_by_key(self.sheet_id)
            try:
                self._ws = book.worksheet(SHEET_TITLE)
            except gspread.WorksheetNotFound:
                self._ws = book.add_worksheet(SHEET_TITLE, rows=100, cols=len(COLUMNS))
        return self._ws

    def push(self, rows: list[list]) -> None:
        """Перезаписывает лист целиком: записей у салона немного, зато лист всегда совпадает с базой."""
        values = [[_cell(c) for c in r] for r in rows]
        ws = self._worksheet()
        ws.clear()
        ws.update([[title for title, _ in COLUMNS], *values], value_input_option="USER_ENTERED")
        ws.freeze(rows=1)
