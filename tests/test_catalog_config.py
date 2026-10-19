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


def write_raw(tmp_path, business=None, services=None, masters=None):
    path = tmp_path / "catalog.json"
    raw = {
        "business": {**BUSINESS, **(business or {})},
        "services": services or [{"id": 1, "name": "Стрижка", "duration_min": 60, "price": 1000}],
        "masters": masters or [master()],
    }
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("business", "error"),
    [
        # шаг 0 раньше вешал подбор окон в бесконечном цикле
        ({"slot_step_min": 0}, "slot_step_min must be positive"),
        ({"slot_step_min": -15}, "slot_step_min must be positive"),
        ({"booking_days": 0}, "booking_days must be positive"),
        ({"min_lead_min": -1}, "min_lead_min must not be negative"),
    ],
)
def test_load_catalog_rejects_bad_business_numbers(tmp_path, business, error):
    with pytest.raises(ValueError, match=error):
        load_catalog(write_raw(tmp_path, business=business))


def test_load_catalog_accepts_zero_lead_time(tmp_path):
    assert load_catalog(write_raw(tmp_path, business={"min_lead_min": 0})).business.min_lead_min == 0


@pytest.mark.parametrize("duration", [0, -30])
def test_load_catalog_rejects_non_positive_duration(tmp_path, duration):
    services = [{"id": 1, "name": "Стрижка", "duration_min": duration, "price": 1000}]
    with pytest.raises(ValueError, match="duration_min must be positive"):
        load_catalog(write_raw(tmp_path, services=services))


def test_load_catalog_rejects_duplicate_ids(tmp_path):
    services = [
        {"id": 1, "name": "Стрижка", "duration_min": 60, "price": 1000},
        {"id": 1, "name": "Укладка", "duration_min": 30, "price": 800},
    ]
    with pytest.raises(ValueError, match="duplicate service ids \\[1\\]"):
        load_catalog(write_raw(tmp_path, services=services))
    with pytest.raises(ValueError, match="duplicate master ids \\[1\\]"):
        load_catalog(write_raw(tmp_path, masters=[master(), master(name="Ирина")]))


def test_names_fall_back_for_ids_missing_from_catalog(tmp_path):
    catalog = load_catalog(write_raw(tmp_path))
    assert catalog.service_name(1) == "Стрижка"
    assert catalog.master_name(1) == "Анна"
    assert catalog.service_name(9) == "услуга №9 (нет в каталоге)"
    assert catalog.master_name(9) == "мастер №9 (нет в каталоге)"
