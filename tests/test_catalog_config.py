"""Каталог из JSON и настройки из окружения — без настоящего .env."""

import json
from datetime import time
from pathlib import Path

import pytest

from booking import config
from booking.catalog import load_catalog

BUSINESS = {
    "name": "Тест",
    "address": "адрес",
    "phone": "+7 900 000-00-00",
    "hours": "10–20",
    "timezone": "Europe/Moscow",
    "slot_step_min": 15,
    "booking_days": 7,
    "min_lead_min": 30,
}


def write_catalog(tmp_path, masters):
    path = tmp_path / "catalog.json"
    raw = {
        "business": BUSINESS,
        "services": [{"id": 1, "name": "Стрижка", "duration_min": 60, "price": 1000}],
        "masters": masters,
    }
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def master(**over):
    base = {
        "id": 1,
        "name": "Анна",
        "title": "стилист",
        "services": [1],
        "weekdays": [1, 2],
        "start": "09:30",
        "end": "18:00",
    }
    return {**base, **over}


def test_load_catalog_parses_types(tmp_path):
    catalog = load_catalog(write_catalog(tmp_path, [master()]))
    anna = catalog.masters[1]
    assert (anna.start, anna.end) == (time(9, 30), time(18, 0))
    assert anna.weekdays == frozenset({1, 2})
    assert catalog.business.slot_step_min == 15
    assert catalog.masters_for(1) == [anna]
    assert catalog.masters_for(2) == []


def test_load_catalog_rejects_unknown_service(tmp_path):
    with pytest.raises(ValueError, match="unknown services \\[7\\]"):
        load_catalog(write_catalog(tmp_path, [master(services=[1, 7])]))


@pytest.mark.parametrize(
    ("over", "error"),
    [
        ({"start": "18:00", "end": "09:30"}, "must be before end"),
        ({"start": "10:00", "end": "10:00"}, "must be before end"),
        ({"weekdays": [0, 1]}, "weekdays must be 1..7"),
        ({"weekdays": []}, "weekdays must be 1..7"),
    ],
)
def test_load_catalog_rejects_bad_schedule(tmp_path, over, error):
    with pytest.raises(ValueError, match=error):
        load_catalog(write_catalog(tmp_path, [master(**over)]))


def test_demo_catalog_masters_cover_every_service(catalog):
    for service_id in catalog.services:
        assert catalog.masters_for(service_id), service_id


def test_load_settings(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)  # настоящий .env не читаем
    monkeypatch.setenv("ADMINS", " tg:1, max:2 ,,")
    monkeypatch.setenv("TG_BOT_TOKEN", "")
    monkeypatch.setenv("MAX_BOT_TOKEN", "abc")
    monkeypatch.setenv("DB_PATH", "/var/x.db")
    monkeypatch.delenv("CATALOG_PATH", raising=False)
    monkeypatch.delenv("GSHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CREDENTIALS", raising=False)

    s = config.load_settings()
    assert s.admins == {"tg:1", "max:2"}
    assert s.tg_token is None  # пустая строка — это «нет токена»
    assert s.max_token == "abc"
    assert s.db_path == Path("/var/x.db")
    assert s.catalog_path == config.ROOT / "data" / "catalog.json"
    assert s.gsheet_id is None and s.google_credentials is None


def test_load_settings_without_admins(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("ADMINS", raising=False)
    assert config.load_settings().admins == set()
