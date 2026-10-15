"""Диалог: команды, ввод имени, правка контактов, граничные случаи времени и напоминаний."""

from datetime import date, datetime

from test_flow import CLIENT, book_haircut, datas, press, say

from booking.slots import free_starts, open_days

OWNER = ("tg", "1")


async def test_commands(bot):
    assert "s:1" in datas(await say(bot, "/book"))
    assert "Активных записей нет" in (await say(bot, "/my")).text
    assert "Лаванда" in (await say(bot, "  /START@lavanda_bot  ")).text
    # клиенту команды владельца недоступны — просто меню
    assert (await say(bot, "/export")).file_bytes is None
    assert "Не понял сообщение" in (await say(bot, "привет")).text


async def test_name_validation_and_whitespace(bot, storage):
    await press(bot, "t:1:1:202610151200")
    assert "от 2 до 40" in (await say(bot, "Я")).text
    assert "от 2 до 40" in (await say(bot, "Я" * 41)).text
    assert "Телефон" in (await say(bot, "  Мария   Ивановна ")).text
    assert storage.get_client(*CLIENT).name == "Мария Ивановна"


async def test_start_resets_name_input(bot):
    await press(bot, "t:1:1:202610151200")
    await say(bot, "/start")
    assert "Не понял сообщение" in (await say(bot, "Мария")).text


async def test_edit_contacts_keeps_draft(bot, storage):
    await book_haircut(bot)
    assert "Как к вам обращаться" in (await press(bot, "edit")).text
    await say(bot, "Ирина")
    summary = await say(bot, "+7 900 222-33-44")
    assert "Ирина, +7 900 222-33-44" in summary.text
    assert "d:1:1:20261015" in datas(summary)  # «Другое время» ведёт на тот же день
    await press(bot, "ok")
    (appt,) = storage.all_appointments()
    assert (appt.client_name, appt.phone) == ("Ирина", "+7 900 222-33-44")


async def test_edit_without_draft_returns_menu(bot):
    await press(bot, "edit")
    await say(bot, "Ирина")
    reply = await say(bot, "+7 900 222-33-44")
    assert "book" in datas(reply)


async def test_ok_twice_books_once(bot, storage):
    await book_haircut(bot)
    await press(bot, "ok")
    again = await press(bot, "ok")
    assert "book" in datas(again)
    assert len(storage.all_appointments()) == 1


async def test_confirm_after_time_passed(bot, clock, storage):
    await book_haircut(bot, start="202610141200")
    clock.now = datetime(2026, 10, 14, 12, 0)
    reply = await press(bot, "ok")
    assert "уже прошло" in reply.text
    assert storage.all_appointments() == []
    assert storage.get_client(*CLIENT).draft == {}


async def test_confirm_too_close_to_visit(bot, clock, storage):
    """Черновик выбран заранее, а подтверждён меньше чем за час до визита."""
    await book_haircut(bot, start="202610141000")
    clock.now = datetime(2026, 10, 14, 9, 30)
    reply = await press(bot, "ok")
    assert "слишком мало времени" in reply.text
    assert "t:1:1:202610141000" not in datas(reply)
    assert storage.all_appointments() == []


async def test_booking_beyond_horizon_rejected(bot, storage):
    """Самодельная кнопка с датой через два месяца не даёт записаться."""
    reply = await press(bot, "t:1:1:202612141200")
    assert "заняли" in reply.text
    assert "свободного времени не осталось" in reply.text
    assert storage.get_client(*CLIENT).draft == {}
    assert "свободного времени не осталось" in (await press(bot, "d:1:1:20261214")).text


def test_horizon_bounds(catalog, storage):
    anna, haircut = catalog.masters[1], catalog.services[1]
    now = datetime(2026, 10, 14, 8)
    last = date(2026, 10, 27)  # 14-й день, считая сегодняшний (вторник)
    assert free_starts(catalog, storage, anna, haircut, last, now)
    assert free_starts(catalog, storage, anna, haircut, date(2026, 10, 28), now) == []
    assert free_starts(catalog, storage, anna, haircut, date(2026, 10, 13), now) == []  # вчера
    assert open_days(catalog, storage, [anna], haircut, now, limit=100)[-1] == last


