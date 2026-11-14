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

    # старые записи могут ссылаться на услугу или мастера, которых владелец уже убрал из каталога
    def service_name(self, service_id: int) -> str:
        service = self.services.get(service_id)
        return service.name if service else f"услуга №{service_id} (нет в каталоге)"

    def master_name(self, master_id: int) -> str:
        master = self.masters.get(master_id)
        return master.name if master else f"мастер №{master_id} (нет в каталоге)"


def _unique_ids(items: list[dict], kind: str) -> None:
    ids = [item["id"] for item in items]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        # без проверки второй элемент с тем же id молча затирал первый
        raise ValueError(f"duplicate {kind} ids {duplicates}")


def load_catalog(path: Path) -> Catalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    _unique_ids(raw["services"], "service")
    _unique_ids(raw["masters"], "master")
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
    for service in services.values():
        # услуга нулевой длины не пересекается ни с чем — один слот можно было бы занять дважды
        if service.duration_min <= 0:
            raise ValueError(
                f"service {service.id}: duration_min must be positive, got {service.duration_min}"
            )
    for master in masters.values():
        unknown = master.services - services.keys()
        if unknown:
            raise ValueError(f"master {master.id} references unknown services {sorted(unknown)}")
        # ошибку в графике владелец должен увидеть при запуске, а не по пустому списку окон
        if master.start >= master.end:
            raise ValueError(f"master {master.id}: start {master.start} must be before end {master.end}")
        if not master.weekdays or not master.weekdays <= set(range(1, 8)):
            raise ValueError(f"master {master.id}: weekdays must be 1..7, got {sorted(master.weekdays)}")
    business = Business(**raw["business"])
    # при шаге 0 подбор окон в slots.free_starts не завершается
    if business.slot_step_min <= 0:
        raise ValueError(f"slot_step_min must be positive, got {business.slot_step_min}")
    if business.booking_days <= 0:
        raise ValueError(f"booking_days must be positive, got {business.booking_days}")
    if business.min_lead_min < 0:
        raise ValueError(f"min_lead_min must not be negative, got {business.min_lead_min}")
    return Catalog(business=business, services=services, masters=masters)
