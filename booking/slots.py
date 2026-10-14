"""Свободные окна: рабочий день мастера минус занятые записи, с шагом сетки салона."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from booking.catalog import Catalog, Master, Service
from booking.db import Storage


def free_starts(
    catalog: Catalog,
    storage: Storage,
    master: Master,
    service: Service,
    day: date,
    now: datetime,
) -> list[datetime]:
    """Времена начала, на которые к мастеру можно записаться на эту услугу в этот день."""
    if day.isoweekday() not in master.weekdays:
        return []
    biz = catalog.business
    opens = datetime.combine(day, master.start)
    closes = datetime.combine(day, master.end)
    duration = timedelta(minutes=service.duration_min)
    step = timedelta(minutes=biz.slot_step_min)
    earliest = now + timedelta(minutes=biz.min_lead_min)
    busy = storage.busy_intervals(master.id, opens, closes)

    result = []
    start = opens
    while start + duration <= closes:
        end = start + duration
        if start >= earliest and not any(b_start < end and b_end > start for b_start, b_end in busy):
            result.append(start)
        start += step
    return result


def free_by_time(
    catalog: Catalog,
    storage: Storage,
    masters: list[Master],
    service: Service,
    day: date,
    now: datetime,
) -> dict[datetime, Master]:
    """Время начала -> первый свободный мастер. Для выбора «любой мастер»."""
    result: dict[datetime, Master] = {}
    for master in masters:
        for start in free_starts(catalog, storage, master, service, day, now):
            result.setdefault(start, master)
    return dict(sorted(result.items()))


def open_days(
    catalog: Catalog,
    storage: Storage,
    masters: list[Master],
    service: Service,
    now: datetime,
    limit: int = 8,
) -> list[date]:
    """Ближайшие дни, где есть хоть одно окно, но не дальше горизонта записи."""
    days = []
    for offset in range(catalog.business.booking_days):
        day = now.date() + timedelta(days=offset)
        if free_by_time(catalog, storage, masters, service, day, now):
            days.append(day)
            if len(days) == limit:
                break
    return days