def test_open_days_limit(catalog, storage):
    days = open_days(catalog, storage, catalog.masters_for(1), catalog.services[1], datetime(2026, 10, 14, 8))
    assert len(days) == 8
    assert days == sorted(days)


async def test_single_master_has_no_any_button(bot):
    reply = await press(bot, "s:4")
    assert datas(reply) == ["m:4:4", "book"]


async def test_late_evening_today_has_no_slots(bot, clock):
    clock.now = datetime(2026, 10, 14, 18, 30)  # Анне до конца дня меньше часа + услуги
    reply = await press(bot, "d:1:1:20261014")
    assert "свободного времени не осталось" in reply.text
    days = await press(bot, "m:1:1")
    assert "d:1:1:20261014" not in datas(days)


async def test_foreign_and_past_appointments_not_cancellable(bot, clock, storage):
    await book_haircut(bot)
    await press(bot, "ok")
    (appt,) = storage.all_appointments()
    assert "уже отменена" in (await press(bot, f"c:{appt.id}", ("tg", "7"))).text
    assert "уже отменена" in (await press(bot, "c:999")).text
    clock.now = datetime(2026, 10, 15, 12, 0)
    assert "уже отменена" in (await press(bot, f"cy:{appt.id}")).text
    assert storage.get_appointment(appt.id).status == "active"


async def test_info_and_ack(bot):
    info = await press(bot, "info")
    assert "Садовая" in info.text and "&lt;" not in info.text
    assert "ждём вас" in (await press(bot, "ack:1")).text


async def test_today_for_owner(bot):
    await book_haircut(bot, start="202610141200")
    await press(bot, "ok")
    reply = await press(bot, "today", OWNER)
    assert "12:00 — Женская стрижка, Анна; Мария, +7 900 111-22-33" in reply.text
    assert "today" not in datas(await press(bot, "today"))  # клиенту — меню без кнопок владельца


async def test_admin_notify_failure_does_not_break_booking(bot, storage):
    async def broken(user_id, reply):
        raise ConnectionError("telegram down")

    bot.senders["tg"] = broken
    bot.admins |= {"vk:5", "max:9"}  # для vk отправщика нет — пропускаем
    await book_haircut(bot)
    assert "записаны" in (await press(bot, "ok")).text
    assert len(storage.all_appointments()) == 1


async def test_reminder_skips_cancelled_and_undeliverable(bot, clock, storage, outbox):
    await press(bot, "t:1:2:202610171200")
    await say(bot, "Мария")
    await say(bot, "+79001112233")
    await press(bot, "ok")
    other = ("tg", "7")
    await press(bot, "t:1:2:202610171400", other)
    await say(bot, "Ирина", other)
    await say(bot, "+79002223344", other)
    await press(bot, "ok", other)
    first, second = storage.all_appointments()
    storage.cancel(first.id)

    async def blocked(user_id, reply):
        raise RuntimeError("bot blocked by user")

    bot.senders["tg"] = blocked
    clock.now = datetime(2026, 10, 16, 14, 0)
    assert await bot.send_due_reminders() == 0
    # недоставленное напоминание помечено — не будем слать каждую минуту
    assert storage.get_appointment(second.id).reminded is True
    assert storage.get_appointment(first.id).reminded is False


async def test_reminder_text_today(bot, clock, outbox):
    await press(bot, "t:1:2:202610171900")
    await say(bot, "Мария")
    await say(bot, "+79001112233")
    await press(bot, "ok")
    outbox.sent.clear()
    clock.now = datetime(2026, 10, 17, 8, 0)
    assert await bot.send_due_reminders() == 1
    (_, _, reply) = outbox.sent[0]
    assert "сегодня в 19:00" in reply.text
    assert datas(reply)[1].startswith("c:")


async def test_clock_seconds_are_dropped(bot, clock):
    clock.now = datetime(2026, 10, 14, 8, 0, 59, 123)
    assert bot.now() == datetime(2026, 10, 14, 8, 0)
