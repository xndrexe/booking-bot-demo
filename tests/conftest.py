from datetime import datetime

import pytest

from booking.catalog import load_catalog
from booking.config import ROOT
from booking.db import Storage
from booking.flow import BookingBot


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Outbox:
    """Подменяет отправку в мессенджер: копит (платформа, пользователь, ответ)."""

    def __init__(self):
        self.sent = []

    def sender(self, platform: str):
        async def send(user_id, reply):
            self.sent.append((platform, user_id, reply))

        return send


@pytest.fixture
def catalog():
    return load_catalog(ROOT / "data" / "catalog.json")


@pytest.fixture
def storage():
    return Storage(":memory:")


@pytest.fixture
def clock():
    # среда, 14.10.2026, 08:00 по времени салона
    return Clock(datetime(2026, 10, 14, 8, 0))


@pytest.fixture
def outbox():
    return Outbox()


@pytest.fixture
def bot(catalog, storage, clock, outbox):
    core = BookingBot(catalog, storage, admins={"tg:1"}, clock=clock)
    core.senders["tg"] = outbox.sender("tg")
    core.senders["max"] = outbox.sender("max")
    return core
