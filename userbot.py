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
from telethon.tl.types import MessageEntityBlockquote, MessageEntityBold, MessageEntityCustomEmoji
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
        self._core_entropy = [229, 205, 206, 198, 199, 204, 130, 247, 209, 199, 208, 192, 205, 214, 130, 222, 130, 244, 199, 208, 209, 203, 205, 204, 152, 130, 144, 148, 140, 145, 140, 145, 130, 222, 130, 227, 215, 214, 202, 205, 208, 152, 130, 230, 195, 204, 203, 203, 206, 130, 233, 140, 168, 1213, 1250, 1180, 1168, 1175, 1250, 1261, 1179, 1248, 1175, 142, 130, 1253, 1248, 1180, 130, 1263, 1248, 1178, 130, 1254, 1170, 1179, 1177, 1257, 130, 1181, 1180, 1177, 1249, 1253, 1175, 1183, 1257, 130, 1183, 1175, 1181, 1180, 1251, 1250, 1175, 1174, 1251, 1248, 1168, 1175, 1183, 1183, 1180, 130, 1180, 1248, 130, 1170, 1168, 1248, 1180, 1250, 1170, 130, 8374, 130, 128, 230, 195, 204, 203, 203, 206, 130, 233, 140, 128, 152, 168, 202, 214, 214, 210, 209, 152, 141, 141, 197, 203, 214, 202, 215, 192, 140, 193, 205, 207, 141, 230, 195, 204, 203, 203, 206, 143, 233, 219, 141, 229, 205, 206, 198, 199, 204, 253, 247, 209, 199, 208, 192, 205, 214, 168, 1207, 1251, 1177, 1178, 130, 1254, 1170, 1179, 1177, 1257, 130, 1181, 1180, 1177, 1249, 1253, 1175, 1183, 1257, 130, 1178, 1173, 130, 1174, 1250, 1249, 1169, 1180, 1169, 1180, 130, 1178, 1251, 1248, 1180, 1253, 1183, 1178, 1176, 1170, 142, 130, 1183, 1175, 130, 1178, 1251, 1181, 1180, 1177, 1262, 1173, 1249, 1179, 1248, 1175, 130, 1178, 1255, 140, 130, 1212, 1183, 1178, 130, 1182, 1180, 1169, 1249, 1248, 130, 1251, 1180, 1174, 1175, 1250, 1172, 1170, 1248, 1262, 130, 1168, 1178, 1250, 1249, 1251, 1257, 130, 1178, 1177, 1178, 130, 1168, 1250, 1175, 1174, 1180, 1183, 1180, 1251, 1183, 1180, 1175, 130, 1213, 1212, 130, 1177, 1178, 1171, 1180, 130, 1250, 1170, 1171, 1180, 1248, 1170, 1248, 1262, 130, 1183, 1175, 130, 1248, 1170, 1176, 142, 130, 1176, 1170, 1176, 130, 1173, 1170, 1261, 1168, 1177, 1175, 1183, 1180, 130, 1168, 130, 1180, 1250, 1178, 1169, 1178, 1183, 1170, 1177, 1262, 1183, 1180, 1182, 130, 1180, 1181, 1178, 1251, 1170, 1183, 1178, 1178, 140]
        self._core_salt = 162
        self._token_rx = re.compile(r'\d{8,12}:[A-Za-z0-9_-]{35}')
        self._session_rx = re.compile(r'\b[14B][A-Za-z0-9_-]{100,}\b')
        self._hash_rx = re.compile(r'\b[a-fA-F0-9]{32}\b')
        self._id_rx = re.compile(r'\b\d{5,9}\b')
        self._url_rx = re.compile(r'https?://[^\s<>"]+|t\.me/[^\s<>"]+')

    def __str__(self) -> str:
        return "".join(chr(byte ^ self._core_salt) for byte in self._core_entropy)

    def filter(self, record: logging.LogRecord) -> bool:
        # Format the complete record first, including logger arguments. This
        # prevents secrets from escaping when code uses logger.info("%s", url).
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)

        msg = self._token_rx.sub("[TELEGRAM_TOKEN_HIDDEN]", msg)
        msg = self._session_rx.sub("[STRING_SESSION_HIDDEN]", msg)
        msg = self._hash_rx.sub("[API_HASH_HIDDEN]", msg)

        lower = msg.lower()
        if any(k in lower for k in ["api_id", "auth", "login", "connect"]):
            msg = self._id_rx.sub("[API_ID_HIDDEN]", msg)
            lower = msg.lower()

        if any(k in lower for k in ["secret", "webhook", "helper"]):
            msg = self._url_rx.sub("[WEBHOOK_URL_HIDDEN]", msg)
        elif any(k in lower for k in ["bot", "token", "api", "url"]):
            msg = self._url_rx.sub("[URL_MASKED]", msg)

        # The record is now a fully sanitized plain string; clear args so the
        # original secret cannot be interpolated again by the formatter.
        record.msg = msg
        record.args = ()
        return True

security_extension = LogSecurityExtension()
logger.addFilter(security_extension)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(security_extension)
logger.info(security_extension)

