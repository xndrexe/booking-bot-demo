"""Настройки из переменных окружения (.env рядом с проектом)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    tg_token: str | None
    max_token: str | None
    admins: set[str]
    db_path: Path
    catalog_path: Path


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    admins = {a.strip() for a in os.getenv("ADMINS", "").split(",") if a.strip()}
    return Settings(
        tg_token=os.getenv("TG_BOT_TOKEN") or None,
        max_token=os.getenv("MAX_BOT_TOKEN") or None,
        admins=admins,
        db_path=Path(os.getenv("DB_PATH", ROOT / "data" / "booking.db")),
        catalog_path=Path(os.getenv("CATALOG_PATH", ROOT / "data" / "catalog.json")),
    )
