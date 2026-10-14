"""Каталог: салон, услуги, мастера и их график. Всё берётся из data/catalog.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import time
from pathlib import Path


@dataclass(frozen=True)
class Business:
    name: str
    address: str
    phone: str
    hours: str
    timezone: str
    slot_step_min: int
    booking_days: int
    min_lead_min: int


@dataclass(frozen=True)
class Service:
    id: int
    name: str
    duration_min: int
    price: int


@dataclass(frozen=True)
class Master:
    id: int
    name: str
    title: str
    services: frozenset[int]
    weekdays: frozenset[int]  # ISO: 1 — понедельник, 7 — воскресенье
    start: time
    end: time


@dataclass(frozen=True)
class Catalog:
    business: Business
    services: dict[int, Service]
    masters: dict[int, Master]

    def masters_for(self, service_id: int) -> list[Master]:
        return [m for m in self.masters.values() if service_id in m.services]


def load_catalog(path: Path) -> Catalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    services = {s["id"]: Service(**s) for s in raw["services"]}
    masters = {
        m["id"]: Master(
            id=m["id"],
            name=m["name"],
            title=m["title"],
            services=frozenset(m["services"]),
            weekdays=frozenset(m["weekdays"]),
            start=time.fromisoformat(m["start"]),
            end=time.fromisoformat(m["end"]),
        )
        for m in raw["masters"]
    }
    for master in masters.values():
        unknown = master.services - services.keys()
        if unknown:
            raise ValueError(f"master {master.id} references unknown services {sorted(unknown)}")
    return Catalog(business=Business(**raw["business"]), services=services, masters=masters)