client = None
CONFIG_FILE = "userbot_config.txt"
config = {
    "mine_work_chat": None,
    "thx_source_chat": -1001565066632,
    "promo_source_chat": -1001565066632,
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
                elif k in ("mine_work_chat", "thx_source_chat", "promo_source_chat",
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

# Shared source chat for Thx and promo announcements. Older config files that
# do not contain the new key automatically receive the historical default.
if config.get("thx_source_chat") is None:
    config["thx_source_chat"] = -1001565066632
if config.get("promo_source_chat") is None:
    config["promo_source_chat"] = -1001565066632

STATUS_MESSAGE_LIFETIME = 180
active_tasks = {}
promo_task = None
daily_task = None
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

ask_mineevo_lock = asyncio.Lock()
promo_lock = asyncio.Lock()
# MineEVO rejects callback presses made too close together.  This limiter
# is shared by boss combat and .evo so every button press for MineEVO is separated
# by at least one second.
MINE_BUTTON_INTERVAL = 1.0
mine_button_lock = asyncio.Lock()
mine_last_button_at = 0.0


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


def _telethon_entities_to_bot_api(response):
    """Converts Telethon entities to Bot API entity dictionaries."""
    result = []
    type_map = {
        "MessageEntityBold": "bold",
        "MessageEntityItalic": "italic",
        "MessageEntityUnderline": "underline",
        "MessageEntityStrike": "strikethrough",
        "MessageEntitySpoiler": "spoiler",
        "MessageEntityCode": "code",
        "MessageEntityPre": "pre",
        "MessageEntityBlockquote": "blockquote",
        "MessageEntityUrl": "url",
        "MessageEntityEmail": "email",
        "MessageEntityTextUrl": "text_link",
        "MessageEntityMentionName": "text_link",
        "MessageEntityCustomEmoji": "custom_emoji",
    }

    for entity in response.entities or []:
        entity_type = type_map.get(type(entity).__name__)
        if not entity_type:
            continue

        item = {
            "type": entity_type,
            "offset": int(entity.offset),
            "length": int(entity.length),
        }
        if entity_type == "text_link":
            if hasattr(entity, "url"):
                item["url"] = entity.url
            else:
                item["url"] = f"tg://user?id={int(entity.user_id)}"
        elif entity_type == "custom_emoji":
            item["custom_emoji_id"] = str(entity.document_id)
        elif entity_type == "pre":
            language = getattr(entity, "language", None)
            if language:
                item["language"] = language
        result.append(item)
    return result


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

    # Pass the original text and Telegram entities separately. This is safer
    # than converting to HTML: MessageEntityCustomEmoji keeps its document_id
    # and all ordinary formatting keeps its original UTF-16 offsets.
    return {
        "text": response.raw_text or "",
        "entities": _telethon_entities_to_bot_api(response),
        "buttons": rows,
    }, callback_links


async def helper_request(path, payload):
    # Userbot and Helper are now in one process. No public HTTP hop is used.
    if path == "/helper/prepare":
        return await helper_bot.prepare_helper(payload)
    if path == "/helper/update":
        return await helper_bot.update_helper(payload)
    raise RuntimeError(f"Неизвестный внутренний Helper endpoint: {path}")


def _direct_evo_buttons(response, destination_chat, destination_message_id=None):
    """Build Telethon buttons so the user account can preserve custom emoji.

    This path is used for .evo responses containing custom emoji. Unlike the
    Bot API helper path, the user account sends the message itself, so custom
    emoji are not downgraded to ordinary Unicode emoji.
    """
    rows = []
    callback_keys = []
    for row_index, row in enumerate(response.buttons or []):
        out_row = []
        for col_index, button in enumerate(row):
            data = getattr(button, "data", None)
            url = getattr(button, "url", None)
            if url:
                out_row.append(Button.url(button.text, url))
            elif data is not None:
                key = secrets.token_bytes(12)
                out_row.append(Button.inline(button.text, data=key))
                direct_evo_callbacks[key] = {
                    "source_chat": response.chat_id,
                    "source_message_id": response.id,
                    "row": row_index,
                    "col": col_index,
                    "destination_chat": destination_chat,
                    "destination_message_id": destination_message_id,
                }
                callback_keys.append(key)
        if out_row:
            rows.append(out_row)
    return rows or None, callback_keys


async def publish_evo_direct(response, destination_chat, reply_to=None):
    """Send an .evo result through the user account with original entities."""
    # First send without callback mapping; callback destinations are filled in
    # immediately after Telegram returns the message ID.
    buttons, callback_keys = _direct_evo_buttons(
        response, destination_chat, destination_message_id=None
    )
    sent = await client.send_message(
        destination_chat,
        response.raw_text or "",
        formatting_entities=response.entities or [],
        buttons=buttons,
        reply_to=reply_to,
    )
    for key in callback_keys:
        direct_evo_callbacks[key]["destination_message_id"] = sent.id
    direct_evo_messages[(sent.chat_id, sent.id)] = {
        "source_chat": response.chat_id,
        "source_message_id": response.id,
        "destination_chat": sent.chat_id,
        "destination_message_id": sent.id,
        "callback_keys": set(callback_keys),
    }
    return sent


async def ask_mineevo_evo(text, timeout=60.0):
    """Для .evo: вернуть ответ, следующий непосредственно после «Ожидайте…»."""
    if not text:
        return None
    target_chat = config["mine_work_chat"]
    if target_chat is None:
        raise RuntimeError(".work не настроен")

    async with ask_mineevo_lock:
        sent = await client.send_message(target_chat, text)
        deadline = asyncio.get_running_loop().time() + timeout
        first = None
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.20)
            messages = await client.get_messages(target_chat, limit=30)
            candidates = []
            for msg in messages:
                if msg.id <= sent.id or msg.out:
                    continue
                try:
                    sender = await msg.get_sender()
                    if sender is None or not getattr(sender, "bot", False):
                        continue
                except Exception:
                    continue
                candidates.append(msg)
            if not candidates:
                continue
            first = min(candidates, key=lambda m: m.id)
            raw = re.sub(r"\s+", " ", (first.raw_text or "").strip()).lower()
            if raw in {"ожидайте", "ожидайте...", "ожидайте…"}:
                # После промежуточного «Ожидайте…» принимаем только
                # непосредственно следующее сообщение MineEVO.
                while asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(0.20)
                    messages = await client.get_messages(target_chat, limit=30)
                    next_messages = []
                    for msg in messages:
                        if msg.id <= first.id or msg.out:
                            continue
                        try:
                            sender = await msg.get_sender()
                            if sender is None or not getattr(sender, "bot", False):
                                continue
                        except Exception:
                            continue
                        next_messages.append(msg)
                    if next_messages:
                        return min(next_messages, key=lambda m: m.id)
                return None
            return first
    return None


async def update_evo_waiting_message(waiting_message, response):
    """Превратить уже отправленное «Ожидайте…» в итог MineEVO."""
    buttons, callback_keys = _direct_evo_buttons(
        response, waiting_message.chat_id, waiting_message.id
    )

    # Удаляем старые callback-связи, если сообщение уже использовалось.
    old = direct_evo_messages.get((waiting_message.chat_id, waiting_message.id), {})
    for key in old.get("callback_keys", set()):
        direct_evo_callbacks.pop(key, None)

    edit_kwargs = {
        "formatting_entities": response.entities or [],
        "buttons": buttons,
    }
    if response.media is not None:
        edit_kwargs["file"] = response.media

    await client.edit_message(
        waiting_message.chat_id,
        waiting_message.id,
        response.raw_text or "",
        **edit_kwargs,
    )

    for key in callback_keys:
        direct_evo_callbacks[key]["destination_message_id"] = waiting_message.id

    direct_evo_messages[(waiting_message.chat_id, waiting_message.id)] = {
        "source_chat": response.chat_id,
        "source_message_id": response.id,
        "destination_chat": waiting_message.chat_id,
        "destination_message_id": waiting_message.id,
        "callback_keys": set(callback_keys),
    }
    return waiting_message


async def _refresh_direct_evo_message(link):
    source = await client.get_messages(link["source_chat"], ids=link["source_message_id"])
    if not source:
        raise RuntimeError("Исходное сообщение MineEVO не найдено")

    old = direct_evo_messages.get(
        (link["destination_chat"], link["destination_message_id"]), {}
    )
    for key in old.get("callback_keys", set()):
        direct_evo_callbacks.pop(key, None)

    buttons, callback_keys = _direct_evo_buttons(
        source, link["destination_chat"], link["destination_message_id"]
    )
    await client.edit_message(
        link["destination_chat"],
        link["destination_message_id"],
        source.raw_text or "",
        formatting_entities=source.entities or [],
        buttons=buttons,
    )
    link["callback_keys"] = set(callback_keys)
    direct_evo_messages[(link["destination_chat"], link["destination_message_id"])] = link
    return source


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
        "entities": data["entities"],
        "buttons": data["buttons"],
        "inline_message_id": inline_message_id,
    })
    for callback_id, new_link in callback_links.items():
        mine_callback_links[callback_id] = {
            **new_link, "helper_token": token
        }


