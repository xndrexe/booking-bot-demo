"""Хранилище SQLite в памяти: клиенты, пересечения записей, выборки."""

from datetime import datetime

from booking.db import ACTIVE, CANCELLED, Client

NOW = datetime(2026, 10, 14, 8, 0)


def book(storage, start, end, master_id=1, user=("tg", "5"), created_at=NOW):
    return storage.book(
        platform=user[0],
        user_id=user[1],
        client_name="Тест",
        phone="+7 900 000-00-01",
        service_id=1,
        master_id=master_id,
        start=start,
        end=end,
        created_at=created_at,
    )


def test_client_roundtrip(storage):
    empty = storage.get_client("max", "1")
    assert (empty.name, empty.phone, empty.state, empty.draft) == (None, None, None, {})

    storage.save_client(
        Client("max", "1", "Мария", "+7 900 111-22-33", "ask_phone", {"start": "2026-10-15T12:00"})
    )
    storage.save_client(Client("max", "1", "Мария", "+7 900 111-22-33", None, {}))
    got = storage.get_client("max", "1")
    assert (got.name, got.state, got.draft) == ("Мария", None, {})
    # тот же id в другом мессенджере — другой клиент
    assert storage.get_client("tg", "1").name is None


def test_adjacent_bookings_allowed_overlap_rejected(storage):
    first = book(storage, datetime(2026, 10, 15, 12), datetime(2026, 10, 15, 13))
    assert first.status == ACTIVE and first.reminded is False
    assert book(storage, datetime(2026, 10, 15, 13), datetime(2026, 10, 15, 14)) is not None
    assert book(storage, datetime(2026, 10, 15, 11), datetime(2026, 10, 15, 12)) is not None
    assert book(storage, datetime(2026, 10, 15, 12, 30), datetime(2026, 10, 15, 13, 30)) is None
    # у другого мастера то же время свободно
    assert book(storage, datetime(2026, 10, 15, 12), datetime(2026, 10, 15, 13), master_id=2) is not None
    assert len(storage.all_appointments()) == 4


def test_cancelled_booking_frees_time(storage):
    appt = book(storage, datetime(2026, 10, 15, 12), datetime(2026, 10, 15, 13))
    storage.cancel(appt.id)
    assert storage.get_appointment(appt.id).status == CANCELLED
    assert storage.busy_intervals(1, datetime(2026, 10, 15), datetime(2026, 10, 16)) == []
    assert book(storage, datetime(2026, 10, 15, 12), datetime(2026, 10, 15, 13)) is not None


def test_storage_usable_after_rejected_booking(storage):
    book(storage, datetime(2026, 10, 15, 12), datetime(2026, 10, 15, 13))
    assert book(storage, datetime(2026, 10, 15, 12), datetime(2026, 10, 15, 13)) is None
    # транзакция откатилась — следующая запись проходит
    assert book(storage, datetime(2026, 10, 15, 14), datetime(2026, 10, 15, 15)) is not None


def test_queries(storage):
    past = book(storage, datetime(2026, 10, 14, 7), datetime(2026, 10, 14, 8))
    today = book(storage, datetime(2026, 10, 14, 12), datetime(2026, 10, 14, 13))
    tomorrow = book(storage, datetime(2026, 10, 15, 12), datetime(2026, 10, 15, 13))
    other = book(storage, datetime(2026, 10, 15, 14), datetime(2026, 10, 15, 15), user=("max", "5"))
    gone = book(storage, datetime(2026, 10, 16, 12), datetime(2026, 10, 16, 13))
    storage.cancel(gone.id)

    upcoming = storage.upcoming_for_client("tg", "5", NOW)
    assert [a.id for a in upcoming] == [today.id, tomorrow.id]

    day = storage.active_between(datetime(2026, 10, 14), datetime(2026, 10, 15))
    assert [a.id for a in day] == [past.id, today.id]

    due = storage.not_reminded_before(NOW, datetime(2026, 10, 15, 12))
    assert [a.id for a in due] == [today.id, tomorrow.id]  # граница until включена
    storage.mark_reminded(today.id)
    assert storage.get_appointment(today.id).reminded is True
    assert [a.id for a in storage.not_reminded_before(NOW, datetime(2026, 10, 15, 12))] == [tomorrow.id]

    assert [a.id for a in storage.all_appointments()] == [past.id, today.id, tomorrow.id, other.id, gone.id]
    assert storage.get_appointment(999) is None
