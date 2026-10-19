"""Диалог записи — общий для Telegram и MAX.

Ядро ничего не знает о мессенджерах: получает текст или данные нажатой кнопки
и возвращает ответы (текст + кнопки + файл). Адаптеры в booking/tg.py и
booking/maxbot.py только переводят это в вызовы своих библиотек.

Данные кнопок самодостаточны ("t:1:2:202610151030" — услуга, мастер, время),
поэтому старые кнопки в истории чата продолжают работать. В базе хранится
только шаг ввода имени и телефона и черновик выбранного времени до подтверждения.
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from html import escape
from typing import Protocol

from booking import texts
from booking.catalog import Catalog, Master
from booking.db import ACTIVE, Appointment, Client, Storage
from booking.export import build_xlsx, rows
from booking.slots import free_by_time, open_days

log = logging.getLogger(__name__)

ASK_NAME = "ask_name"
ASK_PHONE = "ask_phone"
REMIND_BEFORE = timedelta(hours=24)
# образец номера в подсказках о телефоне; неразрывные пробелы не дают ему переноситься
PHONE_EXAMPLE = "+7\u00a0900\u00a0123-45-67"


@dataclass(frozen=True)
class Button:
    text: str
    data: str


@dataclass
class Reply:
    text: str
    buttons: list[list[Button]] = field(default_factory=list)
    file_name: str | None = None
    file_bytes: bytes | None = None


Sender = Callable[[str, Reply], Awaitable[None]]


class SheetSink(Protocol):
    def push(self, rows: list[list]) -> None: ...


def _grid(buttons: list[Button], per_row: int) -> list[list[Button]]:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def _back(data: str, text: str = "« Назад") -> list[Button]:
    return [Button(text, data)]


def _gone() -> Reply:
    return Reply("Эта запись уже отменена или прошла.", [_back("my")])


class BookingBot:
    def __init__(
        self,
        catalog: Catalog,
        storage: Storage,
        *,
        admins: set[str],
        clock: Callable[[], datetime],
        sheet: SheetSink | None = None,
    ):
        """admins — ключи вида "tg:123456" или "max:987"; clock — локальное время салона;
        sheet — Google Таблица, куда копируются записи (необязательно)."""
        self.catalog = catalog
        self.storage = storage
        self.admins = admins
        self.clock = clock
        self.sheet = sheet
        self.senders: dict[str, Sender] = {}

    def now(self) -> datetime:
        return self.clock().replace(second=0, microsecond=0)

    def is_admin(self, platform: str, user_id: str) -> bool:
        return f"{platform}:{user_id}" in self.admins

    # --- входы из адаптеров ---

    async def handle_text(self, platform: str, user_id: str, text: str) -> list[Reply]:
        client = self.storage.get_client(platform, user_id)
        text = text.strip()
        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else None

        if command == "/start":
            self._save(client, state=None)
            return [self._menu(platform, user_id)]
        if command == "/book":
            return [self._services()]
        if command == "/my":
            return [self._my(platform, user_id)]
        if command in ("/export", "/today"):
            if not self.is_admin(platform, user_id):
                return [self._menu(platform, user_id)]
            return [self._export() if command == "/export" else self._today()]

        if client.state == ASK_NAME:
            return [self._take_name(client, text)]
        if client.state == ASK_PHONE:
            return [self._take_phone(client, text)]
        return [self._menu(platform, user_id, hint=True)]

    async def handle_callback(self, platform: str, user_id: str, data: str) -> list[Reply]:
        client = self.storage.get_client(platform, user_id)
        kind, *args = data.split(":")
        try:
            match kind:
                case "menu":
                    self._save(client, state=None)
                    return [self._menu(platform, user_id)]
                case "book":
                    return [self._services()]
                case "s":
                    return [self._masters(int(args[0]))]
                case "m":
                    return [self._days(int(args[0]), int(args[1]))]
                case "d":
                    day = datetime.strptime(args[2], "%Y%m%d").date()
                    return [self._times(int(args[0]), int(args[1]), day)]
                case "t":
                    start = datetime.strptime(args[2], "%Y%m%d%H%M")
                    return [self._pick_time(client, int(args[0]), int(args[1]), start)]
                case "edit":
                    self._save(client, state=ASK_NAME)
                    return [self._ask_name()]
                case "ok":
                    return await self._confirm(client)
                case "my":
                    return [self._my(platform, user_id)]
                case "c":
                    return [self._ask_cancel(platform, user_id, int(args[0]))]
                case "cy":
                    return await self._cancel(platform, user_id, int(args[0]))
                case "ack":
                    return [Reply("Отлично, ждём вас! 💜")]
                case "info":
                    return [self._info()]
                case "x" if self.is_admin(platform, user_id):
                    return [self._export()]
                case "today" if self.is_admin(platform, user_id):
                    return [self._today()]
        except (IndexError, ValueError, KeyError, OverflowError):
            # OverflowError — подделанный id длиннее, чем влезает в INTEGER SQLite
            # длину кнопки MAX не ограничивает, как Telegram (64 байта) — в лог только начало
            log.warning("bad callback data %r from %s:%s", data[:100], platform, user_id)
        return [self._menu(platform, user_id)]

    # --- экраны записи ---

    def _menu(self, platform: str, user_id: str, hint: bool = False) -> Reply:
        biz = self.catalog.business
        if hint:
            text = "Не понял сообщение. Выберите действие кнопкой 👇"
        else:
            text = (
                f"Здравствуйте! Это бот записи в <b>{escape(biz.name)}</b>.\n\n"
                "Запишу к мастеру за минуту и напомню о визите за сутки."
            )
        buttons = [
            [Button("📝 Записаться", "book")],
            [Button("🗓 Мои записи", "my"), Button("📍 Адрес", "info")],
        ]
        if self.is_admin(platform, user_id):
            buttons.append([Button("📊 Выгрузка в Excel", "x"), Button("📅 Сегодня", "today")])
        return Reply(text, buttons)

    def _services(self) -> Reply:
        buttons = [
            [Button(f"{s.name} · {s.duration_min} мин · {texts.price(s.price)}", f"s:{s.id}")]
            for s in self.catalog.services.values()
        ]
        return Reply("Выберите услугу:", [*buttons, _back("menu")])

    def _masters(self, service_id: int) -> Reply:
        service = self.catalog.services[service_id]
        masters = self.catalog.masters_for(service_id)
        buttons = [[Button(f"{m.name}, {m.title}", f"m:{service_id}:{m.id}")] for m in masters]
        if len(masters) > 1:
            buttons.append([Button("Любой свободный мастер", f"m:{service_id}:0")])
        return Reply(f"<b>{escape(service.name)}</b> — к кому записать?", [*buttons, _back("book")])

    def _candidates(self, service_id: int, master_id: int) -> list[Master]:
        if master_id == 0:
            return self.catalog.masters_for(service_id)
        master = self.catalog.masters[master_id]
        if service_id not in master.services:
            raise ValueError("master does not provide service")
        return [master]

    def _days(self, service_id: int, master_id: int) -> Reply:
        service = self.catalog.services[service_id]
        masters = self._candidates(service_id, master_id)
        days = open_days(self.catalog, self.storage, masters, service, self.now())
        back = _back(f"s:{service_id}")
        if not days:
            horizon = texts.days(self.catalog.business.booking_days)
            return Reply(f"Свободных окон на {horizon} вперёд нет — выберите другого мастера.", [back])
        buttons = [Button(texts.day_button(d), f"d:{service_id}:{master_id}:{d:%Y%m%d}") for d in days]
        return Reply("Выберите день:", [*_grid(buttons, 2), back])

    def _times(self, service_id: int, master_id: int, day: date, note: str = "") -> Reply:
        service = self.catalog.services[service_id]
        masters = self._candidates(service_id, master_id)
        free = free_by_time(self.catalog, self.storage, masters, service, day, self.now())
        back = _back(f"m:{service_id}:{master_id}")
        if not free:
            return Reply(f"{note}На {texts.day_long(day)} свободного времени не осталось.", [back])
        buttons = [
            Button(f"{start:%H:%M}", f"t:{service_id}:{master_id}:{start:%Y%m%d%H%M}") for start in free
        ]
        return Reply(f"{note}<b>{texts.day_long(day)}</b> — свободное время:", [*_grid(buttons, 4), back])

    def _pick_time(self, client: Client, service_id: int, master_id: int, start: datetime) -> Reply:
        service = self.catalog.services[service_id]
        masters = self._candidates(service_id, master_id)
        free = free_by_time(self.catalog, self.storage, masters, service, start.date(), self.now())
        if start not in free:
            return self._times(
                service_id, master_id, start.date(), note="Это время уже заняли, выберите другое.\n\n"
            )
        draft = {
            "service_id": service_id,
            "master_id": free[start].id,
            "chosen_master_id": master_id,
            "start": start.isoformat(timespec="minutes"),
        }
        client = replace(client, draft=draft)
        if client.name and client.phone:
            self._save(client, state=None)
            return self._summary(client)
        self._save(client, state=ASK_NAME)
        return self._ask_name()

    def _ask_name(self) -> Reply:
        return Reply("Как к вам обращаться? Напишите имя.", [_back("menu", "✖️ Отмена")])

    def _take_name(self, client: Client, text: str) -> Reply:
        # невидимые и управляющие символы (смена направления текста, нулевая ширина) подделывают вид
        # уведомления владельцу — выбрасываем их до проверки длины
        name = " ".join("".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf")).split())
        if not 2 <= len(name) <= 40:
            return Reply("Имя должно быть от 2 до 40 символов. Напишите ещё раз.")
        self._save(replace(client, name=name), state=ASK_PHONE)
        return Reply(f"Телефон для связи — например, {PHONE_EXAMPLE}.", [_back("menu", "✖️ Отмена")])

    def _take_phone(self, client: Client, text: str) -> Reply:
        phone = texts.normalize_phone(text)
        if phone is None:
            return Reply(f"Не похоже на номер. Напишите в формате {PHONE_EXAMPLE}.")
        client = replace(client, phone=phone)
        self._save(client, state=None)
        if not client.draft:
            return self._menu(client.platform, client.user_id)
        return self._summary(client)

    def _summary(self, client: Client) -> Reply:
        draft = client.draft
        service = self.catalog.services[draft["service_id"]]
        master = self.catalog.masters[draft["master_id"]]
        start = datetime.fromisoformat(draft["start"])
        text = (
            "Проверьте запись:\n\n"
            f"💇 {escape(service.name)}\n"
            f"👤 Мастер: {escape(master.name)}\n"
            f"🗓 {texts.when(start)}\n"
            f"💳 {texts.price(service.price)}\n\n"
            f"На имя {escape(client.name or '')}, {client.phone}"
        )
        day_back = f"d:{service.id}:{draft['chosen_master_id']}:{start:%Y%m%d}"
        return Reply(
            text,
            [
                [Button("✅ Подтвердить", "ok")],
                [Button("🔁 Другое время", day_back), Button("✏️ Имя и телефон", "edit")],
                _back("menu", "✖️ Отмена"),
            ],
        )

    async def _confirm(self, client: Client) -> list[Reply]:
        draft = client.draft
        if not draft or not client.name or not client.phone:
            return [self._menu(client.platform, client.user_id)]
        service = self.catalog.services[draft["service_id"]]
        start = datetime.fromisoformat(draft["start"])

        def retry(note: str) -> Reply:
            # обратно к времени того же дня и того же выбора мастера («любой» остаётся «любым»)
            return self._times(service.id, draft["chosen_master_id"], start.date(), note=note)

        if start <= self.now():
            self._save(replace(client, draft={}), state=None)
            return [Reply("Это время уже прошло — выберите новое.", [[Button("📝 Записаться", "book")]])]
        # черновик мог пролежать долго: правило «не позже чем за min_lead_min до визита» проверяем снова
        if start < self.now() + timedelta(minutes=self.catalog.business.min_lead_min):
            return [retry("До визита осталось слишком мало времени. Выберите другое.\n\n")]
        appt = self.storage.book(
            platform=client.platform,
            user_id=client.user_id,
            client_name=client.name,
            phone=client.phone,
            service_id=service.id,
            master_id=draft["master_id"],
            start=start,
            end=start + timedelta(minutes=service.duration_min),
            created_at=self.now(),
        )
        if appt is None:
            return [retry("Пока вы подтверждали, это время заняли. Выберите другое.\n\n")]
        self._save(replace(client, draft={}), state=None)
        await self._sync_sheet()
        await self._notify_admins(f"🆕 Новая запись\n\n{self._describe(appt, with_client=True)}")
        biz = self.catalog.business
        return [
            Reply(
                "Готово, вы записаны! ✨\n\n"
                f"{self._describe(appt)}\n"
                f"📍 {escape(biz.address)}\n\n"
                "Напомню за сутки до визита. Отменить запись можно в «Мои записи».",
                [[Button("🗓 Мои записи", "my"), Button("« В меню", "menu")]],
            )
        ]

    # --- мои записи и отмена ---

    def _my(self, platform: str, user_id: str) -> Reply:
        items = self.storage.upcoming_for_client(platform, user_id, self.now())
        if not items:
            return Reply("Активных записей нет.", [[Button("📝 Записаться", "book")], _back("menu")])
        lines = [f"{i}. {self._describe_short(a)}" for i, a in enumerate(items, start=1)]
        buttons = [[Button(f"✖️ Отменить {a.start:%d.%m %H:%M}", f"c:{a.id}")] for a in items]
        return Reply("Ваши записи:\n\n" + "\n".join(lines), [*buttons, _back("menu")])

    def _own_active(self, platform: str, user_id: str, appointment_id: int) -> Appointment | None:
        appt = self.storage.get_appointment(appointment_id)
        if (
            appt is None
            or appt.platform != platform
            or appt.user_id != user_id
            or appt.status != ACTIVE
            or appt.start <= self.now()
        ):
            return None
        return appt

    def _ask_cancel(self, platform: str, user_id: str, appointment_id: int) -> Reply:
        appt = self._own_active(platform, user_id, appointment_id)
        if appt is None:
            return _gone()
        return Reply(
            f"Отменить запись?\n\n{self._describe(appt)}",
            [[Button("Да, отменить", f"cy:{appt.id}"), Button("Нет, оставить", "my")]],
        )

    async def _cancel(self, platform: str, user_id: str, appointment_id: int) -> list[Reply]:
        appt = self._own_active(platform, user_id, appointment_id)
        if appt is None:
            return [_gone()]
        self.storage.cancel(appt.id)
        await self._sync_sheet()
        await self._notify_admins(f"❌ Клиент отменил запись\n\n{self._describe(appt, with_client=True)}")
        return [
            Reply(
                "Запись отменена. Будем рады видеть вас в другой раз!",
                [[Button("📝 Записаться снова", "book"), Button("« В меню", "menu")]],
            )
        ]

    # --- владельцу ---

    def _info(self) -> Reply:
        biz = self.catalog.business
        return Reply(
            f"<b>{escape(biz.name)}</b>\n\n📍 {escape(biz.address)}\n"
            f"📞 {escape(biz.phone)}\n🕙 {escape(biz.hours)}",
            [_back("menu")],
        )

    def _export(self) -> Reply:
        items = self.storage.all_appointments()
        return Reply(
            f"Выгрузка записей: {len(items)} шт.",
            file_name=f"zapisi_{self.now():%Y-%m-%d}.xlsx",
            file_bytes=build_xlsx(self.catalog, items),
        )

    def _today(self) -> Reply:
        day_start = datetime.combine(self.now().date(), datetime.min.time())
        items = self.storage.active_between(day_start, day_start + timedelta(days=1))
        if not items:
            return Reply("На сегодня записей нет.", [_back("menu")])
        lines = []
        for a in items:
            service, master = self._names(a)
            lines.append(f"{a.start:%H:%M} — {service}, {master}; {escape(a.client_name)}, {a.phone}")
        return Reply("Записи на сегодня:\n\n" + "\n".join(lines), [_back("menu")])

    async def _sync_sheet(self) -> None:
        if self.sheet is None:
            return
        data = rows(self.catalog, self.storage.all_appointments())
        try:
            # gspread синхронный — уводим в поток, чтобы бот не замирал на время запроса
            await asyncio.to_thread(self.sheet.push, data)
        except Exception:
            log.warning("google sheet sync failed", exc_info=True)

    async def _notify_admins(self, text: str) -> None:
        for key in sorted(self.admins):
            platform, _, user_id = key.partition(":")
            sender = self.senders.get(platform)
            if sender is None:
                continue
            try:
                await sender(user_id, Reply(text))
            except Exception:
                log.warning("admin notify failed for %s", key, exc_info=True)

    # --- напоминания ---

    async def send_due_reminders(self) -> int:
        """Шлёт напоминания о визитах в ближайшие сутки. Возвращает число отправленных.

        Если клиент записался меньше чем за сутки, напоминание не шлём: он только
        что получил подтверждение.
        """
        now = self.now()
        sent = 0
        for appt in self.storage.not_reminded_before(now, now + REMIND_BEFORE):
            self.storage.mark_reminded(appt.id)
            if appt.created_at > appt.start - REMIND_BEFORE:
                continue
            sender = self.senders.get(appt.platform)
            if sender is None:
                continue
            reply = Reply(
                f"Напоминаю о записи {texts.relative_day(appt.start, now)} в {appt.start:%H:%M} 💜\n\n"
                f"{self._describe(appt)}\n📍 {escape(self.catalog.business.address)}\n\n"
                "Планы поменялись — отмените запись, чтобы время досталось другому.",
                [[Button("👍 Приду", f"ack:{appt.id}"), Button("✖️ Отменить", f"c:{appt.id}")]],
            )
            try:
                await sender(appt.user_id, reply)
                sent += 1
            except Exception:
                # клиент мог заблокировать бота — повторять каждую минуту незачем
                log.warning("reminder %s not delivered", appt.id, exc_info=True)
        return sent

    # --- служебное ---

    def _names(self, appt: Appointment) -> tuple[str, str]:
        """Названия услуги и мастера записи, уже экранированные для HTML."""
        catalog = self.catalog
        return escape(catalog.service_name(appt.service_id)), escape(catalog.master_name(appt.master_id))

    def _describe(self, appt: Appointment, with_client: bool = False) -> str:
        service, master = self._names(appt)
        text = f"💇 {service}\n👤 Мастер: {master}\n🗓 {texts.when(appt.start)}"
        if with_client:
            text += f"\n🙋 {escape(appt.client_name)}, {appt.phone}"
        return text

    def _describe_short(self, appt: Appointment) -> str:
        service, master = self._names(appt)
        return f"{texts.when(appt.start)} — {service}, {master}"

    def _save(self, client: Client, *, state: str | None) -> None:
        self.storage.save_client(replace(client, state=state))