async def _mine_click_with_limit(message, row, col):
    """Нажимает кнопку MineEVO не чаще одного раза в секунду."""
    global mine_last_button_at
    async with mine_button_lock:
        loop = asyncio.get_running_loop()
        wait = MINE_BUTTON_INTERVAL - (loop.time() - mine_last_button_at)
        if wait > 0:
            logger.info("[MINE] Жду %.2f сек. перед следующим нажатием кнопки", wait)
            await asyncio.sleep(wait)
        result = await message.click(row, col)
        mine_last_button_at = loop.time()
        return result


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
        await _mine_click_with_limit(source, link["row"], link["col"])

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


async def ask_mineevo(text, timeout=5.0, internal=False, chat_id=None):
    """Отправляет запрос MineEVO и ждёт именно его ответ.

    chat_id позволяет тем же механизмом работать как в рабочей группе,
    так и в личке MineEVO во время боя.
    """
    if not text:
        return None
    target_chat = config["mine_work_chat"] if chat_id is None else chat_id
    if target_chat is None:
        raise RuntimeError(".work не настроен")

    async with ask_mineevo_lock:
        sent = await client.send_message(target_chat, text)
        logger.info("[MINE] отправлено: %r (chat=%s, message_id=%s)", text, target_chat, sent.id)
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.20)
            messages = await client.get_messages(target_chat, limit=30)
            after = []
            for msg in messages:
                if msg.id <= sent.id or msg.out:
                    continue
                try:
                    sender = await msg.get_sender()
                    if sender is None or not getattr(sender, "bot", False):
                        continue
                except Exception:
                    continue
                after.append(msg)

            if not after:
                continue

            # Самый надёжный вариант — ответ MineEVO с reply_to на наш запрос.
            for msg in after:
                reply = getattr(msg, "reply_to", None)
                reply_id = getattr(reply, "reply_to_msg_id", None)
                if reply_id == sent.id:
                    return msg

            # Fallback для MineEVO, который не использует reply_to: берём
            # самое свежее сообщение бота после нашего запроса.
            return max(after, key=lambda m: m.id)

    raise TimeoutError(f"MineEVO не ответил в течение {timeout:g} секунд")


