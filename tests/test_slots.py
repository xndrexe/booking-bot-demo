from datetime import date, datetime

import pytest

from booking.slots import free_by_time, free_starts, open_days
from booking.texts import normalize_phone


def test_master_day_off_has_no_slots(catalog, storage):
    anna, haircut = catalog.masters[1], catalog.services[1]
    saturday = date(2026, 10, 17)
    assert free_starts(catalog, storage, anna, haircut, saturday, datetime(2026, 10, 14, 8)) == []


def test_grid_respects_lead_time_and_closing(catalog, storage):
    anna, haircut = catalog.masters[1], catalog.services[1]
    starts = free_starts(catalog, storage, anna, haircut, date(2026, 10, 14), datetime(2026, 10, 14, 9, 30))
    # до 10:30 — меньше часа до визита; последний час 18:00–19:00
    assert starts[0] == datetime(2026, 10, 14, 10, 30)
    assert starts[-1] == datetime(2026, 10, 14, 18, 0)


def test_busy_interval_blocks_overlapping_starts(catalog, storage):
    anna, haircut = catalog.masters[1], catalog.services[1]
    storage.book(
        platform="tg",
        user_id="5",
        client_name="Тест",
        phone="+7 900 000-00-01",
        service_id=1,
        master_id=1,
        start=datetime(2026, 10, 15, 12, 0),
        end=datetime(2026, 10, 15, 13, 0),
        created_at=datetime(2026, 10, 14, 8),
    )
    starts = free_starts(catalog, storage, anna, haircut, date(2026, 10, 15), datetime(2026, 10, 14, 8))
    times = {s.strftime("%H:%M") for s in starts}
    assert {"11:30", "12:00", "12:30"}.isdisjoint(times)
    assert {"11:00", "13:00"} <= times


def test_any_master_picks_first_free(catalog, storage):
    haircut = catalog.services[1]
    masters = catalog.masters_for(1)
    friday = date(2026, 10, 16)
    free = free_by_time(catalog, storage, masters, haircut, friday, datetime(2026, 10, 14, 8))
    assert free[datetime(2026, 10, 16, 10, 0)].name == "Анна"  # Марина начинает в 11:00
    assert free[datetime(2026, 10, 16, 19, 0)].name == "Марина"  # Анна до 19:00


def test_open_days_skips_days_off(catalog, storage):
    anna, haircut = catalog.masters[1], catalog.services[1]
    days = open_days(catalog, storage, [anna], haircut, datetime(2026, 10, 14, 8))
    assert all(d.isoweekday() <= 5 for d in days)
    assert days[0] == date(2026, 10, 14)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+7 (900) 123-45-67", "+7 900 123-45-67"),
        ("89001234567", "+7 900 123-45-67"),
        ("9001234567", "+7 900 123-45-67"),
        ("12345", None),
        ("+7 100 123 45 67", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected
