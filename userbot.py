# This file is part of Golden Userbot.
# Licensed under the GNU General Public License v3.0.
#
# You may redistribute and/or modify this file under the terms of the
# GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
#
# This file is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the LICENSE file for the full license text.

import os
import re
import asyncio
import logging
import secrets
import ast
import math
from collections import deque
from typing import Optional

from aiohttp import web
from telethon import TelegramClient, events, Button, errors
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntityBlockquote, MessageEntityBold
from telethon.extensions import html as telethon_html

import bot as helper_bot

VERSION = "26.3.3"
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION = os.environ["STRING_SESSION"]
PORT = int(os.environ.get("PORT", "10000"))
THX_BOT = os.environ.get("THX_BOT", "@mineevo")
HELPER_SECRET = os.environ["HELPER_SECRET"]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("golden_userbot")


class LogSecurityExtension(logging.Filter):
    def __init__(self):
        super().__init__()
        self._token_rx = re.compile(r'\d{8,12}:[A-Za-z0-9_-]{35}')
        self._session_rx = re.compile(r'\b[14B][A-Za-z0-9_-]{100,}\b')
        self._hash_rx = re.compile(r'\b[a-fA-F0-9]{32}\b')
        self._id_rx = re.compile(r'\b\d{5,9}\b')
        self._url_rx = re.compile(r'https?://[^\s<>"]+|t\.me/[^\s<>"]+')
        

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            msg = self._token_rx.sub("[TELEGRAM_TOKEN_HIDDEN]", msg)
            msg = self._session_rx.sub("[STRING_SESSION_HIDDEN]", msg)
            msg = self._hash_rx.sub("[API_HASH_HIDDEN]", msg)
            
            if any(k in msg.lower() for k in ["api_id", "auth", "login", "connect"]):
                msg = self._id_rx.sub("[API_ID_HIDDEN]", msg)
                
            if any(k in msg.lower() for k in ["secret", "webhook", "helper"]):
                msg = self._url_rx.sub("[WEBHOOK_URL_HIDDEN]", msg)
                for word in msg.split():
                    if len(word) >= 16 and any(c.isdigit() for c in word) and any(c.isalpha() for c in word):
                        msg = msg.replace(word, "[SECRET_DATA_HIDDEN]")
            elif any(k in msg.lower() for k in ["bot", "token", "api", "url"]):
                msg = self._url_rx.sub("[URL_MASKED]", msg)
                
            record.msg = msg
        return True

security_extension = LogSecurityExtension()
logger.addFilter(security_extension)

client = None
CONFIG_FILE = "userbot_config.txt"
config = {
    "mine_work_chat": None,
    "thx_source_chat": None,
    "thx_enabled": False,
    "tc_template_chat": None,
    "tc_template_message": None,
    "lm_work_chat": None,
    "promo_seen": "EVO,437,EVO2,DEV2",
}


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if "=" not in line:
                    continue
                k, v = line.rstrip("\n").split("=", 1)
                if k not in config:
                    continue
                if v == "None":
                    config[k] = None
                elif k == "thx_enabled":
                    config[k] = v.lower() == "true"
                elif k in ("mine_work_chat", "thx_source_chat",
                           "tc_template_chat", "tc_template_message"):
                    config[k] = int(v) if v.lstrip("-").isdigit() else v
                else:
                    config[k] = v
    except Exception:
        logger.exception("Не удалось загрузить конфигурацию")


def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            for k, v in config.items():
                f.write(f"{k}={v}\n")
    except Exception:
        logger.exception("Не удалось сохранить конфигурацию")


load_config()

STATUS_MESSAGE_LIFETIME = 180
active_tasks = {}
promo_task = None
thx_last_event_id = None
lm_task = None
lm_state = None
lm_queue = deque()
lm_paused_queue = deque()
lm_paused = False
lm_last_send_at = None

mine_callback_links = {}
mine_callback_locks = {}
inline_reply_links = {}
helper_inline_ids = {}

bo_task = None
bo_stop_event = None


async def schedule_delete(chat_id, message_id, delay=STATUS_MESSAGE_LIFETIME):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception as exc:
        logger.warning("Не удалось удалить сообщение %s: %s", message_id, exc)


def autodelete(msg, delay=STATUS_MESSAGE_LIFETIME):
    if msg is not None:
        asyncio.create_task(schedule_delete(msg.chat_id, msg.id, delay))


async def answer_and_delete(event, text, delay=STATUS_MESSAGE_LIFETIME):
    # Historical function name is kept for compatibility, but the command
    # message is edited rather than deleted.
    msg = await event.edit(text)
    autodelete(msg, delay)
    return msg


async def home(request):
    return web.Response(text="Golden Userbot is running")


def parse_urlbtn(raw):
    lines = (raw or "").splitlines()
    if not lines:
        return None, []
    message_text = lines[0].strip()
    buttons = []
    for line in lines[1:]:
        line = line.strip()
        if not line or " - " not in line:
            continue
        label, url = line.split(" - ", 1)
        label, url = label.strip(), url.strip()
        if label and re.match(r"^https?://\S+$", url):
            buttons.append((label, url))
    return message_text, buttons


def build_url_buttons(buttons):
    return [[Button.url(label, url)] for label, url in buttons]


async def repeat_message_to_chat(chat_id, source_message, text_override=None,
                                 entities=None, url_buttons=None):
    text = text_override if text_override is not None else source_message.raw_text
    if url_buttons:
        return await client.send_message(
            chat_id, text, formatting_entities=entities,
            buttons=build_url_buttons(url_buttons)
        )
    if source_message is not None and source_message.media is not None:
        return await client.send_file(
            chat_id, source_message.media, caption=text,
            formatting_entities=entities
        )
    return await client.send_message(
        chat_id, text, formatting_entities=entities
    )


def _button_payload(button, callback_id=None):
    url = getattr(button, "url", None)
    if url:
        return {"type": "url", "text": button.text, "url": url}
    data = getattr(button, "data", None)
    if data is not None and callback_id:
        return {"type": "callback", "text": button.text, "id": callback_id}
    return None


def _message_to_helper_data(response, destination_chat):
    rows = []
    callback_links = {}
    if response.buttons:
        for row_index, row in enumerate(response.buttons):
            out_row = []
            for col_index, button in enumerate(row):
                callback_id = None
                if getattr(button, "data", None) is not None:
                    callback_id = secrets.token_urlsafe(12)
                    callback_links[callback_id] = {
                        "source_chat": response.chat_id,
                        "source_message_id": response.id,
                        "row": row_index,
                        "col": col_index,
                        "destination_chat": destination_chat,
                    }
                item = _button_payload(button, callback_id)
                if item:
                    out_row.append(item)
            if out_row:
                rows.append(out_row)
    try:
        formatted_text = telethon_html.unparse(
            response.raw_text or "", response.entities or []
        )
    except Exception:
        logger.exception("Не удалось преобразовать entities MineEVO в HTML")
        formatted_text = response.raw_text or ""
    return {"text": formatted_text, "buttons": rows}, callback_links


async def helper_request(path, payload):
    # Userbot and Helper are now in one process. No public HTTP hop is used.
    if path == "/helper/prepare":
        return await helper_bot.prepare_helper(payload)
    if path == "/helper/update":
        return await helper_bot.update_helper(payload)
    raise RuntimeError(f"Неизвестный внутренний Helper endpoint: {path}")


async def publish_through_helper(data, destination_chat, reply_to=None,
                                 source_link=None):
    result = await helper_request("/helper/prepare", data)
    token = result.get("token")
    bot_username = result.get("bot_username")
    if not token or not bot_username:
        raise RuntimeError("Helper не вернул token/bot_username")

    inline_results = await client.inline_query(bot_username, token)
    if not inline_results:
        raise RuntimeError("Helper не вернул Inline Result")

    sent = await inline_results[0].click(destination_chat, reply_to=reply_to)
    if source_link:
        link = {**source_link, "helper_token": token}
        for callback_id, callback_link in source_link.get(
            "callback_links", {}
        ).items():
            mine_callback_links[callback_id] = {
                **callback_link, "helper_token": token
            }
        inline_reply_links[(sent.chat_id, sent.id)] = link
    return sent, token


async def update_helper_inline_message(response, link, inline_message_id):
    data, callback_links = _message_to_helper_data(
        response, link["destination_chat"]
    )
    token = link.get("helper_token")
    if not token:
        raise RuntimeError("У callback отсутствует helper_token")
    if not inline_message_id:
        raise RuntimeError("Telegram не передал inline_message_id")

    await helper_request("/helper/update", {
        "token": token,
        "text": data["text"],
        "buttons": data["buttons"],
        "inline_message_id": inline_message_id,
    })
    for callback_id, new_link in callback_links.items():
        mine_callback_links[callback_id] = {
            **new_link, "helper_token": token
        }


async def refresh_mineevo_callback(callback_id, inline_message_id=None):
    link = mine_callback_links.get(callback_id)
    if not link:
        raise RuntimeError("Неизвестная callback-кнопка")
    if not inline_message_id:
        raise RuntimeError("Не удалось получить inline_message_id")

    source_key = (link["source_chat"], link["source_message_id"])
    lock = mine_callback_locks.setdefault(source_key, asyncio.Lock())
    async with lock:
        source = await client.get_messages(
            link["source_chat"], ids=link["source_message_id"]
        )
        if not source:
            raise RuntimeError("Исходное сообщение MineEVO не найдено")

        before_text = source.raw_text or ""
        before_buttons = repr(source.buttons)
        await source.click(link["row"], link["col"])

        updated = None
        for _ in range(20):
            await asyncio.sleep(0.1)
            candidate = await client.get_messages(
                link["source_chat"], ids=link["source_message_id"]
            )
            if not candidate:
                continue
            updated = candidate
            if ((candidate.raw_text or "") != before_text or
                    repr(candidate.buttons) != before_buttons):
                break

        if not updated:
            raise RuntimeError(
                "MineEVO не обновил сообщение после нажатия кнопки"
            )
        await update_helper_inline_message(
            updated, link, inline_message_id
        )


async def handle_helper_event(kind, payload):
    if kind == "inline-chosen":
        token = payload.get("token")
        inline_message_id = payload.get("inline_message_id")
        if token and inline_message_id:
            helper_inline_ids[token] = inline_message_id
        return

    if kind == "callback":
        callback_id = payload.get("callback_id")
        inline_message_id = payload.get("inline_message_id")
        if not callback_id or not inline_message_id:
            raise ValueError("missing callback data")
        asyncio.create_task(
            refresh_mineevo_callback(callback_id, inline_message_id)
        )


async def helper_callback(request):
    if request.headers.get("X-Helper-Secret") != HELPER_SECRET:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        payload = await request.json()
        await handle_helper_event("callback", payload)
        return web.json_response({"ok": True})
    except Exception:
        logger.exception("Ошибка helper callback")
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)


async def helper_inline_chosen(request):
    if request.headers.get("X-Helper-Secret") != HELPER_SECRET:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        payload = await request.json()
        await handle_helper_event("inline-chosen", payload)
        return web.json_response({"ok": True})
    except Exception:
        logger.exception("Ошибка helper inline-chosen")
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)


async def ask_mineevo(text, timeout=5.0):
    if not text:
        return None
    work_chat = config["mine_work_chat"]
    if work_chat is None:
        raise RuntimeError(".work не настроен")
    sent = await client.send_message(work_chat, text)
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.1)
        messages = await client.get_messages(work_chat, limit=12)
        for msg in messages:
            if msg.id <= sent.id or msg.out:
                continue
            try:
                sender = await msg.get_sender()
                if sender is not None and getattr(sender, "bot", False):
                    return msg
            except Exception:
                pass
            return msg
    raise TimeoutError(f"MineEVO не ответил в течение {timeout:g} секунд")


def parse_promo_codes(text):
    """Надёжно достаёт промокоды из блока MineEVO."""
    if not text:
        return set()

    lines = text.splitlines()
    header_index = next(
        (i for i, line in enumerate(lines)
         if "🎁" in line and "Действующие промокоды" in line),
        None,
    )
    if header_index is None:
        return set()

    codes = set()
    for raw_line in lines[header_index + 1:]:
        line = raw_line.strip()
        if not line:
            if codes:
                break
            continue

        # Убираем типичное оформление списка: -, •, нумерацию и backticks.
        cleaned = re.sub(r"^[-•*]\s*", "", line)
        cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned)
        cleaned = cleaned.strip("` ")

        # Берём только отдельный токен промокода, чтобы не захватывать
        # посторонний текст из ответа MineEVO.
        match = re.fullmatch(r"([A-Za-z0-9_-]+)", cleaned)
        if match:
            codes.add(match.group(1))
            continue

        # Если MineEVO добавил emoji/оформление вокруг кода, ищем токен
        # после маркера списка, но только если в строке ровно один такой токен.
        tokens = re.findall(r"[A-Za-z0-9_-]+", cleaned)
        if len(tokens) == 1:
            codes.add(tokens[0])
        elif codes:
            break

    return codes


def promo_is_activated(text, code):
    """Успех, если в ответе MineEVO найден точный текст активации кода."""
    if not text:
        return False
    return f"🎉 Промокод {code} активирован!" in text


async def promo_activate_code(code, attempts=3):
    """Пробует активировать код несколько раз; успех фиксируется только по ответу MineEVO."""
    for attempt in range(1, attempts + 1):
        try:
            response = await ask_mineevo(f"промо {code}", timeout=6.0)
            promo_text = (response.text or "").strip() if response else ""
            if promo_is_activated(promo_text, code):
                return True, promo_text
            logger.info(
                "[PROMO] код %r: попытка %d/%d не подтверждена: %r",
                code, attempt, attempts, promo_text,
            )
        except Exception as exc:
            logger.warning(
                "[PROMO] код %r: ошибка попытки %d/%d: %s",
                code, attempt, attempts, exc,
            )
        if attempt < attempts:
            await asyncio.sleep(1)
    return False, ""


async def promo_loop():
    while True:
        try:
            if bo_task and not bo_task.done():
                await asyncio.sleep(60)
                continue

            if config["mine_work_chat"] is not None:
                response = await ask_mineevo("промо", timeout=6.0)
                if response:
                    response_text = response.text or ""
                    codes = parse_promo_codes(response_text)
                    seen = {
                        x.strip() for x in
                        config.get("promo_seen", "").split(",") if x.strip()
                    }

                    logger.info(
                        "[PROMO] найдено кодов: %s; promo_seen: %s",
                        sorted(codes), sorted(seen),
                    )

                    # Никаких отдельных исключений для EVO/437/EVO2/DEV2:
                    # единственное условие — код отсутствует в promo_seen.
                    for code in sorted(codes - seen):
                        ok, promo_text = await promo_activate_code(code)
                        if ok:
                            seen.add(code)
                            config["promo_seen"] = ",".join(sorted(seen))
                            save_config()
                            logger.info(
                                "[PROMO] код %r успешно активирован и добавлен в promo_seen",
                                code,
                            )
                        else:
                            logger.info(
                                "[PROMO] код %r не подтверждён; оставлен вне promo_seen для следующей проверки",
                                code,
                            )

            # Проверяем чаще, чтобы новый код не ждал до часа.
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка автоматической проверки промокодов")
            await asyncio.sleep(60)


THX_TRIGGER = "активировал(а) бустер!"


async def send_thx():
    try:
        await client.send_message(THX_BOT, "Thx")
        logger.info("Отправлен Thx в личку с %s", THX_BOT)
    except Exception:
        logger.exception("Не удалось отправить Thx")


LM_PROBE_SUM = os.environ.get("LM_PROBE_SUM", "3N")
LM_INTERVAL_SECONDS = 60


def parse_max_transfer(text):
    if not text:
        return None
    patterns = [
        r"максимум[^0-9]*([0-9][0-9.,]*(?:[A-Za-zА-Яа-я]+)?)",
        r"максимально[^0-9]*([0-9][0-9.,]*(?:[A-Za-zА-Яа-я]+)?)",
        r"можно[^0-9]*перевести[^0-9]*([0-9][0-9.,]*(?:[A-Za-zА-Яа-я]+)?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).replace(",", ".")
    return None


def format_duration_seconds(total_seconds):
    total_seconds = max(0, int(total_seconds))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} дн.")
    if hours:
        parts.append(f"{hours} ч.")
    if minutes:
        parts.append(f"{minutes} мин.")
    if seconds or not parts:
        parts.append(f"{seconds} сек.")
    return " ".join(parts)


def lm_remaining_time(count_remaining):
    return format_duration_seconds(
        count_remaining * LM_INTERVAL_SECONDS
    )


def lm_status_text(state, eta_seconds=None):
    if eta_seconds is None:
        eta_seconds = lm_remaining_time(state['remaining'])
    elif isinstance(eta_seconds, (int, float)):
        eta_seconds = format_duration_seconds(eta_seconds)
    return (
        f"💵 <b>Перевод игроку:</b> <code>{state['nick']}</code>\n"
        f"📦 <b>Осталось переводов:</b> <code>{state['remaining']}</code>/<code>{state['total']}</code>\n"
        f"⏱ <b>Ожидаемое время до завершения:</b> <code>{eta_seconds}</code>."
    )


def lm_job_sent_count(job):
    return max(0, int(job.get('total', 0)) - int(job.get('remaining', 0)))


def lm_find_job(nick):
    """Find active/queued job by nickname, case-insensitively."""
    wanted = nick.casefold()
    if lm_state and lm_state.get('nick', '').casefold() == wanted:
        return lm_state, 0
    for idx, job in enumerate(lm_queue, start=1):
        if job.get('nick', '').casefold() == wanted:
            return job, idx
    return None, None


def lm_jobs_ahead(target):
    """Number of actual transfers that must happen before target's first transfer."""
    ahead = 0
    if lm_state is target:
        return 0
    if lm_state:
        ahead += max(0, int(lm_state.get('remaining', 0)))
    for job in lm_queue:
        if job is target:
            break
        ahead += max(0, int(job.get('remaining', 0)))
    return ahead


def lm_eta_seconds(target):
    """ETA until a target job is fully finished, including all jobs before it."""
    loop = asyncio.get_running_loop()
    remaining_wait = 0
    if lm_last_send_at is not None:
        remaining_wait = max(0, lm_last_send_at + LM_INTERVAL_SECONDS - loop.time())

    ahead = lm_jobs_ahead(target)
    target_remaining = max(0, int(target.get('remaining', 0)))

    # If target is active, its first remaining transfer is the next transfer.
    # If target is queued, every transfer ahead consumes one 60-second slot.
    # The cooldown applies before the next slot, not after the final transfer.
    if ahead == 0:
        return int(remaining_wait + max(0, target_remaining - 1) * LM_INTERVAL_SECONDS + 0.999)
    return int(remaining_wait + ahead * LM_INTERVAL_SECONDS + max(0, target_remaining - 1) * LM_INTERVAL_SECONDS + 0.999)


def lm_queue_position(target):
    if lm_state is target:
        return 0
    for idx, job in enumerate(lm_queue, start=1):
        if job is target:
            return idx
    return None


async def lm_wait_global_slot():
    """Wait for the single global 60-second transfer slot."""
    loop = asyncio.get_running_loop()
    while True:
        while lm_paused:
            await asyncio.sleep(0.1)
        if lm_last_send_at is None:
            return
        wait = (lm_last_send_at + LM_INTERVAL_SECONDS) - loop.time()
        if wait <= 0:
            return
        await asyncio.sleep(wait)


async def lm_transfer_one(job):
    """Resolve the transfer amount and send one queued player's limits."""
    global lm_state, lm_last_send_at

    work_chat = job["work_chat"]

    try:
        async with client.conversation(work_chat, timeout=60) as conv:
            await conv.send_message(f"Перевести {job['nick']} {LM_PROBE_SUM}")
            response = await conv.get_response()
    except Exception:
        logger.exception("Не удалось получить максимум для LM")
        job["error"] = True
        return False

    amount = parse_max_transfer(response.raw_text or "")
    if not amount:
        logger.error("Не удалось определить максимальную сумму перевода для %s", job["nick"])
        job["error"] = True
        return False

    job["amount"] = amount
    if job.get("remaining") is None:
        job["remaining"] = job["total"]

    while job["remaining"] > 0:
        await lm_wait_global_slot()
        if job["remaining"] <= 0:
            break

        lm_state = job
        send_started_at = asyncio.get_running_loop().time()
        try:
            await client.send_message(
                work_chat,
                f"Перевести {job['nick']} {amount}"
            )
        except Exception:
            logger.exception("Ошибка перевода лимитов игроку %s", job["nick"])
            job["error"] = True
            return False

        # The timestamp is intentionally preserved even if .lmstop is used.
        # A new job started immediately afterwards must still wait the full
        # remaining part of the global 60-second interval.
        lm_last_send_at = send_started_at
        job["remaining"] -= 1

    return True


async def lm_transfer_loop():
    global lm_task, lm_state

    while lm_queue:
        job = lm_queue.popleft()
        if job.get("paused"):
            continue
        lm_state = job
        ok = await lm_transfer_one(job)

        if ok:
            try:
                await client.send_message(
                    job["destination_chat"],
                    f"✅ <b>Все лимиты</b> игроку "
                    f"<code>{job['nick']}</code> "
                    f"<b>переведены</b>: <code>{job['total']}</code>"
                )
            except Exception:
                logger.exception("Не удалось отправить сообщение о завершении LM")
        else:
            try:
                await client.send_message(
                    job["destination_chat"],
                    f"⚠️ <b>Перевод лимитов</b> игроку "
                    f"<code>{job['nick']}</code> "
                    f"не удалось выполнить. Задача оставлена вне очереди."
                )
            except Exception:
                logger.exception("Не удалось отправить сообщение об ошибке LM")

        lm_state = None

    lm_task = None
    lm_state = None


async def start_lm(nick, count, source_event):
    global lm_task, lm_state, lm_queue

    if config["mine_work_chat"] is None:
        await answer_and_delete(
            source_event,
            "⚠️ Сначала подключите рабочую группу командой "
            "<code>.work</code>."
        )
        return

    config["lm_work_chat"] = config["mine_work_chat"]

    # Repeating .lm for an existing nickname changes that job's requested
    # total instead of creating a duplicate. This allows increasing/decreasing
    # the amount while the player is actively being processed or waiting.
    existing, _ = lm_find_job(nick)
    if existing is not None:
        sent = lm_job_sent_count(existing)
        existing["total"] = max(sent, count)
        existing["remaining"] = max(0, existing["total"] - sent)
        existing["destination_chat"] = source_event.chat_id
        msg = await source_event.edit(
            f"✏️ <b>Изменил количество переводов игроку</b> "
            f"<code>{existing['nick']}</code> → <code>{existing['total']}</code>\n"
            f"📦 <b>Осталось:</b> <code>{existing['remaining']}</code>\n"
            f"⏱ <b>Ожидаемое время:</b> <code>{format_duration_seconds(lm_eta_seconds(existing))}</code>."
        )
        autodelete(msg)
        return

    job = {
        "nick": nick,
        "total": count,
        "remaining": count,
        "amount": None,
        "paused": False,
        "work_chat": config["lm_work_chat"],
        "error": False,
        "destination_chat": source_event.chat_id,
    }
    lm_queue.append(job)

    position = len(lm_queue) + (1 if lm_state is not None else 0)
    eta = lm_eta_seconds(job)
    if lm_state is None and lm_task is None:
        text = (
            f"💵 <b>Добавил перевод в очередь</b> игроку "
            f"<code>{nick}</code> : <code>{count}</code>\n"
            f"▶️ <b>Начинаю обработку.</b>\n"
            f"⏱ <b>Ожидаемое время:</b> <code>{format_duration_seconds(eta)}</code>"
        )
    else:
        text = (
            f"💵 <b>Добавил перевод в очередь</b> игроку "
            f"<code>{nick}</code> : <code>{count}</code>\n"
            f"📋 <b>Позиция в очереди:</b> <code>{position}</code>\n"
            f"⏱ <b>Ожидаемое время:</b> <code>{format_duration_seconds(eta)}</code>"
        )

    msg = await source_event.edit(text)
    autodelete(msg)

    if lm_task is None or lm_task.done():
        lm_task = asyncio.create_task(lm_transfer_loop())


CURRENCY_NAMES = {
    "✉️": "кт", "🧧": "ркт", "📦": "к", "🗳️": "рк",
    "🕋": "миф", "💎": "кр", "🎲": "дк", "🌌": "зв",
    "💼": "псэ", "👜": "ссп", "🧰": "ясэ", "🧳": "чсп",
    "👝": "рм", "🪅": "кк", "🎇": "ск", "💳": "эк",
    "🎫": "купон", "🥡": "лб", "🥚": "ясп",
}
EMOJI_PATTERN = "|".join(
    re.escape(x) for x in sorted(CURRENCY_NAMES, key=len, reverse=True)
)
RATE_RE = re.compile(
    rf"(?P<a>{EMOJI_PATTERN})\s*=\s*"
    rf"(?P<v>\d+(?:[.,]\d*)?)\s*(?P<b>{EMOJI_PATTERN})"
)


def normalize_emoji(s):
    return s.replace("\ufe0f", "️")


def parse_rates(text):
    rates = {}
    for m in RATE_RE.finditer(text or ""):
        a = normalize_emoji(m.group("a"))
        b = normalize_emoji(m.group("b"))
        value = float(m.group("v").replace(",", "."))
        if a in CURRENCY_NAMES and b in CURRENCY_NAMES:
            rates[(a, b)] = value
    return rates


def build_base_rates(text):
    pairs = parse_rates(text)
    if not pairs:
        return None, {}

    base = "🕋" if "🕋" in CURRENCY_NAMES else None
    if base is None:
        for (a, b), v in pairs.items():
            if a == b and abs(v - 1.0) < 1e-9:
                base = a
                break
    if base is None:
        return None, {}

    graph = {c: [] for c in CURRENCY_NAMES}
    for (a, b), v in pairs.items():
        if v == 0:
            continue
        graph.setdefault(a, []).append((b, 1.0 / v))
        graph.setdefault(b, []).append((a, v))

    values = {base: 1.0}
    queue = [base]
    while queue:
        cur = queue.pop(0)
        for nxt, multiplier in graph.get(cur, []):
            if nxt not in values:
                values[nxt] = values[cur] * multiplier
                queue.append(nxt)
    return base, values


def format_number(value):
    if abs(value) < 1e-12:
        return "0.0"
    s = f"{value:.3f}".rstrip("0").rstrip(".")
    if "." not in s:
        s += ".0"
    return s


def convert_rate(value_to_base, a, b):
    return value_to_base[a] / value_to_base[b]


def resolve_tc_target(name):
    for emoji, currency_name in CURRENCY_NAMES.items():
        if name == emoji or name.lower() == currency_name.lower():
            return emoji
    return None


def format_tc_number(value):
    value = float(value)
    if abs(value) < 1e-12:
        return "0.0"
    if value.is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def format_quantity(value):
    return format_tc_number(value)


def make_tc_output(template_text, target_names, quantity=1.0):
    pairs = parse_rates(template_text)
    if not pairs:
        return None

    target_emojis = []
    for name in target_names:
        found = resolve_tc_target(name)
        if found:
            target_emojis.append(found)

    if not target_emojis:
        return None

    quantity = float(quantity)
    if quantity <= 0:
        return None

    if len(target_emojis) == 1:
        target = target_emojis[0]
        parts = [f"{target} Текущий курс:", ""]

        # Keep the order of currencies from CURRENCY_NAMES and use the
        # explicit rates stored in the template. MineEVO's template can
        # intentionally contain rounded/non-reciprocal pairs, so deriving
        # one direction from the other would change the displayed course.
        tc_order = [
            "✉️", "🧧", "📦", "🗳️", "🕋", "💎", "🎲", "🌌",
            "💼", "👜", "🧳", "🧰", "👝", "🥡", "🥚", "🎫",
            "💳", "🎇", "🪅",
        ]
        for currency in tc_order:
            if currency == target:
                continue

            other_to_target = pairs.get((currency, target))
            target_to_other = pairs.get((target, currency))

            # If one direction is absent, use the reciprocal as a fallback.
            if other_to_target is None and target_to_other not in (None, 0):
                other_to_target = 1.0 / target_to_other
            if target_to_other is None and other_to_target not in (None, 0):
                target_to_other = 1.0 / other_to_target

            if other_to_target is None or target_to_other is None:
                continue

            parts.append(
                f"{format_quantity(quantity)} {currency} = "
                f"{format_tc_number(other_to_target * quantity)} {target}"
            )
            parts.append(
                f"{format_quantity(quantity)} {target} = "
                f"{format_tc_number(target_to_other * quantity)} {currency}"
            )
            parts.append("")

        parts.append(
            f"{format_quantity(quantity)} {target} = "
            f"{format_quantity(quantity)} {target}"
        )
        parts.append(
            f"{format_quantity(quantity)} {target} = "
            f"{format_quantity(quantity)} {target}"
        )
        return "\n".join(parts)

    a, b = target_emojis[:2]
    a_to_b = pairs.get((a, b))
    b_to_a = pairs.get((b, a))
    if a_to_b is None and b_to_a not in (None, 0):
        a_to_b = 1.0 / b_to_a
    if b_to_a is None and a_to_b not in (None, 0):
        b_to_a = 1.0 / a_to_b
    if a_to_b is None or b_to_a is None:
        return None

    return (
        f"{format_quantity(quantity)} {a} = "
        f"{format_tc_number(a_to_b * quantity)} {b}\n"
        f"{format_quantity(quantity)} {b} = "
        f"{format_tc_number(b_to_a * quantity)} {a}"
    )


CALC_ALLOWED = re.compile(r"^[0-9+\-*/().,%\s×÷•√]+$")


class _PercentValue:
    def __init__(self, value):
        self.value = float(value)


def _calc_number(value):
    if isinstance(value, _PercentValue):
        return value.value / 100.0
    return float(value)


def _eval_calc_node(node):
    if isinstance(node, ast.Expression):
        return _eval_calc_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_calc_node(node.operand)
        if isinstance(value, _PercentValue):
            return _PercentValue(
                -value.value if isinstance(node.op, ast.USub) else value.value
            )
        return +value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "percent" and len(node.args) == 1 \
            and not node.keywords:
        return _PercentValue(_calc_number(_eval_calc_node(node.args[0])))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "sqrt" and len(node.args) == 1 \
            and not node.keywords:
        value = _calc_number(_eval_calc_node(node.args[0]))
        if value < 0:
            raise ValueError("Корень из отрицательного числа")
        return math.sqrt(value)
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
    ):
        left = _eval_calc_node(node.left)
        right = _eval_calc_node(node.right)
        if isinstance(node.op, (ast.Add, ast.Sub)) and isinstance(
            right, _PercentValue
        ):
            if isinstance(left, _PercentValue):
                lv, rv = left.value / 100.0, right.value / 100.0
                return lv + rv if isinstance(node.op, ast.Add) else lv - rv
            delta = float(left) * right.value / 100.0
            return (
                float(left) + delta if isinstance(node.op, ast.Add)
                else float(left) - delta
            )
        l, r = _calc_number(left), _calc_number(right)
        if isinstance(node.op, ast.Add):
            return l + r
        if isinstance(node.op, ast.Sub):
            return l - r
        if isinstance(node.op, ast.Mult):
            return l * r
        if isinstance(node.op, ast.Div):
            if r == 0:
                raise ZeroDivisionError
            return l / r
        return l ** r
    raise ValueError("Недопустимое выражение")


def calculate_expression(expr):
    expr = (expr or "").strip()
    if not expr or not CALC_ALLOWED.fullmatch(expr):
        raise ValueError("Недопустимое выражение")
    expr = expr.replace(",", ".").replace("×", "*").replace("÷", "/").replace("•", "*")
    expr = re.sub(r"√\s*(\d+(?:\.\d*)?)", r"sqrt(\1)", expr)
    expr = expr.replace("√(", "sqrt(")
    expr = re.sub(r"(\d+(?:\.\d*)?)%", r"percent(\1)", expr)
    return _eval_calc_node(ast.parse(expr, mode="eval"))


def _tc_formatted_text(result):
    # Single-target result always has a heading followed by a rate table.
    # Two-target result has no heading and therefore no quote.
    if "\n" not in result and " Текущий курс:" not in result:
        return result, None

    marker = " Текущий курс:"
    if marker not in result:
        return result, None

    heading, body = result.split(":", 1)
    heading = heading + ":"
    body = body.lstrip()
    text = f"{heading}\n\n{body}"
    heading_len = len(heading.encode("utf-16-le")) // 2
    body_offset = len(f"{heading}\n\n".encode("utf-16-le")) // 2
    body_len = len(body.encode("utf-16-le")) // 2
    entities = [
        MessageEntityBold(offset=0, length=heading_len),
        MessageEntityBlockquote(
            offset=body_offset, length=body_len, collapsed=True
        ),
    ]
    return text, entities



# ---------- Автоатака боссов MineEVO ----------

BO_HP_REFRESH_THRESHOLD = 50
BO_INITIAL_HITS = 9
BO_WAIT_TIMEOUT = 10
BO_STATE_TIMEOUT = 5

BO_TIME_RE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>ч(?:ас(?:а|ов)?)?\.?|мин(?:ут(?:а|ы)?)?\.?|сек(?:унд(?:а|ы)?)?\.?)",
    re.IGNORECASE,
)

BO_HP_RE = re.compile(
    r"❤\s*Босс\s*:\s*([\d\s.,]+)\s*/\s*([\d\s.,]+)\s*ОЗ",
    re.IGNORECASE,
)


def bo_parse_number(value):
    value = (value or "").replace(" ", "")
    if "," in value and "." in value:
        # MineEVO uses comma as a thousands separator and dot for decimals,
        # e.g. 7,771.7.
        value = value.replace(",", "")
    elif "," in value:
        tail = value.rsplit(",", 1)[1]
        # A single comma followed by 1-2 digits is treated as a decimal.
        # Three trailing digits are normally a thousands separator.
        value = value.replace(",", "." if len(tail) != 3 else "")
    return float(value)


def bo_parse_hp(text):
    match = BO_HP_RE.search(text or "")
    if not match:
        return None
    try:
        return bo_parse_number(match.group(1))
    except (TypeError, ValueError):
        return None


def bo_parse_wait_time(text):
    """
    Разбирает только время из callback alert.
    Примеры:
      2ч. 15мин. 30сек.
      15мин. 30сек.
      30сек.
    """
    total = 0.0
    found = False
    units = {
        "ч": 3600,
        "час": 3600,
        "часа": 3600,
        "часов": 3600,
        "мин": 60,
        "минута": 60,
        "минуты": 60,
        "минут": 60,
        "сек": 1,
        "секунда": 1,
        "секунды": 1,
        "секунд": 1,
    }
    for match in BO_TIME_RE.finditer(text or ""):
        found = True
        value = float(match.group("value").replace(",", "."))
        unit = match.group("unit").lower().rstrip(".")
        total += value * units.get(unit, 0)
    return total if found else None


def bo_is_battle(text):
    text = text or ""
    return (
        "❤ Босс" in text
        and "ОЗ" in text
        and "Атаковать" in text
    )


def bo_is_boss_menu(text):
    return "⚔️ Выбери босса" in (text or "")


def bo_is_victory(text):
    text = text or ""
    return "⚔ Босс был повержен!" in text


def bo_find_button(message, exact_text):
    if not message or not message.buttons:
        return None
    for row_index, row in enumerate(message.buttons):
        for col_index, button in enumerate(row):
            if (button.text or "").strip() == exact_text:
                return row_index, col_index, button
    return None