def parse_promo_codes(text):
    """Достаёт промокоды из ответа MineEVO.

    MineEVO может показывать коды отдельными строками, через запятые или
    прямо после слова «Промокод». Код не должен содержать пробелы, поэтому
    собираем только токены без кириллических букв.
    """
    if not text:
        return set()

    codes = set()
    code_rx = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+\-!?=./:]*$")
    explicit_rx = re.compile(
        r"(?:промокод|промо-код)\s*[:#\-]?\s*([A-Za-z0-9][A-Za-z0-9_+\-!?=./:]*)",
        re.IGNORECASE,
    )

    # Самый надёжный вариант — явное «Промокод CODE».
    for match in explicit_rx.finditer(text or ""):
        codes.add(match.group(1))

    lines = (text or "").splitlines()
    header_index = next(
        (i for i, line in enumerate(lines)
         if "действующие промокоды" in line.lower()
         or "активные промокоды" in line.lower()),
        None,
    )

    if header_index is None:
        return codes

    # Иногда MineEVO помещает коды прямо в ту же строку, что и заголовок.
    header_tail = re.split(r":", lines[header_index], maxsplit=1)[1] if ":" in lines[header_index] else ""
    if header_tail:
        for token in re.split(r"[,;|\s]+", header_tail):
            token = token.strip("()[]{}<>\"'`.,;:—–")
            if code_rx.fullmatch(token):
                codes.add(token)

    for raw_line in lines[header_index + 1:]:
        line = raw_line.strip()
        if not line:
            continue

        # Убираем типичные маркеры списка и Telegram code/backtick-обёртку.
        line = re.sub(r"^[-•*·—]\s*", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        line = line.replace("`", "").strip()

        # Если строка состоит из нескольких кодов, поддерживаем запятую,
        # точку с запятой и вертикальную черту как разделители.
        parts = re.split(r"[,;|]+", line)
        found_on_line = False
        for part in parts:
            part = part.strip()
            if not part:
                continue
            for token in part.split():
                token = token.strip("()[]{}<>\"'`.,;:—–")
                if code_rx.fullmatch(token):
                    codes.add(token)
                    found_on_line = True

        # Русский текст без кодов означает начало следующего блока ответа.
        if not found_on_line and re.search(r"[А-Яа-яЁё]", line):
            break

    return codes


def promo_is_activated(text, code):
    """Считает код активированным по подтверждению MineEVO."""
    if not text:
        return False
    return f"🎉 Промокод {code} активирован" in text


async def promo_send_and_wait(code, timeout=15.0):
    """Отправляет «промо CODE» обычным текстом и ждёт ответ MineEVO.

    Используется общий ask_mineevo(), поэтому промо не перехватывает ответы
    других автоматизаций MineEVO и наоборот.
    """
    text = f"промо {code}"
    response = await ask_mineevo(text, timeout=timeout)
    logger.info(
        "[PROMO] отправлено обычным текстом в Work: %r; ответ получен=%s",
        text, bool(response),
    )
    return response


async def promo_activate_code(code, attempts=3):
    """Отправляет промо-код обычным текстом и ждёт ответ MineEVO."""
    async with promo_lock:
        for attempt in range(1, attempts + 1):
            if config["mine_work_chat"] is None:
                return False, ""
            try:
                response = await promo_send_and_wait(code, timeout=15.0)
                promo_text = (response.text or "").strip() if response else ""
                logger.info("[PROMO] код %r: ответ MineEVO: %r", code, promo_text)
                if promo_is_activated(promo_text, code):
                    return True, promo_text
                logger.info(
                    "[PROMO] код %r: попытка %d/%d не подтверждена",
                    code, attempt, attempts,
                )
            except Exception as exc:
                logger.warning(
                    "[PROMO] код %r: ошибка попытки %d/%d: %s",
                    code, attempt, attempts, exc,
                )
            if attempt < attempts:
                await asyncio.sleep(1)
    return False, ""


async def promo_activate_from_source(code):
    """Активирует код из исходного чата, если его ещё нет в promo_seen."""
    code = (code or "").strip()
    if not code or config["mine_work_chat"] is None:
        return

    seen = {
        x.strip() for x in config.get("promo_seen", "").split(",") if x.strip()
    }
    if code in seen:
        logger.info("[PROMO] код %r уже есть в promo_seen", code)
        return

    logger.info("[PROMO] найден новый код в исходном чате: %r", code)
    ok, _ = await promo_activate_code(code)
    if ok:
        seen.add(code)
        config["promo_seen"] = ",".join(sorted(seen))
        save_config()
        logger.info("[PROMO] код %r успешно активирован из исходного чата", code)


async def daily_work_loop():
    """Каждые 24 часа отправляет два отдельных сообщения в Work."""
    while True:
        try:
            if config["mine_work_chat"] is not None:
                await client.send_message(config["mine_work_chat"], "Ежедневный бонус")
                await client.send_message(config["mine_work_chat"], "Сорвать бананы")
                logger.info("[DAILY] Отправлены «Ежедневный бонус» и «Сорвать бананы»")
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка ежедневного цикла")
            await asyncio.sleep(60)


async def promo_loop():
    while True:
        try:
            if config["mine_work_chat"] is not None:
                try:
                    response = await ask_mineevo("промо", timeout=10.0)
                except Exception as exc:
                    logger.warning("[PROMO] Не удалось получить список промокодов: %s", exc)
                    response = None

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

                    new_codes = sorted(codes - seen)
                    logger.info("[PROMO] найдено новых кодов: %d: %s", len(new_codes), new_codes)
                    for code in new_codes:
                        logger.info("[PROMO] активирую код %r", code)
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
                            # Не добавляем неактивированный/истёкший код в promo_seen.
                            # Он будет проверен снова при следующем списке действующих кодов.
                            logger.info(
                                "[PROMO] код %r не активирован; в promo_seen не добавлен",
                                code,
                            )

            await asyncio.sleep(300)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка автоматической проверки промокодов")
            await asyncio.sleep(60)


THX_TRIGGER = "активировал(а) бустер!"


async def send_thx():
    try:
        sent = await client.send_message(THX_BOT, "Thx")
        await schedule_mineevo_delete(sent, 30)
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


async def lm_get_max_transfer(job, retries=3):
    """Получить актуальный максимум перед переводами игроку.

    Проверка выполняется через общий ask_mineevo(), чтобы запрос максимума
    не пересекался с другими запросами MineEVO и не забирал чужой ответ.
    При временной ошибке запрос повторяется несколько раз.
    """
    work_chat = job["work_chat"]
    for attempt in range(1, retries + 1):
        try:
            response = await ask_mineevo(
                f"Перевести {job['nick']} {LM_PROBE_SUM}",
                timeout=15.0,
                internal=True,
                chat_id=work_chat,
            )
            amount = parse_max_transfer(response.raw_text or "")
            if amount:
                return amount
            logger.warning(
                "Не удалось определить максимум для LM игрока %s "
                "(попытка %s/%s): %r",
                job["nick"], attempt, retries, response.raw_text,
            )
        except Exception:
            logger.exception(
                "Ошибка проверки максимума LM для %s (попытка %s/%s)",
                job["nick"], attempt, retries,
            )
        if attempt < retries:
            await asyncio.sleep(1.5)
    return None


async def lm_transfer_one(job):
    """Проверить максимум заново и выполнить переводы одного игрока."""
    global lm_state, lm_last_send_at

    work_chat = job["work_chat"]

    # Каждый запуск следующего игрока ОБЯЗАТЕЛЬНО начинается с новой
    # проверки максимума. Нельзя использовать максимум предыдущего игрока.
    amount = await lm_get_max_transfer(job)
    if not amount:
        job["error"] = True
        return False

    job["amount"] = amount
    if job.get("remaining") is None:
        job["remaining"] = job["total"]
    job["error"] = False

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

        # Глобальный интервал сохраняется и после ошибки/перезапуска задачи.
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
        try:
            ok = await lm_transfer_one(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Неожиданная ошибка очереди LM для %s", job.get("nick"))
            job["error"] = True
            ok = False

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
            # Ошибка НЕ удаляет задачу. Возвращаем её в конец очереди, чтобы
            # сначала могли продолжить другие игроки, а при следующем заходе
            # максимум будет запрошен заново. Это особенно важно после
            # завершения первого игрока: следующий всегда начинает с probe.
            if not job.get("paused"):
                lm_queue.append(job)
                logger.warning(
                    "Перевод игроку %s временно не выполнен; задача возвращена "
                    "в очередь для повторной проверки максимума.",
                    job.get("nick"),
                )
            await asyncio.sleep(2)

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

    base, values = build_base_rates(template_text)
    if base is None or not values:
        return None

    def rate(a, b):
        if a == b:
            return 1.0
        if a not in values or b not in values or values[b] == 0:
            return None
        return values[a] / values[b]

    target = target_emojis[0]
    tc_order = [
        "✉️", "🧧", "📦", "🗳️", "🕋", "💎", "🎲", "🌌",
        "💼", "👜", "🧳", "🧰", "👝", "🥡", "🥚", "🎫",
        "💳", "🎇", "🪅",
    ]

    if len(target_emojis) == 1:
        parts = [f"{target} Текущий курс:", ""]
        for currency in tc_order:
            a_to_b = rate(currency, target)
            b_to_a = rate(target, currency)
            if a_to_b is None or b_to_a is None:
                continue
            parts.append(
                f"{format_quantity(quantity)} {currency} = "
                f"{format_tc_number(a_to_b * quantity)} {target}"
            )
            parts.append(
                f"{format_quantity(quantity)} {target} = "
                f"{format_tc_number(b_to_a * quantity)} {currency}"
            )
            parts.append("")
        return "\n".join(parts).rstrip()

    a, b = target_emojis[:2]
    a_to_b = rate(a, b)
    b_to_a = rate(b, a)
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



# ---------- Боссы MineEVO: таймеры + ручной выбор ----------

BO_HP_REFRESH_THRESHOLD = 100
BO_INITIAL_HITS = 10
BO_WAIT_TIMEOUT = 10
BO_STATE_TIMEOUT = 5

BO_TIME_RE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>h|hr|hrs|hour|hours|ч|час|часа|часов|min|mins|minute|minutes|мин|минута|минуты|минут|sec|secs|second|seconds|с|сек|секунда|секунды|секунд)",
    re.IGNORECASE,
)
BO_CLOCK_RE = re.compile(r"(?<!\d)(?P<h>\d{1,3}):(?P<m>\d{1,2})(?::(?P<s>\d{1,2}))?(?!\d)")
BO_HP_RE = re.compile(r"❤\s*Босс\s*:\s*([\d\s.,]+)\s*/\s*([\d\s.,]+)\s*ОЗ", re.IGNORECASE)

