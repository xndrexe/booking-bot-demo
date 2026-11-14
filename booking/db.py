"""Хранилище на SQLite: клиенты с их шагом диалога и записи.

Время записей хранится как локальное время салона без пояса ("2026-10-15T10:30"):
салон один, а строки так сортируются и сравниваются как даты.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    platform TEXT NOT NULL,
    user_id TEXT NOT NULL,
    name TEXT,
    phone TEXT,
    state TEXT,
    draft TEXT,
    PRIMARY KEY (platform, user_id)
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    user_id TEXT NOT NULL,
    client_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    service_id INTEGER NOT NULL,
    master_id INTEGER NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    reminded INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_appointments_master_start ON appointments (master_id, start);
"""

ACTIVE = "active"
CANCELLED = "cancelled"


@dataclass(frozen=True)
class Client:
    platform: str
    user_id: str
    name: str | None
    phone: str | None
    state: str | None
    draft: dict


@dataclass(frozen=True)
class Appointment:
    id: int
    platform: str
    user_id: str
    client_name: str
    phone: str
    service_id: int
    master_id: int
    start: datetime
    end: datetime
    status: str
    created_at: datetime
    reminded: bool


def _to_appointment(row: sqlite3.Row) -> Appointment:
    return Appointment(
        id=row["id"],
        platform=row["platform"],
        user_id=row["user_id"],
        client_name=row["client_name"],
        phone=row["phone"],
        service_id=row["service_id"],
        master_id=row["master_id"],
        start=datetime.fromisoformat(row["start"]),
        end=datetime.fromisoformat(row["end"]),
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        reminded=bool(row["reminded"]),
    )


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


class Storage:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # --- клиенты ---

    def get_client(self, platform: str, user_id: str) -> Client:
        row = self.conn.execute(
            "SELECT * FROM clients WHERE platform = ? AND user_id = ?", (platform, user_id)
        ).fetchone()
        if row is None:
            return Client(platform, user_id, None, None, None, {})
        return Client(
            platform=platform,
            user_id=user_id,
            name=row["name"],
            phone=row["phone"],
            state=row["state"],
            draft=json.loads(row["draft"] or "{}"),
        )

    def save_client(self, client: Client) -> None:
        self.conn.execute(
            """
            INSERT INTO clients (platform, user_id, name, phone, state, draft)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (platform, user_id) DO UPDATE SET
                name = excluded.name, phone = excluded.phone,
                state = excluded.state, draft = excluded.draft
            """,
            (
                client.platform,
                client.user_id,
                client.name,
                client.phone,
                client.state,
                json.dumps(client.draft, ensure_ascii=False),
            ),
        )

    # --- записи ---

    def book(
        self,
        *,
        platform: str,
        user_id: str,
        client_name: str,
        phone: str,
        service_id: int,
        master_id: int,
        start: datetime,
        end: datetime,
        created_at: datetime,
    ) -> Appointment | None:
        """Создаёт запись, если у мастера это время ещё свободно; иначе None.

        Проверка и вставка идут в одной транзакции BEGIN IMMEDIATE, чтобы два
        клиента не заняли один слот одновременно.
        """
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            clash = self.conn.execute(
                """
                SELECT 1 FROM appointments
                WHERE master_id = ? AND status = ? AND start < ? AND end > ?
                """,
                (master_id, ACTIVE, _iso(end), _iso(start)),
            ).fetchone()
            if clash:
                self.conn.execute("ROLLBACK")
                return None
            cur = self.conn.execute(
                """
                INSERT INTO appointments
                    (platform, user_id, client_name, phone, service_id, master_id,
                     start, end, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    user_id,
                    client_name,
                    phone,
                    service_id,
                    master_id,
                    _iso(start),
                    _iso(end),
                    ACTIVE,
                    _iso(created_at),
                ),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return self.get_appointment(cur.lastrowid)

    def get_appointment(self, appointment_id: int) -> Appointment | None:
        row = self.conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return _to_appointment(row) if row else None

    def cancel(self, appointment_id: int) -> None:
        self.conn.execute("UPDATE appointments SET status = ? WHERE id = ?", (CANCELLED, appointment_id))

    def mark_reminded(self, appointment_id: int) -> None:
        self.conn.execute("UPDATE appointments SET reminded = 1 WHERE id = ?", (appointment_id,))

    def busy_intervals(
        self, master_id: int, day_start: datetime, day_end: datetime
    ) -> list[tuple[datetime, datetime]]:
        rows = self.conn.execute(
            """
            SELECT start, end FROM appointments
            WHERE master_id = ? AND status = ? AND start < ? AND end > ?
            """,
            (master_id, ACTIVE, _iso(day_end), _iso(day_start)),
        ).fetchall()
        return [(datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])) for r in rows]

    def upcoming_for_client(self, platform: str, user_id: str, now: datetime) -> list[Appointment]:
        rows = self.conn.execute(
            """
            SELECT * FROM appointments
            WHERE platform = ? AND user_id = ? AND status = ? AND start > ?
            ORDER BY start
            """,
            (platform, user_id, ACTIVE, _iso(now)),
        ).fetchall()
        return [_to_appointment(r) for r in rows]

    def active_between(self, start: datetime, end: datetime) -> list[Appointment]:
        rows = self.conn.execute(
            "SELECT * FROM appointments WHERE status = ? AND start >= ? AND start < ? ORDER BY start",
            (ACTIVE, _iso(start), _iso(end)),
        ).fetchall()
        return [_to_appointment(r) for r in rows]

    def not_reminded_before(self, now: datetime, until: datetime) -> list[Appointment]:
        rows = self.conn.execute(
            """
            SELECT * FROM appointments
            WHERE status = ? AND reminded = 0 AND start > ? AND start <= ?
            ORDER BY start
            """,
            (ACTIVE, _iso(now), _iso(until)),
        ).fetchall()
        return [_to_appointment(r) for r in rows]

    def all_appointments(self) -> list[Appointment]:
        rows = self.conn.execute("SELECT * FROM appointments ORDER BY start").fetchall()
        return [_to_appointment(r) for r in rows]
