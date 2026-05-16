"""
Telegram webhook: обработка нажатий на inline-кнопки и команд эксперта.

Раньше кнопки `✉️ Отправить как есть / ✍️ Добавить заметку / 🤐 Не отправлять`
никак не обрабатывались — в кодбейзе вообще не было ни webhook-handler-а,
ни long-polling. Этот модуль закрывает дыру.

Установка webhook у Telegram (выполнить один раз, после деплоя):

    curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
         -d "url=https://catcore.ru/api/v1/telegram/webhook/<SECRET>" \
         -d "allowed_updates=[\"callback_query\",\"message\"]"

где SECRET = sha256(BOT_TOKEN). Готовая команда лежит в DEPLOY.md.

Команды в чате эксперта:
    /send  <8-символьный префикс id>          — отправить отчёт как есть
    /hold  <8-символьный префикс id>          — не отправлять
    /note  <8-символьный префикс id> <текст>  — добавить личную заметку и отправить
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlalchemy import cast, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.report import Report
from app.db.repositories.report_repo import (
    get_report,
    log_event,
    update_report_field,
    update_report_status,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def expected_webhook_secret() -> str:
    """Секрет, который должен быть в URL вебхука. Не подбирается без токена бота."""
    token = (settings.TELEGRAM_BOT_TOKEN or "").encode()
    return hashlib.sha256(token).hexdigest()[:32] if token else ""


async def _tg_api(method: str, payload: dict) -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    try:
        async with httpx.AsyncClient(timeout=10.0, proxy=settings.TELEGRAM_PROXY_URL or None) as client:
            await client.post(url, json=payload)
    except Exception as exc:
        logger.error("tg_api_failed", method=method, error=repr(exc))


async def _answer_callback(callback_id: str, text: str = "", show_alert: bool = False) -> None:
    await _tg_api("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text[:200],
        "show_alert": show_alert,
    })


async def _edit_message_remove_keyboard(chat_id: int | str, message_id: int, suffix: str = "") -> None:
    """После клика — убираем клавиатуру и добавляем строку «✅ обработано: …»."""
    await _tg_api("editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": {"inline_keyboard": []},
    })
    if suffix:
        await _tg_api("sendMessage", {
            "chat_id": chat_id,
            "reply_to_message_id": message_id,
            "text": suffix,
            "disable_web_page_preview": True,
        })


async def _send_text(chat_id: int | str, text: str, reply_to: Optional[int] = None) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    await _tg_api("sendMessage", payload)


async def _find_report_by_prefix(db: AsyncSession, prefix: str) -> Report | None:
    """Находит отчёт по первым 8 символам UUID (как они показаны в сообщении эксперту)."""
    prefix = prefix.strip().lower()
    if not prefix:
        return None
    try:
        # если эксперт ввёл полный UUID
        return await get_report(db, UUID(prefix))
    except (ValueError, AttributeError):
        pass
    # поиск по префиксу UUID — приводим колонку к тексту через CAST
    try:
        stmt = select(Report).where(cast(Report.id, String).ilike(f"{prefix}%"))
        result = await db.execute(stmt)
        row = result.scalars().first()
        if row:
            return row
    except Exception:
        pass

    # fallback: построчно (для тестов на SQLite)
    result = await db.execute(select(Report))
    for row in result.scalars().all():
        if str(row.id).lower().startswith(prefix):
            return row
    return None


# ── Действия эксперта ────────────────────────────────────────────────────────

async def _action_send_as_is(db: AsyncSession, report: Report) -> str:
    from app.email.sender import EmailSender
    from app.integrations.telegram import TelegramNotifier

    sender = EmailSender(settings)
    telegram = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_NOTIFY_CHAT_ID)

    await update_report_status(db, report.id, "sending_email", progress=99)
    await sender.send_report_ready(report)
    await update_report_status(db, report.id, "completed", progress=100)
    await telegram.notify_report_completed(report)
    await log_event(db, report.id, "expert_send_as_is")
    return "✉️ Отчёт отправлен клиенту."


async def _action_hold(db: AsyncSession, report: Report) -> str:
    await update_report_field(db, report.id, status="held_by_expert")
    await log_event(db, report.id, "expert_hold")
    return "🤐 Отчёт удержан, клиенту не отправлен."


async def _action_add_note(db: AsyncSession, report: Report, note: str) -> str:
    from app.email.sender import EmailSender
    from app.integrations.telegram import TelegramNotifier

    note = (note or "").strip()
    if not note:
        return "⚠️ Текст заметки пустой — нечего сохранять."

    sender = EmailSender(settings)
    telegram = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_NOTIFY_CHAT_ID)

    await update_report_field(db, report.id, expert_note=note)
    report.expert_note = note
    await update_report_status(db, report.id, "sending_email", progress=99)
    await sender.send_report_ready(report)
    await update_report_status(db, report.id, "completed", progress=100)
    await telegram.notify_report_completed(report)
    await log_event(db, report.id, "expert_add_note")
    return f"✍️ Заметка сохранена ({len(note)} симв.), отчёт отправлен клиенту."


# ── Обработка апдейтов ──────────────────────────────────────────────────────

async def handle_update(update: dict, db: AsyncSession) -> None:
    """Главная точка входа. Вызывается из роута Telegram webhook."""
    if not isinstance(update, dict):
        return

    # 1) Клик по inline-кнопке
    cb = update.get("callback_query")
    if cb:
        await _handle_callback_query(cb, db)
        return

    # 2) Текстовая команда от эксперта
    msg = update.get("message")
    if msg and isinstance(msg.get("text"), str):
        await _handle_message(msg, db)
        return


async def _handle_callback_query(cb: dict, db: AsyncSession) -> None:
    callback_id = cb.get("id", "")
    data = cb.get("data", "") or ""
    message = cb.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")

    # Ожидаемый формат: "action:<report_id>:<action_name>"
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "action":
        await _answer_callback(callback_id, "Неизвестная команда.")
        return

    _, report_id_str, action = parts
    try:
        report_id = UUID(report_id_str)
    except ValueError:
        await _answer_callback(callback_id, "Битый идентификатор отчёта.")
        return

    report = await get_report(db, report_id)
    if not report:
        await _answer_callback(callback_id, "Отчёт не найден.", show_alert=True)
        return

    if action == "send_as_is":
        suffix = await _action_send_as_is(db, report)
        await _answer_callback(callback_id, "Отправлено")
        if chat_id and message_id:
            await _edit_message_remove_keyboard(chat_id, message_id, suffix)
        return

    if action == "hold":
        suffix = await _action_hold(db, report)
        await _answer_callback(callback_id, "Удержано")
        if chat_id and message_id:
            await _edit_message_remove_keyboard(chat_id, message_id, suffix)
        return

    if action == "add_note":
        # Нельзя получить текст заметки из callback — просим ответить командой.
        prefix = report_id_str[:8]
        instructions = (
            "✍️ Чтобы добавить заметку, ответьте сообщением:\n"
            f"<code>/note {prefix} ваш текст заметки</code>\n\n"
            "Или используйте короткие команды:\n"
            f"<code>/send {prefix}</code> — отправить как есть\n"
            f"<code>/hold {prefix}</code> — не отправлять"
        )
        await _answer_callback(callback_id, "Жду /note <id> <текст>")
        if chat_id and message_id:
            await _tg_api("sendMessage", {
                "chat_id": chat_id,
                "reply_to_message_id": message_id,
                "text": instructions,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
        return

    await _answer_callback(callback_id, f"Неизвестное действие: {action}")


async def _handle_message(msg: dict, db: AsyncSession) -> None:
    chat_id = (msg.get("chat") or {}).get("id")
    reply_to = msg.get("message_id")
    text = (msg.get("text") or "").strip()

    # Принимаем команды только из заранее настроенного chat-id (чат эксперта).
    notify_chat_id = settings.TELEGRAM_NOTIFY_CHAT_ID
    if notify_chat_id and str(chat_id) != str(notify_chat_id):
        return

    if not text.startswith("/"):
        return

    # Разбор: /command<@bot> <prefix> [<text>]
    head, _, rest = text.partition(" ")
    cmd = head.split("@", 1)[0].lower()
    rest = rest.strip()

    if cmd in ("/help", "/start"):
        await _send_text(chat_id, (
            "Команды эксперта:\n"
            "/send <id> — отправить отчёт как есть\n"
            "/hold <id> — не отправлять\n"
            "/note <id> <текст> — добавить личную заметку и отправить\n\n"
            "<id> — первые 8 символов UUID из уведомления."
        ), reply_to=reply_to)
        return

    if cmd not in ("/send", "/hold", "/note"):
        return

    if not rest:
        await _send_text(chat_id, f"Использование: {cmd} <id> …", reply_to=reply_to)
        return

    prefix, _, note_text = rest.partition(" ")
    report = await _find_report_by_prefix(db, prefix)
    if not report:
        await _send_text(chat_id, f"Отчёт с id {prefix} не найден.", reply_to=reply_to)
        return

    if cmd == "/send":
        result = await _action_send_as_is(db, report)
    elif cmd == "/hold":
        result = await _action_hold(db, report)
    else:  # /note
        result = await _action_add_note(db, report, note_text)

    await _send_text(chat_id, result, reply_to=reply_to)