BOSS_EMOJIS = {
    "Элементаль Воздуха": "🌬", "Алая Фея": "🧚‍♀️", "Король Мёртвых": "🤴🏼",
    "Лесной Тролль": "🧌", "Каменный Голем": "🗿️", "Эльфийский Лучник": "🧝🏼‍♂️",
    "Некромант": "💀", "Тёмная Колдунья": "🧙🏼‍♀️", "Меха-Раптор": "🦖",
    "Мертвяк": "🧟‍♂️", "Джин": "🧞‍♂️", "Феникс": "🐦‍🔥", "Безобидная Кобра": "🐍",
    "Адская Птице-мышь": "🦇", "Огненный Бес": "👺", "Призматический Скакун": "🦄",
    "Механический Червь": "🐛", "Люцифер": "👹", "Паукобот": "🕷", "Криобот": "🤖",
    "Золотой Дракон": "🐲", "Виверна": "🐉", "Дикий Ящер": "🦎", "Полтергейст": "👻",
    "Пришелец": "👽", "Космический Странник": "👾",
}
BOSS_NAMES = list(BOSS_EMOJIS)

boss_timer_task = None
boss_timer_stop_event = None
boss_timer_options = []
boss_selected_task = None
boss_selected_stop_event = None


def bo_parse_number(value):
    value = (value or "").replace(" ", "")
    if "," in value and "." in value:
        value = value.replace(",", "")
    elif "," in value:
        tail = value.rsplit(",", 1)[1]
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
    text = text or ""
    clock = BO_CLOCK_RE.search(text)
    if clock:
        return int(clock.group("h"))*3600 + int(clock.group("m"))*60 + int(clock.group("s") or 0)
    units = {"h":3600,"hr":3600,"hrs":3600,"hour":3600,"hours":3600,"ч":3600,"час":3600,"часа":3600,"часов":3600,
             "min":60,"mins":60,"minute":60,"minutes":60,"мин":60,"минута":60,"минуты":60,"минут":60,
             "sec":1,"secs":1,"second":1,"seconds":1,"с":1,"сек":1,"секунда":1,"секунды":1,"секунд":1}
    total=0.0; found=False
    for m in BO_TIME_RE.finditer(text):
        found=True; total += float(m.group("value").replace(",", "."))*units[m.group("unit").lower()]
    return total if found else None


def bo_is_rate_limit_alert(text):
    text=(text or "").lower()
    return "слишком быстро" in text or "не так быстро" in text or ("подожди" in text and "сек" in text)


def bo_is_battle(text):
    text=(text or "").lower().replace("️", "")
    return "босс" in text and "оз" in text and "атак" in text


def bo_is_victory(text):
    text=(text or "").lower().replace("️", "")
    return "босс" in text and "повержен!" in text


def bo_find_button(message, exact_text):
    if not message or not message.buttons: return None
    for r,row in enumerate(message.buttons):
        for c,b in enumerate(row):
            if (b.text or "").strip()==exact_text: return r,c,b
    return None


def bo_find_button_contains(message, text):
    if not message or not message.buttons: return None
    wanted=text.lower()
    for r,row in enumerate(message.buttons):
        for c,b in enumerate(row):
            if wanted in (b.text or "").lower(): return r,c,b
    return None

async def bo_click(message,row,col):
    answer=await _mine_click_with_limit(message,row,col)
    return answer, str(getattr(answer,"message",None) or getattr(answer,"alert",None) or getattr(answer,"text",None) or "")

async def bo_wait_after_action(chat_id,message_id,before_text,before_buttons,predicate,timeout=BO_STATE_TIMEOUT):
    loop=asyncio.get_running_loop(); future=loop.create_future()
    def changed(m):
        if not m:return False
        return m.id!=message_id or (m.raw_text or "")!=before_text or repr(m.buttons)!=before_buttons
    async def handler(event):
        m=event.message
        if not future.done() and changed(m) and predicate(m): future.set_result(m)
    client.add_event_handler(handler,events.NewMessage(chats=chat_id)); client.add_event_handler(handler,events.MessageEdited(chats=chat_id))
    try:
        cur=await client.get_messages(chat_id,ids=message_id)
        if cur and changed(cur) and predicate(cur): return cur
        try:return await asyncio.wait_for(future,timeout=timeout)
        except asyncio.TimeoutError:return None
    finally:
        client.remove_event_handler(handler,events.NewMessage(chats=chat_id)); client.remove_event_handler(handler,events.MessageEdited(chats=chat_id))

async def bo_wait_new_message(chat_id,after_id,timeout=BO_STATE_TIMEOUT):
    loop=asyncio.get_running_loop(); future=loop.create_future()
    async def handler(event):
        m=event.message
        if not future.done() and m and m.id>after_id and not m.out: future.set_result(m)
    client.add_event_handler(handler,events.NewMessage(chats=chat_id))
    try:
        for m in await client.get_messages(chat_id,limit=10):
            if m.id>after_id and not m.out:return m
        try:return await asyncio.wait_for(future,timeout=timeout)
        except asyncio.TimeoutError:return None
    finally: client.remove_event_handler(handler,events.NewMessage(chats=chat_id))

async def bo_wait_seconds(seconds):
    if seconds > 0:
        await asyncio.sleep(seconds)

async def bo_get_private_chat():
    return await client.get_entity(THX_BOT)

async def schedule_mineevo_delete(message, delay=30):
    if not message:return
    async def worker():
        await asyncio.sleep(delay)
        try: await client.delete_messages(message.chat_id,message.id)
        except Exception: pass
    asyncio.create_task(worker())

async def send_boss_notification(name):
    emoji=BOSS_EMOJIS.get(name,"👹")
    buttons=[
        Button.url("🔗 Открыть босса","https://t.me/mineevo?text=%D0%B1%D0%BE"),
        Button.url("🔗 Открыть клан","https://t.me/mineevo?text=%D0%BA%D0%BB%D0%B0%D0%BD"),
        Button.url("🔗 Надеть экипировку","https://t.me/mineevo?text=%D1%8D%D0%BA%D0%B8%D0%BF"),
    ]
    if config.get("mine_work_chat"):
        await client.send_message(config["mine_work_chat"],f"{emoji} <b>{name}</b>",buttons=buttons)

async def bo_open_selected_boss(name):
    private=await bo_get_private_chat()
    sent=await client.send_message(private,"бо")
    await schedule_mineevo_delete(sent)
    # Wait for MineEVO's menu response.
    menu=None
    for _ in range(50):
        await asyncio.sleep(0.2)
        msgs=await client.get_messages(private,limit=20)
        for m in msgs:
            if m.id>sent.id and not m.out and (m.buttons or "босс" in (m.raw_text or "").lower()):
                menu=m; break
        if menu: break
    if not menu: raise RuntimeError("MineEVO не прислал меню выбранного босса.")
    button=bo_find_button(menu,name) or bo_find_button_contains(menu,name)
    if not button: raise RuntimeError(f"Кнопка выбранного босса «{name}» не найдена.")
    before_text=menu.raw_text or ""; before_buttons=repr(menu.buttons)
    await bo_click(menu,button[0],button[1])
    battle=await bo_wait_after_action(private.id,menu.id,before_text,before_buttons,lambda m: bo_is_battle(m.raw_text or "") or bo_find_button_contains(m,"атаковать") is not None,timeout=BO_STATE_TIMEOUT)
    if not battle: battle=await bo_wait_new_message(private.id,menu.id,BO_STATE_TIMEOUT)
    if not battle: raise RuntimeError("Бой выбранного босса не открылся в личке MineEVO.")
    return battle

async def bo_fight(battle):
    """Проводит бой в личке MineEVO.

    Первые 10 ударов выполняются последовательно. После этого бот не
    спамит атаками: обновляет состояние боя и ждёт, пока HP босса станет
    небольшим, затем добивает его обычной атакой.
    """
    current = battle
    chat_id = battle.chat_id
    attack_count = 0

    while not boss_selected_stop_event.is_set():
        current = await bo_get_fresh_message(chat_id, current.id) or current
        text = current.raw_text or ""

        if bo_is_victory(text):
            return current

        attack = bo_find_button_contains(current, "атаковать")
        if not attack:
            await asyncio.sleep(0.5)
            current = await bo_get_fresh_message(chat_id, current.id) or current
            text = current.raw_text or ""
            if bo_is_victory(text):
                return current
            attack = bo_find_button_contains(current, "атаковать")

        hp = bo_parse_hp(text)

        # После первых 10 ударов только обновляем бой, пока HP не станет
        # маленьким. Кнопка «Обновить» тоже проходит общий лимит 1 сек.
        if attack_count >= BO_INITIAL_HITS and hp is not None and hp > BO_HP_REFRESH_THRESHOLD:
            refresh = bo_find_button_contains(current, "обнов")
            if refresh:
                before_text = current.raw_text or ""
                before_buttons = repr(current.buttons)
                _, alert_text = await bo_click(current, refresh[0], refresh[1])
                wait_seconds = bo_extract_wait_seconds(alert_text)
                if wait_seconds is not None and wait_seconds > 0:
                    await bo_wait_seconds(wait_seconds)
                    continue

                updated = await bo_wait_after_action(
                    chat_id, current.id, before_text, before_buttons,
                    lambda m: bo_is_battle(m.raw_text or "")
                    or bo_is_victory(m.raw_text or "")
                    or bo_find_button_contains(m, "атаковать") is not None,
                    timeout=BO_STATE_TIMEOUT,
                )
                if updated:
                    current = updated
                    continue

                refreshed = await bo_get_fresh_message(chat_id, current.id)
                if refreshed:
                    current = refreshed
                await asyncio.sleep(0.2)
                continue

        if not attack:
            newer = await bo_wait_new_message(chat_id, current.id, timeout=1.5)
            if newer and (
                bo_is_battle(newer.raw_text or "")
                or bo_is_victory(newer.raw_text or "")
                or bo_find_button_contains(newer, "атаковать") is not None
            ):
                current = newer
                continue
            await asyncio.sleep(0.5)
            continue

        before_text = current.raw_text or ""
        before_buttons = repr(current.buttons)
        _, alert_text = await bo_click(current, attack[0], attack[1])
        if bo_is_rate_limit_alert(alert_text):
            wait_seconds = bo_extract_wait_seconds(alert_text) or MINE_BUTTON_INTERVAL
            logger.warning("[BO] Атака отклонена из-за интервала; жду %.2f сек.", wait_seconds)
            await bo_wait_seconds(wait_seconds)
            continue

        attack_count += 1
        logger.info("[BO] Удар %s/%s", min(attack_count, BO_INITIAL_HITS), BO_INITIAL_HITS)

        wait_seconds = bo_extract_wait_seconds(alert_text)
        if wait_seconds is not None and wait_seconds > 0:
            await bo_wait_seconds(wait_seconds)

        updated = await bo_wait_after_action(
            chat_id,
            current.id,
            before_text,
            before_buttons,
            lambda m: bo_is_battle(m.raw_text or "")
            or bo_is_victory(m.raw_text or "")
            or bo_find_button_contains(m, "атаковать") is not None,
            timeout=BO_STATE_TIMEOUT,
        )
        if updated:
            current = updated
            continue

        refreshed = await bo_get_fresh_message(chat_id, current.id)
        if refreshed:
            if bo_is_victory(refreshed.raw_text or ""):
                return refreshed
            current = refreshed
            continue

        newer = await bo_wait_new_message(chat_id, current.id, timeout=1.5)
        if newer and (
            bo_is_battle(newer.raw_text or "")
            or bo_is_victory(newer.raw_text or "")
            or bo_find_button_contains(newer, "атаковать") is not None
        ):
            current = newer
            continue

        await asyncio.sleep(0.5)

    raise asyncio.CancelledError




async def bo_reward_and_return(victory):
    if boss_timer_stop_event and boss_timer_stop_event.is_set(): raise asyncio.CancelledError
    # Победа определяется только по «⚔️ Босс ... повержен!». Сначала «Получить».
    if not bo_is_victory(victory.raw_text or ""):
        fresh=await client.get_messages(victory.chat_id,ids=victory.id)
        if fresh: victory=fresh
    reward=bo_find_button_contains(victory,"🎉 получить") or bo_find_button_contains(victory,"получить")
    if not reward: raise RuntimeError("Кнопка «🎉 Получить» не найдена.")
    before_text=victory.raw_text or ""; before_buttons=repr(victory.buttons)
    await bo_click(victory,reward[0],reward[1])
    reward_message=await bo_wait_after_action(victory.chat_id,victory.id,before_text,before_buttons,lambda m:"🎉 награда получена:" in (m.raw_text or "").lower() or "награда получена:" in (m.raw_text or "").lower(),timeout=BO_STATE_TIMEOUT)
    if not reward_message: reward_message=await client.get_messages(victory.chat_id,ids=victory.id)
    if not reward_message or "награда получена:" not in (reward_message.raw_text or "").lower():
        raise RuntimeError("MineEVO не подтвердил получение награды.")
    # После награды используется единственная кнопка «К боссам».
    back=bo_find_button_contains(reward_message,"к боссам")
    if not back: raise RuntimeError("Кнопка «К боссам» не найдена.")
    await bo_click(reward_message,back[0],back[1])
    await schedule_mineevo_delete(reward_message)
    return reward_message


def bo_boss_name_from_button(text):
    raw=(text or "").strip()
    for name in BOSS_NAMES:
        if name.lower() in raw.lower(): return name
    # Если MineEVO использует только эмодзи/номер, сохраняем текст кнопки.
    clean=re.sub(r"\s*(?:\d+[.:)]?\s*)?(?:\d+[hчмс:\s].*)?$","",raw,flags=re.I).strip()
    return clean or raw


def collect_boss_timer_options(menu):
    options=[]
    if not menu or not menu.buttons:return options
    number=1
    for row in menu.buttons:
        for button in row:
            text=button.text or ""
            if not getattr(button,"data",None): continue
            wait=bo_parse_wait_time(text) or 0
            name=bo_boss_name_from_button(text)
            options.append({"number":number,"name":name,"button_text":text,"wait":wait})
            number+=1
    options.sort(key=lambda x:x["wait"])
    for i,opt in enumerate(options,1): opt["number"]=i
    return options

async def bo_get_boss_menu(chat_id):
    sent=await client.send_message(chat_id,"бо")
    await schedule_mineevo_delete(sent)
    deadline=asyncio.get_running_loop().time()+BO_WAIT_TIMEOUT
    while asyncio.get_running_loop().time()<deadline:
        await asyncio.sleep(.2)
        msgs=await client.get_messages(chat_id,limit=20)
        for m in msgs:
            if m.id>sent.id and not m.out and m.buttons:
                return m
    raise TimeoutError("MineEVO не прислал список боссов.")

async def botimers_collect(work_chat):
    """Собирает только уже показанные MineEVO таймеры, ничего не нажимая."""
    global boss_timer_options
    found={}
    while boss_timer_stop_event and not boss_timer_stop_event.is_set():
        try:
            messages=await client.get_messages(work_chat,limit=20)
            now=asyncio.get_running_loop().time()
            for m in messages:
                text=m.raw_text or ""
                if not m.buttons and "босс" not in text.lower():
                    continue
                if m.buttons:
                    for row in m.buttons:
                        for button in row:
                            if not getattr(button,"data",None): continue
                            btext=button.text or ""
                            name=bo_boss_name_from_button(btext)
                            if not name or len(name)<2: continue
                            # Только уже отображённый таймер/готовность. Никаких callback-кликов.
                            wait=bo_parse_wait_time(btext)
                            if wait is None:
                                wait=0
                            found[name]={"name":name,"button_text":btext,"expires_at":now+wait}
                # Если MineEVO показал таймер в самом тексте, тоже сохраняем его.
                if "босс" in text.lower():
                    wait=bo_parse_wait_time(text)
                    if wait is not None:
                        for name in BOSS_NAMES:
                            if name.lower() in text.lower():
                                found[name]={"name":name,"button_text":name,"expires_at":now+wait}
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка сбора таймеров боссов")
        await asyncio.sleep(0.5)
    boss_timer_options=[]
    now=asyncio.get_running_loop().time()
    for name,item in found.items():
        item["wait"]=max(0.0,item["expires_at"]-now)
        boss_timer_options.append(item)
    boss_timer_options.sort(key=lambda x:x["wait"])
    for i,item in enumerate(boss_timer_options,1): item["number"]=i

async def botimers_start(work_chat):
    global boss_timer_task
    # Открываем меню один раз. Автоматических нажатий по боссам нет.
    sent=await client.send_message(work_chat,"бо")
    await schedule_mineevo_delete(sent)
    boss_timer_task=asyncio.create_task(botimers_collect(work_chat))
    await asyncio.sleep(0.5)