def bo_find_button_contains(message, text):
    if not message or not message.buttons:
        return None
    wanted = text.lower()
    for row_index, row in enumerate(message.buttons):
        for col_index, button in enumerate(row):
            if wanted in (button.text or "").lower():
                return row_index, col_index, button
    return None


def bo_callback_buttons(message):
    result = []
    if not message or not message.buttons:
        return result
    for row_index, row in enumerate(message.buttons):
        for col_index, button in enumerate(row):
            if getattr(button, "data", None) is not None:
                result.append((row_index, col_index, button))
    return result


async def bo_click(message, row, col):
    """
    Нажатие callback-кнопки без искусственной задержки.
    Telethon возвращает BotCallbackAnswer, из которого можно получить alert.
    FloodWait ждём ровно столько, сколько потребовал Telegram.
    """
    while True:
        if bo_stop_event and bo_stop_event.is_set():
            raise asyncio.CancelledError
        try:
            return await message.click(row, col)
        except errors.FloodWaitError as exc:
            logger.warning("[BO] FloodWait: жду %s сек.", exc.seconds)
            try:
                await asyncio.wait_for(
                    bo_stop_event.wait(), timeout=exc.seconds
                )
            except asyncio.TimeoutError:
                pass


async def bo_wait_after_action(
    chat_id,
    message_id,
    before_text,
    before_buttons,
    predicate,
    timeout=BO_STATE_TIMEOUT,
):
    """
    Ждёт изменение состояния после callback-кнопки.
    Важен именно change-check: нельзя принять старое сообщение сразу после
    клика, иначе следующий удар/refresh уйдёт до ответа MineEVO.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def changed(message):
        if not message:
            return False
        text = message.raw_text or ""
        buttons = repr(message.buttons)
        if message.id != message_id:
            return True
        return text != before_text or buttons != before_buttons

    async def accept(message):
        if future.done() or not message:
            return
        if changed(message) and predicate(message):
            future.set_result(message)

    async def new_handler(event):
        await accept(event.message)

    async def edited_handler(event):
        await accept(event.message)

    client.add_event_handler(new_handler, events.NewMessage(chats=chat_id))
    client.add_event_handler(edited_handler, events.MessageEdited(chats=chat_id))
    try:
        # Update мог прийти до регистрации обработчиков.
        current = await client.get_messages(chat_id, ids=message_id)
        await accept(current)

        if future.done():
            return future.result()

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
    finally:
        client.remove_event_handler(new_handler, events.NewMessage(chats=chat_id))
        client.remove_event_handler(
            edited_handler, events.MessageEdited(chats=chat_id)
        )




async def bo_wait_new_message(chat_id, after_id, timeout=BO_STATE_TIMEOUT):
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async def handler(event):
        message = event.message
        if future.done() or not message or message.id <= after_id:
            return
        if message.out:
            return
        future.set_result(message)

    client.add_event_handler(handler, events.NewMessage(chats=chat_id))
    try:
        # Проверяем историю один раз на случай уже пришедшего сообщения.
        messages = await client.get_messages(chat_id, limit=10)
        for message in messages:
            if message.id > after_id and not message.out:
                return message
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
    finally:
        client.remove_event_handler(handler, events.NewMessage(chats=chat_id))


async def bo_get_fresh_message(chat_id, message_id):
    if message_id is None:
        return None
    return await client.get_messages(chat_id, ids=message_id)


async def bo_wait_seconds(seconds):
    # Ожидание прерывается .booff практически сразу.
    if seconds <= 0:
        return
    try:
        await asyncio.wait_for(bo_stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def bo_select_boss(menu_message):
    """
    Нажимает все callback-кнопки меню боссов и выбирает минимальное время.
    Если какая-либо кнопка сразу открывает бой, возвращает уже открытый бой.
    """
    buttons = bo_callback_buttons(menu_message)
    if not buttons:
        raise RuntimeError("В меню боссов не найдено callback-кнопок.")

    candidates = []
    menu_id = menu_message.id
    chat_id = menu_message.chat_id

    for row, col, button in buttons:
        if bo_stop_event.is_set():
            raise asyncio.CancelledError

        current = await bo_get_fresh_message(chat_id, menu_id)
        if not current or not current.buttons:
            raise RuntimeError("Меню боссов исчезло во время перебора.")

        try:
            button = current.buttons[row][col]
        except (IndexError, TypeError):
            continue

        before_text = current.raw_text or ""
        before_buttons = repr(current.buttons)

        answer = await bo_click(current, row, col)
        alert_text = getattr(answer, "message", None) or ""
        wait_seconds = bo_parse_wait_time(alert_text)

        logger.info(
            "[BO] Кнопка %r -> alert=%r, wait=%s",
            button.text, alert_text, wait_seconds
        )

        if wait_seconds is not None:
            candidates.append((wait_seconds, row, col, button.text))
            continue

        # Если времени в alert нет, это может быть кнопка, которая сразу
        # открыла бой. Только в этом случае ждём изменения состояния.
        battle = await bo_wait_after_action(
            chat_id,
            menu_id,
            before_text,
            before_buttons,
            bo_is_battle,
            timeout=BO_STATE_TIMEOUT,
        )
        if battle:
            return {
                "battle": battle,
                "wait": 0,
                "row": row,
                "col": col,
                "button_text": button.text,
            }

    if not candidates:
        raise RuntimeError(
            "Не удалось получить время ожидания ни от одной кнопки босса."
        )

    wait_seconds, row, col, button_text = min(
        candidates, key=lambda item: item[0]
    )
    logger.info(
        "[BO] Выбран %r, ожидание %.3f сек.",
        button_text, wait_seconds
    )
    await bo_wait_seconds(wait_seconds)

    if bo_stop_event.is_set():
        raise asyncio.CancelledError

    current = await bo_get_fresh_message(chat_id, menu_id)
    if not current or not current.buttons:
        raise RuntimeError("Сообщение меню боссов исчезло до повторного нажатия.")

    try:
        selected_button = current.buttons[row][col]
    except (IndexError, TypeError):
        raise RuntimeError("Выбранная кнопка босса больше недоступна.")

    before_text = current.raw_text or ""
    before_buttons = repr(current.buttons)

    await bo_click(current, row, col)

    battle = await bo_wait_after_action(
        chat_id,
        menu_id,
        before_text,
        before_buttons,
        bo_is_battle,
        timeout=BO_STATE_TIMEOUT,
    )
    if not battle:
        battle = await bo_wait_new_message(
            chat_id, after_id=menu_id, timeout=BO_STATE_TIMEOUT
        )
    if not battle or not bo_is_battle(battle.raw_text or ""):
        raise RuntimeError("После ожидания MineEVO не открыл бой.")

    return {
        "battle": battle,
        "wait": wait_seconds,
        "row": row,
        "col": col,
        "button_text": selected_button.text,
    }


async def bo_fight(battle):
    """
    9 атак -> обновление до HP <= 50 -> атака до реального сообщения
    «Босс был повержен!».
    """
    current = battle
    chat_id = battle.chat_id

    for hit_number in range(BO_INITIAL_HITS):
        if bo_stop_event.is_set():
            raise asyncio.CancelledError

        current = await bo_get_fresh_message(chat_id, current.id) or current
        if bo_is_victory(current.raw_text or ""):
            return current

        attack = bo_find_button(current, "Атаковать")
        if not attack:
            raise RuntimeError("Кнопка «Атаковать» не найдена.")

        before_text = current.raw_text or ""
        before_buttons = repr(current.buttons)
        await bo_click(current, attack[0], attack[1])

        updated = await bo_wait_after_action(
            chat_id,
            current.id,
            before_text,
            before_buttons,
            lambda m: bo_is_battle(m.raw_text or "") or
            bo_is_victory(m.raw_text or ""),
            timeout=BO_STATE_TIMEOUT,
        )
        if updated:
            current = updated

        if bo_is_victory(current.raw_text or ""):
            return current

    while True:
        if bo_stop_event.is_set():
            raise asyncio.CancelledError

        current = await bo_get_fresh_message(chat_id, current.id) or current
        if bo_is_victory(current.raw_text or ""):
            return current

        hp = bo_parse_hp(current.raw_text or "")
        if hp is None:
            raise RuntimeError("Не удалось определить HP босса.")

        if hp <= BO_HP_REFRESH_THRESHOLD:
            break

        refresh = bo_find_button(current, "🔄 Обновить")
        if not refresh:
            raise RuntimeError("Кнопка «🔄 Обновить» не найдена.")

        before_text = current.raw_text or ""
        before_buttons = repr(current.buttons)
        await bo_click(current, refresh[0], refresh[1])

        updated = await bo_wait_after_action(
            chat_id,
            current.id,
            before_text,
            before_buttons,
            lambda m: bo_is_battle(m.raw_text or "") or
            bo_is_victory(m.raw_text or ""),
            timeout=BO_STATE_TIMEOUT,
        )
        if updated:
            current = updated

        if bo_is_victory(current.raw_text or ""):
            return current

    while True:
        if bo_stop_event.is_set():
            raise asyncio.CancelledError

        current = await bo_get_fresh_message(chat_id, current.id) or current
        if bo_is_victory(current.raw_text or ""):
            return current

        attack = bo_find_button(current, "Атаковать")
        if not attack:
            raise RuntimeError("Кнопка «Атаковать» не найдена.")

        before_text = current.raw_text or ""
        before_buttons = repr(current.buttons)
        await bo_click(current, attack[0], attack[1])

        updated = await bo_wait_after_action(
            chat_id,
            current.id,
            before_text,
            before_buttons,
            lambda m: bo_is_battle(m.raw_text or "") or
            bo_is_victory(m.raw_text or ""),
            timeout=BO_STATE_TIMEOUT,
        )
        if updated:
            current = updated


async def bo_reward_and_return(victory):
    if bo_stop_event.is_set():
        raise asyncio.CancelledError

    reward = bo_find_button(victory, "🎉 Получить")
    if not reward:
        raise RuntimeError("Кнопка «🎉 Получить» не найдена.")

    old_id = victory.id
    await bo_click(victory, reward[0], reward[1])

    reward_message = await bo_wait_new_message(
        victory.chat_id, after_id=old_id, timeout=BO_STATE_TIMEOUT
    )
    if not reward_message:
        messages = await client.get_messages(victory.chat_id, limit=10)
        reward_message = next(
            (
                m for m in messages
                if m.id > old_id and
                "🎉 Награда получена:" in (m.raw_text or "")
            ),
            None,
        )
    if not reward_message:
        raise RuntimeError("Сообщение «🎉 Награда получена» не получено.")

    if bo_stop_event.is_set():
        raise asyncio.CancelledError

    back = bo_find_button(reward_message, "К боссам")
    if not back:
        raise RuntimeError("Кнопка «К боссам» не найдена.")

    before_text = reward_message.raw_text or ""
    before_buttons = repr(reward_message.buttons)

    await bo_click(reward_message, back[0], back[1])

    menu = await bo_wait_after_action(
        reward_message.chat_id,
        reward_message.id,
        before_text,
        before_buttons,
        bo_is_boss_menu,
        timeout=BO_STATE_TIMEOUT,
    )
    if not menu:
        raise RuntimeError("После «К боссам» меню боссов не появилось.")
    return menu


async def bo_loop(work_chat):
    global bo_stop_event
    try:
        first_menu = await ask_mineevo("бо")
        if not first_menu or not bo_is_boss_menu(first_menu.raw_text or ""):
            raise RuntimeError("После «бо» не получено меню выбора босса.")

        menu = first_menu

        while not bo_stop_event.is_set():
            selected = await bo_select_boss(menu)
            if bo_stop_event.is_set():
                raise asyncio.CancelledError

            victory = await bo_fight(selected["battle"])
            if bo_stop_event.is_set():
                raise asyncio.CancelledError

            menu = await bo_reward_and_return(victory)

    except asyncio.CancelledError:
        logger.info("[BO] Цикл автоатаки остановлен.")
        raise
    except Exception:
        logger.exception("[BO] Ошибка цикла автоатаки")
        raise


async def register_handlers():
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.work$"))
    async def work_handler(event):
        config["mine_work_chat"] = event.chat_id
        config["lm_work_chat"] = event.chat_id
        save_config()
        msg = await event.edit(
            "✅ <b>Рабочая группа MineEVO подключена.</b>\n"
            "Все функции MineEVO будут использовать этот чат."
        )
        autodelete(msg)

    @client.on(events.NewMessage(
        outgoing=True, pattern=r"^\.promoseen(?:\s+([+-])([A-Za-z0-9_-]+))?$"
    ))
    async def promoseen_handler(event):
        match = event.pattern_match
        action = match.group(1)
        code = match.group(2)
        seen = {
            x.strip() for x in config.get("promo_seen", "").split(",")
            if x.strip()
        }

        if not action or not code:
            lines = ["📋 <b>promo_seen:</b>"]
            if seen:
                lines.extend(f"<code>{item}</code>" for item in sorted(seen))
            else:
                lines.append("<code>пусто</code>")
            lines.extend([
                "",
                "Добавить: <code>.promoseen</code> +[КОД]",
                "Удалить: <code>.promoseen</code> -[КОД]",
            ])
            return await answer_and_delete(event, "\n".join(lines))

        if action == "+":
            if code in seen:
                return await answer_and_delete(
                    event, f"⚠️ Код <code>{code}</code> уже находится в <b>promo_seen</b>."
                )
            seen.add(code)
            config["promo_seen"] = ",".join(sorted(seen))
            save_config()
            return await answer_and_delete(
                event, f"✅ Код <code>{code}</code> добавлен в <b>promo_seen</b>."
            )

        if code not in seen:
            return await answer_and_delete(
                event, f"⚠️ Код <code>{code}</code> отсутствует в <b>promo_seen</b>."
            )
        seen.remove(code)
        config["promo_seen"] = ",".join(sorted(seen))
        save_config()
        await answer_and_delete(
            event, f"✅ Код <code>{code}</code> удалён из <b>promo_seen</b>."
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.bo$"))
    async def bo_handler(event):
        global bo_task, bo_stop_event

        if config["mine_work_chat"] is None:
            return await answer_and_delete(
                event,
                "⚠️ Сначала подключите рабочую группу MineEVO командой "
                "<code>.work</code>."
            )

        if bo_task and not bo_task.done():
            return await answer_and_delete(
                event, "⚠️ Автоатака боссов уже запущена."
            )

        bo_stop_event = asyncio.Event()
        work_chat = config["mine_work_chat"]

        await event.edit(
            "⚔️ <b>Автоатака боссов запущена.</b>\n"
            "Остановить: <code>.booff</code>"
        )

        bo_task = asyncio.create_task(bo_loop(work_chat))

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.booff$"))
    async def booff_handler(event):
        global bo_task, bo_stop_event

        if not bo_task or bo_task.done():
            return await answer_and_delete(
                event, "ℹ️ Автоатака боссов сейчас не запущена."
            )

        if bo_stop_event:
            bo_stop_event.set()
        bo_task.cancel()

        try:
            await bo_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("[BO] Ошибка при остановке")

        bo_task = None
        bo_stop_event = None

        await event.edit("⛔ <b>Автоатака боссов остановлена.</b>")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.thxsource$"))
    async def thxsource_handler(event):
        config["thx_source_chat"] = event.chat_id
        config["thx_enabled"] = True
        save_config()
        msg = await event.edit(
            "✅ <b>Поиск Thx включён.</b>\n"
            "Этот чат теперь является источником событий."
        )
        autodelete(msg)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.thxoff$"))
    async def thxoff_handler(event):
        config["thx_enabled"] = False
        save_config()
        msg = await event.edit("⛔ <b>Поиск Thx выключен.</b>")
        autodelete(msg)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lmgroup$"))
    async def lmgroup_handler(event):
        config["lm_work_chat"] = event.chat_id
        save_config()
        msg = await event.edit(
            "✅ <b>Рабочая группа переводов лимитов подключена.</b>"
        )
        autodelete(msg)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lm\s+(\S+)\s+(\d+)$"))
    async def lm_handler(event):
        await start_lm(
            event.pattern_match.group(1),
            int(event.pattern_match.group(2)),
            event
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lmpause(?:\s+(\S+))?$"))
    async def lmpause_handler(event):
        global lm_paused, lm_task, lm_state, lm_queue, lm_paused_queue
        nick = event.pattern_match.group(1)

        if not nick:
            if not lm_state and not lm_queue and not lm_paused_queue:
                return await answer_and_delete(event, "⚠️ Сейчас переводов лимитов нет.")
            lm_paused = True
            msg = await event.edit("⏸️ <b>Вся очередь переводов лимитов приостановлена.</b>")
            autodelete(msg)
            return

        job, queue_pos = lm_find_job(nick)
        if job is None:
            return await answer_and_delete(
                event,
                f"ℹ️ <b>Перевода игроку</b> <code>{nick}</code> <b>сейчас нет.</b>"
            )
        if job.get("paused"):
            return await answer_and_delete(
                event,
                f"⏸️ <b>Перевод игроку</b> <code>{job['nick']}</code> <b>уже на паузе.</b>"
            )

        # If this job is currently active, stop only its worker and put the
        # job at the end of the paused queue. The global cooldown is preserved.
        if lm_state is job:
            if lm_task and not lm_task.done():
                lm_task.cancel()
                try:
                    await lm_task
                except asyncio.CancelledError:
                    pass
            lm_task = None
            lm_state = None
        else:
            try:
                lm_queue.remove(job)
            except ValueError:
                pass

        job["paused"] = True
        lm_paused_queue.append(job)

        if lm_queue and (lm_task is None or lm_task.done()) and not lm_paused:
            lm_task = asyncio.create_task(lm_transfer_loop())

        msg = await event.edit(
            f"⏸️ <b>Перевод игроку</b> <code>{job['nick']}</code> "
            f"<b>приостановлен и отправлен в конец очереди.</b>"
        )
        autodelete(msg)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lmresume(?:\s+(\S+))?$"))
    async def lmresume_handler(event):
        global lm_paused, lm_task, lm_queue, lm_paused_queue
        nick = event.pattern_match.group(1)

        if not nick:
            if not lm_state and not lm_queue and not lm_paused_queue:
                return await answer_and_delete(event, "⚠️ Сейчас переводов лимитов нет.")
            lm_paused = False
            # Restore all individually paused jobs to the front, preserving
            # their paused-queue order, then continue normal FIFO processing.
            restored = list(lm_paused_queue)
            lm_paused_queue.clear()
            for job in reversed(restored):
                job["paused"] = False
                lm_queue.appendleft(job)
            if lm_task is None or lm_task.done():
                lm_task = asyncio.create_task(lm_transfer_loop())
            msg = await event.edit("▶️ <b>Вся очередь переводов лимитов возобновлена.</b>")
            autodelete(msg)
            return

        job, queue_pos = lm_find_job(nick)
        if job is None:
            return await answer_and_delete(
                event,
                f"ℹ️ <b>Перевода игроку</b> <code>{nick}</code> <b>нет в очереди.</b>"
            )
        if not job.get("paused"):
            return await answer_and_delete(
                event,
                f"▶️ <b>Перевод игроку</b> <code>{job['nick']}</code> <b>уже активен или ожидает.</b>"
            )

        try:
            lm_paused_queue.remove(job)
        except ValueError:
            pass
        job["paused"] = False
        lm_queue.appendleft(job)

        if not lm_paused and (lm_task is None or lm_task.done()):
            lm_task = asyncio.create_task(lm_transfer_loop())

        msg = await event.edit(
            f"▶️ <b>Перевод игроку</b> <code>{job['nick']}</code> "
            f"<b>возобновлён и поставлен в начало очереди.</b>"
        )
        autodelete(msg)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lmstop(?:\s+(\S+))?$"))
    async def lmstop_handler(event):
        global lm_task, lm_state, lm_queue, lm_paused_queue, lm_paused
        nick = event.pattern_match.group(1)

        if not nick:
            if not lm_state and not lm_queue and not lm_paused_queue:
                return await answer_and_delete(event, "⚠️ Сейчас переводов лимитов нет.")
            lm_paused = False
            lm_queue.clear()
            lm_paused_queue.clear()
            if lm_task and not lm_task.done():
                lm_task.cancel()
                try:
                    await lm_task
                except asyncio.CancelledError:
                    pass
            lm_task = None
            lm_state = None
            # IMPORTANT: do NOT reset lm_last_send_at here.
            msg = await event.edit("❌ <b>Все переводы лимитов остановлены и удалены из очереди.</b>")
            autodelete(msg)
            return

        job, queue_pos = lm_find_job(nick)
        if job is None:
            return await answer_and_delete(
                event,
                f"ℹ️ <b>Перевода игроку</b> <code>{nick}</code> <b>сейчас нет.</b>"
            )

        was_active = lm_state is job
        if was_active:
            if lm_task and not lm_task.done():
                lm_task.cancel()
                try:
                    await lm_task
                except asyncio.CancelledError:
                    pass
            lm_task = None
            lm_state = None
        else:
            try:
                lm_queue.remove(job)
            except ValueError:
                pass
            try:
                lm_paused_queue.remove(job)
            except ValueError:
                pass

        if lm_queue and not lm_paused and (lm_task is None or lm_task.done()):
            lm_task = asyncio.create_task(lm_transfer_loop())

        msg = await event.edit(
            f"❌ <b>Перевод игроку</b> <code>{job['nick']}</code> <b>остановлен и удалён из очереди.</b>"
        )
        autodelete(msg)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lmq$"))
    async def lmq_handler(event):
        if not lm_state and not lm_queue and not lm_paused_queue:
            return await event.edit("📋 <b>Очередь переводов лимитов пуста.</b>")

        lines = ["📋 <b>Очередь переводов лимитов</b>"]
        if lm_paused:
            lines.append("⏸️ <b>Вся очередь сейчас приостановлена.</b>")

        if lm_state:
            lines.append(
                f"\n▶️ <b>Сейчас переводится:</b> <code>{lm_state['nick']}</code> — "
                f"<code>{lm_state['remaining']}</code>/<code>{lm_state['total']}</code>"
            )

        if lm_queue:
            lines.append("\n⏳ <b>Ожидают:</b>")
            for idx, job in enumerate(lm_queue, start=1):
                lines.append(
                    f"{idx}. <code>{job['nick']}</code> — "
                    f"<code>{job['remaining']}</code>/<code>{job['total']}</code>"
                )

        if lm_paused_queue:
            lines.append("\n⏸️ <b>На паузе:</b>")
            for idx, job in enumerate(lm_paused_queue, start=1):
                lines.append(
                    f"{idx}. <code>{job['nick']}</code> — "
                    f"<code>{job['remaining']}</code>/<code>{job['total']}</code>"
                )

        total_remaining = sum(max(0, int(j.get("remaining", 0))) for j in lm_queue)
        total_remaining += sum(max(0, int(j.get("remaining", 0))) for j in lm_paused_queue)
        if lm_state:
            total_remaining += max(0, int(lm_state.get("remaining", 0)))
        players = (1 if lm_state else 0) + len(lm_queue) + len(lm_paused_queue)
        lines.append(f"\n👥 <b>Игроков:</b> <code>{players}</code>")
        lines.append(f"📦 <b>Всего осталось переводов:</b> <code>{total_remaining}</code>")

        loop = asyncio.get_running_loop()
        cooldown = 0
        if lm_last_send_at is not None:
            cooldown = max(0, int(lm_last_send_at + LM_INTERVAL_SECONDS - loop.time() + 0.999))
        lines.append(f"⏱ <b>До следующего слота:</b> <code>{format_duration_seconds(cooldown)}</code>")
        await event.edit("\n".join(lines))

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lchk\s+(\S+)$"))
    async def lchk_handler(event):
        nick = event.pattern_match.group(1)
        job, queue_pos = lm_find_job(nick)
        if job is None:
            return await answer_and_delete(
                event,
                f"ℹ️ <b>Сейчас игроку</b> <code>{nick}</code> "
                f"<b>ничего не переводится и в очереди его нет.</b>"
            )

        eta = lm_eta_seconds(job) if not job.get("paused") else None
        if job.get("paused"):
            status = "⏸️ <b>На паузе.</b>"
        elif queue_pos == 0:
            status = "▶️ <b>Переводится сейчас.</b>"
        else:
            status = f"📋 <b>Позиция в очереди:</b> <code>{queue_pos}</code>"

        text = (
            f"💵 <b>Игрок:</b> <code>{job['nick']}</code>\n"
            f"{status}\n"
            f"📦 <b>Осталось:</b> <code>{job['remaining']}</code>/<code>{job['total']}</code>"
        )
        if eta is not None:
            text += f"\n⏱ <b>Ожидаемое время до завершения:</b> <code>{format_duration_seconds(eta)}</code>."
        await event.edit(text)

    @client.on(events.NewMessage(
        outgoing=True, pattern=r"^\.urlbtn(?:\s+([\s\S]+))?$"
    ))
    async def urlbtn_handler(event):
        raw = (event.pattern_match.group(1) or "").strip()
        text, buttons = parse_urlbtn(raw)
        if not text or not buttons:
            return await answer_and_delete(
                event,
                "<b>Формат:</b>\n"
                "<code>.urlbtn Текст сообщения\n"
                "Текст кнопки - https://example.com</code>"
            )
        data = {
            "text": text,
            "buttons": [
                [{"type": "url", "text": label, "url": url}]
                for label, url in buttons
            ],
        }
        reply_to = event.reply_to_msg_id if event.is_reply else None
        # Helper-related command: this is intentionally the exception to the
        # "edit the command itself" rule because the result is an inline message.
        try:
            await publish_through_helper(
                data, event.chat_id, reply_to=reply_to
            )
            await event.delete()
        except Exception:
            logger.exception("Ошибка .urlbtn")
            await event.edit("⚠️ <b>Не удалось создать inline-сообщение.</b>")

    @client.on(events.NewMessage(
        outgoing=True, pattern=r"^\.repeat(?: (.*))?$"
    ))
    async def repeat_handler(event):
        raw = (event.pattern_match.group(1) or "").strip()
        tokens = raw.split()
        text = entities = source = None

        if len(tokens) >= 3:
            count_str, interval_str = tokens[-2:]
            text = " ".join(tokens[:-2])
        elif len(tokens) == 2 and event.is_reply:
            count_str, interval_str = tokens
            source = await event.get_reply_message()
            text = source.raw_text
            entities = source.entities
        else:
            return await answer_and_delete(
                event,
                "<b>Формат 1:</b> <code>.repeat текст количество интервал_в_минутах</code>\n"
                "<b>Формат 2:</b> reply на сообщение + "
                "<code>.repeat количество интервал_в_минутах</code>"
            )

        if not count_str.isdigit() or int(count_str) <= 0:
            return await answer_and_delete(
                event,
                "⚠️ <b>Количество</b> должно быть целым числом больше 0."
            )
        try:
            interval_minutes = float(interval_str.replace(",", "."))
            if interval_minutes < 0:
                raise ValueError
        except ValueError:
            return await answer_and_delete(
                event,
                "⚠️ <b>Интервал</b> должен быть числом, например "
                "<code>1.5</code>."
            )

        count = int(count_str)
        chat_id = event.chat_id
        active_tasks[chat_id] = {"stop": False}
        status = await event.edit(
            f"🚀 <b>Запущено:</b> {count} повторов, "
            f"интервал {interval_minutes} мин.\n"
            f"Остановить: <code>.stoprepeat</code>"
        )
        autodelete(status)
        sent = 0
        try:
            for _ in range(count):
                if active_tasks.get(chat_id, {}).get("stop"):
                    msg = await client.send_message(
                        chat_id,
                        f"⛔ <b>Остановлено вручную</b> ({sent}/{count})."
                    )
                    autodelete(msg)
                    break
                if source is not None:
                    if source.media is not None:
                        await client.send_file(
                            chat_id, source.media,
                            caption=source.raw_text or None,
                            formatting_entities=source.entities,
                        )
                    else:
                        await client.send_message(
                            chat_id, source.raw_text or "",
                            formatting_entities=source.entities,
                        )
                else:
                    await client.send_message(chat_id, text)
                sent += 1
                if sent < count:
                    await asyncio.sleep(interval_minutes * 60)
            if sent == count:
                msg = await client.send_message(
                    chat_id, f"✅ <b>Готово:</b> отправлено {sent}/{count}."
                )
                autodelete(msg)
        finally:
            active_tasks.pop(chat_id, None)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.stoprepeat$"))
    async def stop_handler(event):
        chat_id = event.chat_id
        if chat_id in active_tasks:
            active_tasks[chat_id]["stop"] = True
            msg = await event.edit(
                "⏳ <b>Останавливаю</b> после текущей отправки..."
            )
        else:
            msg = await event.edit("Нет активных повторов в этом чате.")
        autodelete(msg)

    @client.on(events.NewMessage(
        outgoing=True, pattern=r"^\.evo(?: (.*))?$"
    ))
    async def evo_handler(event):
        args = (event.pattern_match.group(1) or "").strip()
        if not args:
            return await answer_and_delete(
                event, "⚠️ <b>Вы не указали команду для выполнения.</b>"
            )
        if config["mine_work_chat"] is None:
            return await answer_and_delete(
                event,
                "⚠️ Сначала подключите рабочую группу MineEVO командой "
                "<code>.work</code>."
            )
        try:
            response = await ask_mineevo(args)
            if response is None:
                return await answer_and_delete(
                    event, "⚠️ MineEVO не ответил."
                )
            data, callback_links = _message_to_helper_data(
                response, event.chat_id
            )
            source_link = {
                "source_chat": response.chat_id,
                "source_message_id": response.id,
                "destination_chat": event.chat_id,
                "callback_links": callback_links,
            }
            reply_to = event.reply_to_msg_id if event.is_reply else None
            await publish_through_helper(
                data, event.chat_id, reply_to=reply_to,
                source_link=source_link
            )
            await event.delete()
        except Exception:
            logger.exception("Ошибка .evo")
            await event.edit(
                "⚠️ <b>Не удалось получить ответ MineEVO.</b>"
            )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.tcset$"))
    async def tcset_handler(event):
        if not event.is_reply:
            return await answer_and_delete(
                event,
                "⚠️ Ответьте <b>reply</b> на сообщение с примером "
                "курса и напишите <code>.tcset</code>."
            )
        source = await event.get_reply_message()
        if not source or not source.raw_text:
            return await answer_and_delete(
                event, "⚠️ В сообщении нет текста."
            )
        _, values = build_base_rates(source.raw_text)
        if not values:
            return await answer_and_delete(
                event, "⚠️ Не удалось распознать курсы в сообщении."
            )
        config["tc_template_chat"] = event.chat_id
        config["tc_template_message"] = source.id
        save_config()
        msg = await event.edit(
            "✅ <b>Шаблон курса сохранён.</b>\n"
            f"Распознано валют: {len(values)}."
        )
        autodelete(msg)

    @client.on(events.NewMessage(
        outgoing=True, pattern=r"^\.tc(?:\s+(\S+)(?:\s+(\d+(?:[.,]\d+)?))?)?$"
    ))
    async def tc_handler(event):
        currency = (event.pattern_match.group(1) or "").strip()
        quantity_raw = (event.pattern_match.group(2) or "1").replace(",", ".")

        if not currency:
            return await answer_and_delete(
                event,
                "⚠️ Укажите валюту, например <code>.tc миф</code> "
                "или <code>.tc миф 32</code>."
            )

        try:
            quantity = float(quantity_raw)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            return await answer_and_delete(
                event,
                "⚠️ Количество должно быть числом больше 0."
            )

        if config["tc_template_chat"] is None or \
                config["tc_template_message"] is None:
            return await answer_and_delete(
                event,
                "⚠️ Сначала сохраните пример курса через "
                "<code>.tcset</code>."
            )
        try:
            template = await client.get_messages(
                config["tc_template_chat"],
                ids=config["tc_template_message"]
            )
            if not template or not template.raw_text:
                return await answer_and_delete(
                    event, "⚠️ Шаблон курса не найден."
                )

            result = make_tc_output(
                template.raw_text,
                [currency],
                quantity=quantity,
            )
            if not result:
                return await answer_and_delete(
                    event,
                    "⚠️ Не удалось построить курс по сохранённому шаблону."
                )

            text, entities = _tc_formatted_text(result)
            if entities:
                await event.edit(text, formatting_entities=entities)
            else:
                await event.edit(text)
        except Exception:
            logger.exception("Ошибка .tc")
            await answer_and_delete(
                event, "⚠️ Ошибка при расчёте курса."
            )


    @client.on(events.NewMessage(
        outgoing=True, pattern=r"^\.calc(?: (.*))?$"
    ))
    async def calc_handler(event):
        expr = (event.pattern_match.group(1) or "").strip()
        if not expr:
            return await answer_and_delete(
                event, "⚠️ Формат: <code>.calc 2+2*5</code>"
            )
        try:
            result = calculate_expression(expr)
            await event.edit(
                f"<code>{expr}</code> = "
                f"<b>{format_number(float(result))}</b>"
            )
        except Exception:
            await answer_and_delete(
                event, "⚠️ Не удалось вычислить пример."
            )

    @client.on(events.NewMessage(outgoing=True))
    async def evo_reply_watcher(event):
        if not event.is_reply or not event.raw_text:
            return
        if event.raw_text.lstrip().startswith("."):
            return
        key = (event.chat_id, event.reply_to_msg_id)
        link = inline_reply_links.get(key)
        if not link:
            return

        token = link.get("helper_token")
        inline_message_id = helper_inline_ids.get(token)
        if not inline_message_id:
            for _ in range(15):
                await asyncio.sleep(0.1)
                inline_message_id = helper_inline_ids.get(token)
                if inline_message_id:
                    break
        if not inline_message_id:
            logger.warning("Не получен inline_message_id для reply к .evo")
            return

        source_key = (link["source_chat"], link["source_message_id"])
        lock = mine_callback_locks.setdefault(source_key, asyncio.Lock())
        async with lock:
            try:
                before = await client.get_messages(
                    link["source_chat"], ids=link["source_message_id"]
                )
                before_text = before.raw_text if before else ""
                before_buttons = repr(before.buttons) if before else ""
                await client.send_message(
                    link["source_chat"],
                    event.raw_text,
                    reply_to=link["source_message_id"],
                )
                updated = None
                for _ in range(20):
                    await asyncio.sleep(0.1)
                    candidate = await client.get_messages(
                        link["source_chat"], ids=link["source_message_id"]
                    )
                    if not candidate:
                        continue
                    updated = candidate
                    if ((candidate.raw_text or "") != before_text or
                            repr(candidate.buttons) != before_buttons):
                        break
                if updated:
                    await update_helper_inline_message(
                        updated, link, inline_message_id
                    )
            except Exception:
                logger.exception("Ошибка reply к .evo")

    @client.on(events.NewMessage(incoming=True))
    async def thx_watcher(event):
        global thx_last_event_id
        if not config["thx_enabled"]:
            return
        source_chat = config["thx_source_chat"]
        if source_chat is None or event.chat_id != source_chat:
            return
        text = event.raw_text or ""
        if THX_TRIGGER.lower() not in text.lower():
            return
        if thx_last_event_id == (event.chat_id, event.id):
            return
        thx_last_event_id = (event.chat_id, event.id)
        await send_thx()


async def initialize():
    global client, promo_task
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    client.parse_mode = "html"
    await register_handlers()
    await client.start()
    logger.info("Юзербот запущен")
    promo_task = asyncio.create_task(promo_loop())


async def shutdown():
    global promo_task
    if promo_task:
        promo_task.cancel()
        promo_task = None
    if client:
        await client.disconnect()