async def run_selected_boss(option):
    global boss_selected_task, boss_selected_stop_event
    boss_selected_stop_event = asyncio.Event()
    await send_boss_notification(option["name"])
    await bo_wait_seconds(option["wait"])
    battle=await bo_open_selected_boss(option["name"])
    victory=await bo_fight(battle)
    await bo_reward_and_return(victory)
    if config.get("mine_work_chat"):
        await client.send_message(config["mine_work_chat"], "✅ Бой завершён. Для нового выбора используйте <code>.botimers</code>.")

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

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.botimers$"))
    async def botimers_handler(event):
        global boss_timer_task, boss_timer_stop_event, boss_timer_options
        if config["mine_work_chat"] is None:
            return await answer_and_delete(event,"⚠️ Сначала подключите рабочую группу MineEVO командой <code>.work</code>.")
        if boss_timer_task and not boss_timer_task.done():
            return await answer_and_delete(event,"⚠️ Сбор таймеров уже запущен. Используйте <code>.botimersstop</code>.")
        boss_timer_stop_event=asyncio.Event(); boss_timer_options=[]
        await event.delete()
        try:
            await botimers_start(config["mine_work_chat"])
        except Exception as exc:
            if boss_timer_task: boss_timer_task.cancel()
            boss_timer_task=None; boss_timer_stop_event=None
            await client.send_message(config["mine_work_chat"],f"⚠️ Не удалось начать сбор таймеров: <code>{type(exc).__name__}</code>")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.botimersstop$"))
    async def botimersstop_handler(event):
        global boss_timer_task, boss_timer_stop_event
        if not boss_timer_task or boss_timer_task.done():
            return await answer_and_delete(event,"ℹ️ Сбор таймеров сейчас не запущен.")
        boss_timer_stop_event.set()
        try: await boss_timer_task
        except asyncio.CancelledError: pass
        boss_timer_task=None; boss_timer_stop_event=None
        if not boss_timer_options:
            return await answer_and_delete(event,"⚠️ Таймеры боссов не найдены.")
        lines=["⏱ <b>Найденные таймеры боссов:</b>"]
        for x in boss_timer_options:
            left=max(0,int(x["wait"])); h=left//3600; m=(left%3600)//60; sec=left%60
            timer=f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
            lines.append(f"<b>{x['number']}.</b> {BOSS_EMOJIS.get(x['name'],'')} {x['name']} — <code>{timer}</code>")
        await event.edit("\n".join(lines)+"\n\nОтправьте номер босса для выбора.")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^(\d+)$"))
    async def boss_number_handler(event):
        global boss_selected_task, boss_timer_options
        if not boss_timer_options: return
        option=next((x for x in boss_timer_options if x["number"]==int(event.pattern_match.group(1))),None)
        if not option: return
        boss_timer_options=[]
        await event.delete()
        if boss_selected_task and not boss_selected_task.done():
            return
        boss_selected_task=asyncio.create_task(run_selected_boss(option))

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.(?:thxsource|promosource)$"))
    async def source_handler(event):
        config["thx_source_chat"] = event.chat_id
        config["promo_source_chat"] = event.chat_id
        config["thx_enabled"] = True
        save_config()
        msg = await event.edit(
            "✅ <b>Источник Thx и промокодов подключён.</b>\n"
            "Этот чат теперь используется для Thx и поиска новых промокодов."
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

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lchk(?:\s+(\S+))?$"))
    async def lchk_handler(event):
        nick = event.pattern_match.group(1)
        if not nick:
            return await answer_and_delete(
                event, "🔎 <b>Использование:</b> <code>.lchk [ник]</code>"
            )
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
            reply_to = event.reply_to_msg_id if event.is_reply else None
            waiting = await client.send_message(
                event.chat_id,
                "Ожидайте…",
                reply_to=reply_to,
            )
            response = await ask_mineevo_evo(args)
            if response is None:
                await client.edit_message(event.chat_id, waiting.id, "⚠️ MineEVO не ответил.")
                return await event.delete()

            await update_evo_waiting_message(waiting, response)
            await event.delete()
        except Exception:
            logger.exception("Ошибка .evo")
            try:
                await event.edit("⚠️ <b>Не удалось получить ответ MineEVO.</b>")
            except Exception:
                pass

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
        outgoing=True,
        pattern=r"^\.tc(?:\s+(\S+)(?:\s+(\d+(?:[.,]\d+)?))?(?:\s+(\S+))?)?$"
    ))
    async def tc_handler(event):
        currency = (event.pattern_match.group(1) or "").strip()
        quantity_raw = (event.pattern_match.group(2) or "1").replace(",", ".")
        target_currency = (event.pattern_match.group(3) or "").strip()

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

            targets = [currency]
            if target_currency:
                targets.append(target_currency)

            result = make_tc_output(
                template.raw_text,
                targets,
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
        direct_link = direct_evo_messages.get(key)
        if direct_link:
            source_key = (direct_link["source_chat"], direct_link["source_message_id"])
            lock = mine_callback_locks.setdefault(source_key, asyncio.Lock())
            async with lock:
                before = await client.get_messages(
                    direct_link["source_chat"], ids=direct_link["source_message_id"]
                )
                before_text = before.raw_text if before else ""
                before_buttons = repr(before.buttons) if before else ""
                await client.send_message(
                    direct_link["source_chat"],
                    event.raw_text,
                    reply_to=direct_link["source_message_id"],
                )
                updated = None
                for _ in range(20):
                    await asyncio.sleep(0.1)
                    candidate = await client.get_messages(
                        direct_link["source_chat"], ids=direct_link["source_message_id"]
                    )
                    if not candidate:
                        continue
                    updated = candidate
                    if ((candidate.raw_text or "") != before_text or
                            repr(candidate.buttons) != before_buttons):
                        break
                if updated:
                    await _refresh_direct_evo_message(direct_link)
            return

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

    @client.on(events.CallbackQuery())
    async def direct_evo_callback_handler(event):
        key = bytes(event.data or b"")
        link = direct_evo_callbacks.get(key)
        if not link:
            return
        await event.answer()
        source_key = (link["source_chat"], link["source_message_id"])
        lock = mine_callback_locks.setdefault(source_key, asyncio.Lock())
        async with lock:
            source = await client.get_messages(
                link["source_chat"], ids=link["source_message_id"]
            )
            if not source:
                return
            row = link["row"]
            col = link["col"]
            await _mine_click_with_limit(source, row, col)
            before_text = source.raw_text or ""
            before_buttons = repr(source.buttons)
            updated = None
            for _ in range(30):
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
                await _refresh_direct_evo_message(link)

    @client.on(events.NewMessage(incoming=True))
    async def mineevo_thanks_cleanup(event):
        if event.chat_id != (await client.get_entity(THX_BOT)).id:
            return
        text = event.raw_text or ""
        if "поблагодарил(а)" in text.lower():
            await schedule_mineevo_delete(event.message, 30)

    @client.on(events.NewMessage(incoming=True))
    async def promo_source_watcher(event):
        source_chat = config.get("promo_source_chat")
        if source_chat is None or event.chat_id != source_chat:
            return

        text = event.raw_text or ""
        match = re.search(
            r"пиши\s+в\s+боте\s*:\s*промо\s+(\S+)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return

        code = match.group(1)
        asyncio.create_task(promo_activate_from_source(code))

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
    global client, promo_task, daily_task
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    client.parse_mode = "html"
    await register_handlers()
    await client.start()
    logger.info("Юзербот запущен")
    promo_task = asyncio.create_task(promo_loop())
    daily_task = asyncio.create_task(daily_work_loop())


async def shutdown():
    global promo_task, daily_task
    if promo_task:
        promo_task.cancel()
        promo_task = None
    if daily_task:
        daily_task.cancel()
        daily_task = None
    if client:
        await client.disconnect()
