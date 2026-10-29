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
import sympy as sp
from sympy.parsing.sympy_parser import (
    parse_expr, standard_transformations, implicit_multiplication_application,
    convert_xor, function_exponentiation, rationalize,
)
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
        self._token_rx = re.compile(r'\d{8,12}:[A-Za-z0-9_-]{35}')
        self._session_rx = re.compile(r'\b[14B][A-Za-z0-9_-]{100,}\b')
        self._hash_rx = re.compile(r'\b[a-fA-F0-9]{32}\b')
        self._id_rx = re.compile(r'\b\d{5,9}\b')
        self._url_rx = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+|(?:t\.me|telegram\.me)/[^\s<>"]+|(?<![@\w])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s<>"]*)?')
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

        # Keep the official public GitHub repository visible in the startup
        # notice across launcher, helper bot, and userbot logs. All other URLs
        # remain protected by the existing masking rules.
        github_link = "https://github.com/Daniil-Ky/Golden_Userbot"
        github_placeholder = "__GOLDEN_USERBOT_PUBLIC_REPOSITORY__"
        msg = msg.replace(github_link, github_placeholder)

        lower = msg.lower()
        if any(k in lower for k in ["api_id", "auth", "login", "connect"]):
            msg = self._id_rx.sub("[API_ID_HIDDEN]", msg)

        msg = self._url_rx.sub("[URL_MASKED]", msg)

        # Restore only the explicitly allowed public repository URL.
        msg = msg.replace(github_placeholder, github_link)

        record.msg = msg
        record.args = ()
        return True

security_extension = LogSecurityExtension()
logger.addFilter(security_extension)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(security_extension)

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
helper_publications = {}
# Compatibility only; .evo results now always use Helper Bot.
direct_evo_callbacks = {}
direct_evo_messages = {}

bo_task = None
bo_stop_event = None
bo_timer_watch_active = False
bo_timer_records = {}
bo_timer_selection = None
ask_mineevo_lock = asyncio.Lock()
promo_lock = asyncio.Lock()
# MineEVO rejects callback presses made too close together.  This limiter
# is shared by .bo and .evo so every button press for MineEVO is separated
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
    raw_text = response.raw_text or ""
    # Helper Bot's inline result uses Bot API HTML. Serialize Telethon entities
    # so bold/italic/links/code formatting survives instead of being discarded.
    try:
        html_text = telethon_html.unparse(raw_text, response.entities or [])
        html_text = re.sub(r"<emoji\s+id=[\"'](\d+)[\"']>", r'<tg-emoji emoji-id="\1">', html_text)
        html_text = html_text.replace("</emoji>", "</tg-emoji>")
    except Exception:
        html_text = raw_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return {
        "text": html_text,
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
    if response.media is not None:
        sent = await client.send_file(
            destination_chat, response.media,
            caption=response.raw_text or None,
            formatting_entities=response.entities or [],
            buttons=buttons, reply_to=reply_to,
        )
    else:
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


def _has_inline_image(message):
    if getattr(message, "photo", None):
        return True
    document = getattr(message, "document", None)
    return bool(document and (getattr(document, "mime_type", "") or "").startswith("image/"))


async def _upload_inline_image(token, bot_username, source_message):
    if not source_message or not _has_inline_image(source_message):
        return False
    image_bytes = await client.download_media(source_message, file=bytes)
    if not image_bytes:
        logger.warning("Не удалось загрузить изображение для inline-сообщения")
        return False
    await client.send_file(
        bot_username,
        image_bytes,
        caption=f"__golden_inline_photo__:{token}",
        force_document=False,
    )
    for _ in range(40):
        stored = helper_bot.pending.get(token, {})
        if stored.get("photo_file_id"):
            return True
        await asyncio.sleep(0.1)
    logger.warning("Helper не подтвердил загрузку изображения для inline-сообщения")
    return False


async def publish_through_helper(data, destination_chat, reply_to=None,
                                 source_link=None, media_message=None):
    result = await helper_request("/helper/prepare", data)
    token = result.get("token")
    bot_username = result.get("bot_username")
    if not token or not bot_username:
        raise RuntimeError("Helper не вернул token/bot_username")
    if media_message:
        await _upload_inline_image(token, bot_username, media_message)

    inline_results = await client.inline_query(bot_username, token)
    if not inline_results:
        raise RuntimeError("Helper не вернул Inline Result")

    sent = await inline_results[0].click(destination_chat, reply_to=reply_to)
    helper_publications[token] = {
        "destination_chat": destination_chat,
        "reply_to": reply_to,
        "sent_chat_id": sent.chat_id,
        "sent_message_id": sent.id,
        "source_link": source_link,
        "bot_username": bot_username,
    }
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


async def recover_helper_inline_message(token, replace_existing=False):
    """Re-publish a Helper inline result if its previous message disappeared."""
    publication = helper_publications.get(token)
    if not publication:
        raise RuntimeError("Не найдены данные для восстановления inline-сообщения")
    if replace_existing:
        old_chat = publication.get("sent_chat_id")
        old_message = publication.get("sent_message_id")
        if old_chat is not None and old_message is not None:
            try:
                await client.delete_messages(old_chat, old_message)
            except Exception as exc:
                logger.warning("Не удалось заменить старое inline-сообщение: %s", type(exc).__name__)
    bot_username = publication["bot_username"]
    results = await client.inline_query(bot_username, token)
    if not results:
        raise RuntimeError("Helper не вернул Inline Result при восстановлении")
    sent = await results[0].click(
        publication["destination_chat"],
        reply_to=publication.get("reply_to"),
    )
    publication["sent_chat_id"] = sent.chat_id
    publication["sent_message_id"] = sent.id
    source_link = publication.get("source_link")
    if source_link:
        inline_reply_links[(sent.chat_id, sent.id)] = {
            **source_link, "helper_token": token
        }
    return sent


async def update_helper_inline_message(response, link, inline_message_id):
    data, callback_links = _message_to_helper_data(
        response, link["destination_chat"]
    )
    token = link.get("helper_token")
    if not token:
        raise RuntimeError("У callback отсутствует helper_token")
    if not inline_message_id:
        raise RuntimeError("Telegram не передал inline_message_id")
    publication = helper_publications.get(token, {})
    bot_username = publication.get("bot_username")
    if bot_username:
        await _upload_inline_image(token, bot_username, response)

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

    if kind == "inline-recover":
        token = payload.get("token")
        if not token:
            raise ValueError("missing inline token")
        await recover_helper_inline_message(
            token, replace_existing=bool(payload.get("replace_existing"))
        )
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


async def ask_mineevo(text, timeout=30.0, internal=False, chat_id=None,
                      on_waiting=None):
    """Send a MineEVO request and wait for its actual result.

    If MineEVO first replies with "Ожидайте...", an optional callback can
    publish that interim message while this function keeps polling for the
    final response or an edit of the same message.
    """
    if not text:
        return None
    target_chat = config["mine_work_chat"] if chat_id is None else chat_id
    if target_chat is None:
        raise RuntimeError(".work не настроен")

    def is_waiting(message):
        value = (getattr(message, "raw_text", None) or "").strip().lower()
        return value.startswith("ожидайте")

    async with ask_mineevo_lock:
        sent = await client.send_message(target_chat, text)
        logger.info(
            "[MINE] запрос отправлен (chat_id=%s, message_id=%s)",
            target_chat, sent.id
        )
        deadline = asyncio.get_running_loop().time() + timeout
        first_incoming = None
        first_seen_at = None
        waiting_message_id = None
        waiting_text = None
        waiting_callback_done = False

        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.2)
            try:
                messages = await client.get_messages(target_chat, limit=100)
            except Exception as exc:
                logger.warning(
                    "[MINE] не удалось прочитать историю чата: %s",
                    type(exc).__name__
                )
                continue

            by_id = {msg.id: msg for msg in messages}
            if waiting_message_id is not None:
                current_waiting = by_id.get(waiting_message_id)
                if current_waiting:
                    current_text = current_waiting.raw_text or ""
                    if current_text.strip() != (waiting_text or "").strip() and not is_waiting(current_waiting):
                        logger.info("[MINE] промежуточное сообщение обновлено до результата")
                        return current_waiting

                later = sorted(
                    (msg for msg in messages
                     if msg.id > waiting_message_id and not msg.out
                     and not is_waiting(msg)),
                    key=lambda msg: msg.id,
                )
                if later:
                    return later[0]

            incoming = sorted(
                (msg for msg in messages if msg.id > sent.id and not msg.out),
                key=lambda msg: msg.id,
            )
            if not incoming:
                continue

            reply_candidates = []
            for msg in incoming:
                reply = getattr(msg, "reply_to", None)
                if getattr(reply, "reply_to_msg_id", None) == sent.id:
                    reply_candidates.append(msg)
            candidates = reply_candidates or incoming
            candidate = candidates[0]

            if is_waiting(candidate):
                if waiting_message_id is None:
                    waiting_message_id = candidate.id
                    waiting_text = candidate.raw_text or ""
                if on_waiting and not waiting_callback_done:
                    await on_waiting(candidate)
                    waiting_callback_done = True
                continue

            if waiting_message_id is not None:
                return candidate

            if reply_candidates:
                logger.info(
                    "[MINE] найден reply на запрос (message_id=%s)", candidate.id
                )
                return candidate

            if first_incoming is None:
                first_incoming = candidate
                first_seen_at = asyncio.get_running_loop().time()
                logger.info(
                    "[MINE] найдено обычное входящее сообщение после запроса "
                    "(message_id=%s); проверяю возможный reply",
                    first_incoming.id
                )
            if asyncio.get_running_loop().time() - first_seen_at >= 0.6:
                logger.info(
                    "[MINE] используем ближайшее входящее сообщение "
                    "без reply (message_id=%s)", first_incoming.id
                )
                return first_incoming

    raise TimeoutError(
        f"В чате MineEVO ({target_chat}) не найдено новое входящее сообщение "
        f"за {timeout:g} с после отправки запроса. "
        "Проверьте .work и убедитесь, что MineEVO отвечает в этом чате."
    )


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
    """Считает код активированным только по явному подтверждению MineEVO."""
    if not text or not code:
        return False
    normalized = re.sub(r"\s+", " ", str(text)).strip().casefold()
    escaped = re.escape(str(code).strip())
    return re.search(
        rf"🎉\s*промокод\s+{escaped}\s+активирован(?:[.!…]*)?(?:\s|$)",
        normalized, re.IGNORECASE,
    ) is not None


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


async def promo_activate_code(code, attempts=1):
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


async def lm_get_max_transfer(job, retries=3):
    """Получить актуальный максимум перед переводами игроку.

    Проверка выполняется через общий ask_mineevo(), чтобы запрос максимума
    не пересекался с другими запросами MineEVO и не забирал чужой ответ.
    При временной ошибке запрос повторяется несколько раз.
    """
    work_chat = job["work_chat"]
    for attempt in range(1, retries + 1):
        try:
            # The probe itself is a MineEVO action. Start the same global
            # 60-second cooldown here so the first real transfer is not sent
            # immediately after the maximum check.
            probe_sent_at = asyncio.get_running_loop().time()
            response = await ask_mineevo(
                f"Перевести {job['nick']} {LM_PROBE_SUM}",
                timeout=15.0,
                internal=True,
                chat_id=work_chat,
            )
            global lm_last_send_at
            lm_last_send_at = probe_sent_at
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

    # Не начинать проверку следующего игрока, пока не прошёл интервал после
    # последнего действия перевода/проверки в общей очереди.
    await lm_wait_global_slot()

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
    """Format results without turning tiny nonzero values into 0.0."""
    value = float(value)
    if not math.isfinite(value):
        return str(value)
    if value == 0:
        return "0"
    magnitude = abs(value)
    # Keep very small/large values readable and preserve significant digits.
    if magnitude < 1e-6 or magnitude >= 1e12:
        mantissa, exponent = f"{value:.10e}".split("e")
        mantissa = mantissa.rstrip("0").rstrip(".")
        return f"{mantissa}×10^{int(exponent)}"
    rendered = f"{value:.10g}"
    if "e" in rendered.lower():
        mantissa, exponent = rendered.lower().split("e")
        return f"{mantissa}×10^{int(exponent)}"
    if "." not in rendered:
        rendered += ".0"
    return rendered


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


CALC_ALLOWED = re.compile(r"^[0-9A-Za-z_+\-*/().,%\s×÷•⋅√∛^!πeE°−–—⌈⌉⌊⌋⁰¹²³⁴⁵⁶⁷⁸⁹]+$")

_CALC_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application, convert_xor,
    function_exponentiation, rationalize,
)
_CALC_FUNCTIONS = {
    "sqrt": sp.sqrt, "root": sp.root, "real_root": sp.real_root, "sign": sp.sign, "sin": sp.sin, "cos": sp.cos,
    "tan": sp.tan, "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
    "asinh": sp.asinh, "acosh": sp.acosh, "atanh": sp.atanh,
    "log": sp.log, "ln": sp.log, "exp": sp.exp, "abs": sp.Abs,
    "floor": sp.floor, "ceil": sp.ceiling, "factorial": sp.factorial,
    "min": sp.Min, "max": sp.Max,
}
_CALC_LOCALS = {**_CALC_FUNCTIONS, "pi": sp.pi, "π": sp.pi, "E": sp.E, "e": sp.E}
_CALC_GLOBALS = {
    "Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational,
    "Symbol": sp.Symbol, "Add": sp.Add, "Mul": sp.Mul, "Pow": sp.Pow,
    "factorial": sp.factorial, "real_root": sp.real_root, "Tuple": sp.Tuple,
}

_SUPERSCRIPTS = str.maketrans({"⁰":"**0", "¹":"**1", "²":"**2", "³":"**3", "⁴":"**4", "⁵":"**5", "⁶":"**6", "⁷":"**7", "⁸":"**8", "⁹":"**9"})


def _normalize_calc_input(expr):
    expr = (expr or "").strip()
    if not expr or len(expr) > 500 or not CALC_ALLOWED.fullmatch(expr):
        raise ValueError("Недопустимое выражение или слишком длинная запись")
    expr = expr.translate(_SUPERSCRIPTS)
    expr = expr.replace("−", "-").replace("–", "-").replace("—", "-")
    expr = expr.replace("×", "*").replace("⋅", "*").replace("•", "*").replace("÷", "/")
    expr = expr.replace("π", "pi").replace("°", "")
    # Scientific notation commonly generated by AI/calculators: 6.67×10^-11.
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*\*\s*10\s*\*\*\s*([+\-]?\d+)", r"(\1*10**(\2))", expr)
    # Cube roots and square roots with parenthesized or single-token arguments.
    expr = re.sub(r"∛\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)", r"sign((\1))*abs((\1))**(1/3)", expr)
    expr = re.sub(r"∛\s*([A-Za-z0-9.]+)", r"sign((\1))*abs((\1))**(1/3)", expr)
    expr = re.sub(r"√\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)", r"sqrt((\1))", expr)
    expr = re.sub(r"√\s*([A-Za-z0-9.]+)", r"sqrt(\1)", expr)
    # Treat common Unicode/ASCII variants and implicit powers consistently.
    expr = expr.replace("^", "**")
    return expr


def _parse_calc_side(expr, symbols):
    normalized = _normalize_calc_input(expr)
    local_dict = dict(_CALC_LOCALS)
    local_dict.update(symbols)
    # parse_expr is constrained to a strict mathematical character whitelist and
    # a small SymPy namespace; Python builtins and arbitrary calls are unavailable.
    return parse_expr(
        normalized, local_dict=local_dict, global_dict=_CALC_GLOBALS,
        transformations=_CALC_TRANSFORMATIONS, evaluate=True,
    )


def _calc_format(value, digits=12):
    try:
        value = sp.N(value, digits)
        if value.is_real is False:
            return str(value)
        as_float = float(value)
        if not math.isfinite(as_float):
            return str(value)
        if abs(as_float) < 1e-7 or abs(as_float) >= 1e10:
            return f"{as_float:.8g}"
        return f"{as_float:.10g}"
    except Exception:
        return str(value)


def _numeric_roots(expr, variable, lower=-1000, upper=1000, step=0.25):
    """Find real roots numerically for equations without a closed form."""
    roots = []
    try:
        fn = sp.lambdify(variable, expr, modules=["math"])
    except Exception:
        return roots

    def safe_eval(v):
        try:
            y = float(fn(v))
            return y if math.isfinite(y) else None
        except Exception:
            return None

    x0 = float(lower)
    y0 = safe_eval(x0)
    while x0 < upper:
        x1 = min(x0 + step, upper)
        y1 = safe_eval(x1)
        if y0 is not None and abs(y0) < 1e-8:
            roots.append(x0)
        if y0 is not None and y1 is not None and y0 * y1 < 0:
            a, b, fa, fb = x0, x1, y0, y1
            for _ in range(70):
                mid = (a + b) / 2
                fm = safe_eval(mid)
                if fm is None:
                    break
                if abs(fm) < 1e-12 or abs(b - a) < 1e-11:
                    a = b = mid
                    break
                if fa * fm <= 0:
                    b, fb = mid, fm
                else:
                    a, fa = mid, fm
            roots.append((a + b) / 2)
        x0, y0 = x1, y1
    # Also try Newton seeds to catch roots that merely touch the x-axis.
    for seed in [-50, -20, -10, -5, -2, -1, 0, 1, 2, 5, 10, 20, 50]:
        try:
            root = complex(sp.N(sp.nsolve(expr, variable, seed, verify=False)))
            if abs(root.imag) < 1e-8 and math.isfinite(root.real):
                roots.append(root.real)
        except Exception:
            pass
    unique = []
    for root in sorted(roots):
        if lower - 1e-8 <= root <= upper + 1e-8 and all(abs(root-r) > 1e-5 for r in unique):
            unique.append(root)
    return unique


def solve_equation(equation, show_steps=False):
    """Parse and solve a one-variable equation, returning a Russian result."""
    if equation.count("=") != 1:
        raise ValueError("Для уравнения нужен ровно один знак =")
    left_text, right_text = equation.split("=", 1)
    left_text, right_text = left_text.strip(), right_text.strip()
    if not left_text or not right_text:
        raise ValueError("Не хватает левой или правой части уравнения")
    # Permit a broad but bounded set of mathematical symbols and names.
    for part in (left_text, right_text):
        if len(part) > 500 or not re.fullmatch(r"[0-9A-Za-z_+\-*/().,%\s×÷•⋅√∛^!π°−–—⌈⌉⌊⌋⁰¹²³⁴⁵⁶⁷⁸⁹]+", part):
            raise ValueError("В уравнении есть неподдерживаемые символы")
    names = set(re.findall(r"[A-Za-z_]+", (left_text + " " + right_text).replace("sin", "").replace("cos", "")))
    # Function names/constants are not variables; equations are solved for one unknown.
    reserved = set(_CALC_FUNCTIONS) | {"pi", "π", "e", "E"}
    vars_found = sorted(name for name in names if name not in reserved)
    if not vars_found:
        # Constant equality: evaluate both sides directly.
        symbols = {}
        lhs, rhs = _parse_calc_side(left_text, symbols), _parse_calc_side(right_text, symbols)
        same = sp.simplify(lhs-rhs) == 0
        return ("Равенство верно." if same else f"Равенство неверно: {_calc_format(lhs)} ≠ {_calc_format(rhs)}"), ["Вычисляем обе части.", f"Левая часть: {_calc_format(lhs)}", f"Правая часть: {_calc_format(rhs)}"]
    if len(vars_found) != 1:
        raise ValueError("Пока можно автоматически решить уравнение только с одной неизвестной: " + ", ".join(vars_found))
    variable = sp.Symbol(vars_found[0], real=True)
    lhs = _parse_calc_side(left_text, {vars_found[0]: variable})
    rhs = _parse_calc_side(right_text, {vars_found[0]: variable})
    difference = sp.expand(lhs-rhs)
    if sp.simplify(difference) == 0:
        return "Бесконечно много решений: левая и правая части тождественно равны.", ["Переносим всё в левую часть.", "Получаем 0 = 0, поэтому подходит любое допустимое значение переменной."]
    if not difference.has(variable):
        return "Решений нет: после упрощения получается ненулевое равенство констант.", [f"Упрощаем: {_calc_format(lhs)} = {_calc_format(rhs)}", "Левая и правая части не равны."]

    steps = [f"1. Переносим всё в левую часть: {sp.sstr(difference)} = 0."]
    solutions = None
    try:
        if difference.is_polynomial(variable):
            poly = sp.Poly(difference, variable)
            exact = sp.solve(poly.as_expr(), variable)
            solutions = [sp.N(r, 14) for r in exact if sp.im(sp.N(r)) == 0]
            steps.append(f"2. Это полиномиальное уравнение степени {poly.degree()}; находим его корни.")
        else:
            result_set = sp.solveset(difference, variable, domain=sp.S.Reals)
            if isinstance(result_set, sp.FiniteSet):
                solutions = sorted(list(result_set), key=lambda v: float(sp.N(v)))
                steps.append("2. Применяем символьный решатель в области действительных чисел.")
            else:
                numeric = _numeric_roots(difference, variable)
                solutions = [sp.Float(r, 12) for r in numeric]
                steps.append("2. Закрытая формула не найдена; ищем действительные корни численно на отрезке [-1000; 1000].")
    except Exception:
        numeric = _numeric_roots(difference, variable)
        solutions = [sp.Float(r, 12) for r in numeric]
        steps.append("2. Используем численный поиск действительных корней на отрезке [-1000; 1000].")

    # Filter invalid/complex roots and verify candidates in original equation.
    cleaned = []
    for root in solutions or []:
        try:
            value = complex(sp.N(root, 14))
            if abs(value.imag) > 1e-7 or not math.isfinite(value.real):
                continue
            residual = abs(float(sp.N(difference.subs(variable, value.real), 12)))
            if residual < 1e-5 and all(abs(value.real-float(sp.N(old))) > 1e-5 for old in cleaned):
                cleaned.append(sp.Float(value.real, 12))
        except Exception:
            # Keep exact symbolic roots if they can be verified symbolically.
            if sp.simplify(difference.subs(variable, root)) == 0 and root not in cleaned:
                cleaned.append(root)
    cleaned.sort(key=lambda r: float(sp.N(r)))
    if not cleaned:
        result_text = "Действительные решения не найдены в проверенном диапазоне. Возможно, решений нет или численный поиск не смог их обнаружить."
        steps.append("3. Проверяем кандидаты подстановкой; подтверждённых действительных корней не найдено.")
    else:
        shown_roots = cleaned[:12]
        result_text = "Решение: " + "; ".join(f"{variable} ≈ {_calc_format(root, 14)}" for root in shown_roots)
        steps.append("3. Проверяем найденные корни подстановкой в исходное уравнение.")
        for root in shown_roots:
            lhs_value = sp.N(lhs.subs(variable, root), 10)
            rhs_value = sp.N(rhs.subs(variable, root), 10)
            residual = sp.N(difference.subs(variable, root), 6)
            root_text = _calc_format(root, 12)
            steps.append(
                f"   Подстановка x = {root_text}: "
                f"левая часть = {_calc_format(lhs_value, 10)}, "
                f"правая часть = {_calc_format(rhs_value, 10)}."
            )
            steps.append(
                f"   Разность: {_calc_format(lhs_value, 10)} − "
                f"({_calc_format(rhs_value, 10)}) ≈ {_calc_format(residual, 6)}."
            )
        if len(cleaned) > 12:
            steps.append(f"   Показаны первые 12 корней; в проверенном диапазоне найдено всего {len(cleaned)}.")
    return result_text, steps


def calculate_expression_steps(expr):
    """Return a numeric operation-by-operation trace for a numeric expression."""
    normalized = _normalize_calc_input((expr or "").strip())
    local_dict = dict(_CALC_LOCALS)
    tree = parse_expr(
        normalized, local_dict=local_dict, global_dict=_CALC_GLOBALS,
        transformations=_CALC_TRANSFORMATIONS, evaluate=False,
    )
    if tree.free_symbols:
        raise ValueError("Для пошагового вычисления неизвестных нужно уравнение с =")
    steps = []

    def walk(node):
        if not getattr(node, "args", ()):
            return node
        children = [walk(arg) for arg in node.args]
        try:
            rebuilt = node.func(*children, evaluate=False)
        except TypeError:
            rebuilt = node.func(*children)
        if rebuilt.is_number:
            value = sp.N(rebuilt, 12)
            if rebuilt.func == sp.Add:
                symbol = " + " if len(children) == 2 else " + "
            elif rebuilt.func == sp.Mul:
                symbol = " × "
            elif rebuilt.func == sp.Pow:
                symbol = " ^ "
            else:
                symbol = None
            if symbol and len(children) == 2:
                lhs_text = _calc_format(children[0], 10)
                rhs_text = _calc_format(children[1], 10)
                result_text = _calc_format(value, 12)
                if rebuilt.func == sp.Add:
                    steps.append(f"{lhs_text} + {rhs_text} = {result_text}")
                elif rebuilt.func == sp.Mul:
                    steps.append(f"{lhs_text} × {rhs_text} = {result_text}")
                elif rebuilt.func == sp.Pow:
                    steps.append(f"{lhs_text} ^ {rhs_text} = {result_text}")
            elif rebuilt.func == sp.Add and len(children) > 2:
                steps.append(f"{sp.sstr(rebuilt)} = {_calc_format(value, 12)}")
            elif rebuilt.func not in (sp.Add, sp.Mul, sp.Pow):
                steps.append(f"{sp.sstr(rebuilt)} = {_calc_format(value, 12)}")
        return rebuilt

    evaluated = walk(tree)
    result = sp.N(evaluated, 16)
    if result.is_real is False or not math.isfinite(float(result)):
        raise ValueError("Результат не является конечным действительным числом")
    # Retain actual numeric steps in evaluation order and remove duplicates.
    return result, list(dict.fromkeys(steps))


def calculate_expression(expr):
    """Evaluate a numeric expression or solve an equation if '=' is present."""
    expr = (expr or "").strip()
    if "=" in expr:
        return solve_equation(expr, show_steps=False)
    normalized = _normalize_calc_input(expr)
    local_dict = dict(_CALC_LOCALS)
    parsed = parse_expr(normalized, local_dict=local_dict, global_dict=_CALC_GLOBALS,
                        transformations=_CALC_TRANSFORMATIONS, evaluate=True)
    if parsed.free_symbols:
        raise ValueError("Обнаружена неизвестная переменная. Для уравнения укажите знак =")
    result = sp.N(parsed, 16)
    if result.is_real is False:
        return result
    try:
        value = float(result)
        if not math.isfinite(value):
            raise ValueError("Результат не является конечным числом")
        return value
    except (TypeError, OverflowError):
        return result



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

BO_HP_REFRESH_THRESHOLD = 100
BO_INITIAL_HITS = 10
BO_WAIT_TIMEOUT = 10
BO_STATE_TIMEOUT = 5

BO_TIME_RE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>h|hr|hrs|hour|hours|ч|час|часа|часов|min|mins|minute|minutes|мин|минута|минуты|минут|sec|secs|second|seconds|с|сек|секунда|секунды|секунд)",
    re.IGNORECASE,
)
BO_CLOCK_RE = re.compile(r"(?<!\d)(?P<h>\d{1,3}):(?P<m>\d{1,2})(?::(?P<s>\d{1,2}))?(?!\d)")

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
    """Разбирает таймер из alert/edit/new message MineEVO."""
    text = text or ""
    clock = BO_CLOCK_RE.search(text)
    if clock:
        hours = int(clock.group("h"))
        minutes = int(clock.group("m"))
        seconds = int(clock.group("s") or 0)
        return hours * 3600 + minutes * 60 + seconds

    units = {
        "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
        "ч": 3600, "час": 3600, "часа": 3600, "часов": 3600,
        "min": 60, "mins": 60, "minute": 60, "minutes": 60,
        "мин": 60, "минута": 60, "минуты": 60, "минут": 60,
        "sec": 1, "secs": 1, "second": 1, "seconds": 1,
        "с": 1, "сек": 1, "секунда": 1, "секунды": 1, "секунд": 1,
    }
    total = 0.0
    found = False
    for match in BO_TIME_RE.finditer(text):
        found = True
        value = float(match.group("value").replace(",", "."))
        total += value * units.get(match.group("unit").lower(), 0)
    return total if found else None


def bo_extract_wait_seconds(*texts):
    for text in texts:
        value = bo_parse_wait_time(text)
        if value is not None:
            return value
    return None


def bo_is_rate_limit_alert(text):
    text = (text or "").lower()
    return (
        "слишком быстро" in text
        or "не так быстро" in text
        or "подожди" in text and "сек" in text
    )


def bo_is_battle(text):
    text = (text or "").lower().replace("️", "")
    return "босс" in text and "оз" in text and "атак" in text


# Точные соответствия эмодзи и названий боссов MineEVO.
# Используются для отображения выбранного босса в уведомлениях и таймерах.
BOSS_EMOJI_NAMES = {
    "🌬": "Элементаль Воздуха",
    "🧚‍♀️": "Алая Фея",
    "🤴🏼": "Король Мёртвых",
    "🧌": "Лесной Тролль",
    "🗿️": "Каменный Голем",
    "🧝🏼‍♂️": "Эльфийский Лучник",
    "💀": "Некромант",
    "🧙🏼‍♀️": "Тёмная Колдунья",
    "🦖": "Меха-Раптор",
    "🧟‍♂️": "Мертвяк",
    "🧞‍♂️": "Джин",
    "🐦‍🔥": "Феникс",
    "🐍": "Безобидная Кобра",
    "🦇": "Адская Птице-мышь",
    "👺": "Огненный Бес",
    "🦄": "Призматический Скакун",
    "🐛": "Механический Червь",
    "👹": "Люцифер",
    "🕷": "Паукобот",
    "🤖": "Криобот",
    "🐲": "Золотой Дракон",
    "🐉": "Виверна",
    "🦎": "Дикий Ящер",
    "👻": "Полтергейст",
    "👽": "Пришелец",
    "👾": "Космический Странник",
}

BOSS_NAME_TO_EMOJI = {name: emoji for emoji, name in BOSS_EMOJI_NAMES.items()}


def bo_is_boss_menu(text):
    text = (text or "").lower().replace("️", "")
    return "выбери босса" in text or ("босс" in text and "атаковать" not in text and "получить" not in text)


def bo_is_victory(text):
    text = (text or "").lower().replace("️", "")
    return ("босс был повержен" in text or
            "босс уже был повержен" in text or
            "босс убит" in text)


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
    """Нажимает callback-кнопку и возвращает (answer, alert_text)."""
    if bo_stop_event and bo_stop_event.is_set():
        raise asyncio.CancelledError
    try:
        answer = await _mine_click_with_limit(message, row, col)
        alert_text = (
            getattr(answer, "message", None)
            or getattr(answer, "alert", None)
            or getattr(answer, "text", None)
            or ""
        )
        logger.info(
            "[BO] click(row=%s,col=%s) -> answer=%r, alert=%r",
            row, col, answer, alert_text,
        )
        return answer, str(alert_text)
    except errors.FloodWaitError as exc:
        logger.warning("[BO] FloodWait: жду %s сек.", exc.seconds)
        await bo_wait_seconds(exc.seconds)
        if bo_stop_event and bo_stop_event.is_set():
            raise asyncio.CancelledError
        return await bo_click(message, row, col)
    except Exception:
        logger.exception("[BO] Ошибка callback-клика row=%s col=%s", row, col)
        raise


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
    """Проверяет таймеры боссов в Work и выбирает ближайший вариант.

    Если нажатие уже открыло бой прямо в Work, сразу возвращаем этот факт.
    Если MineEVO сообщает «босса уже победили» с таймером, после ожидания
    меню проверяется заново, а не выполняется попытка открыть старый бой.
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
            raise RuntimeError("Меню боссов исчезло во время проверки таймеров.")

        try:
            current_button = current.buttons[row][col]
        except (IndexError, TypeError):
            continue

        before_text = current.raw_text or ""
        before_buttons = repr(current.buttons)
        _, alert_text = await bo_click(current, row, col)
        wait_seconds = bo_extract_wait_seconds(alert_text)

        if bo_is_rate_limit_alert(alert_text):
            wait_seconds = bo_extract_wait_seconds(alert_text) or MINE_BUTTON_INTERVAL
            await bo_wait_seconds(wait_seconds)
            current = await bo_get_fresh_message(chat_id, menu_id)
            if not current or not current.buttons:
                continue
            try:
                current_button = current.buttons[row][col]
            except (IndexError, TypeError):
                continue
            before_text = current.raw_text or ""
            before_buttons = repr(current.buttons)
            _, alert_text = await bo_click(current, row, col)
            wait_seconds = bo_extract_wait_seconds(alert_text)

        logger.info(
            "[BO] Таймер кнопки %r -> alert=%r, wait=%s",
            current_button.text, alert_text, wait_seconds,
        )

        if bo_is_rate_limit_alert(alert_text):
            continue

        # Кнопка уже открыла настоящий бой прямо в Work.
        changed = await bo_wait_after_action(
            chat_id, menu_id, before_text, before_buttons,
            lambda m: bo_is_battle(m.raw_text or "")
            or bo_is_victory(m.raw_text or "")
            or bo_parse_wait_time(m.raw_text or "") is not None,
            timeout=BO_STATE_TIMEOUT,
        )
        if changed and bo_is_battle(changed.raw_text or ""):
            logger.info("[BO] Бой уже открыт прямо в Work; пропускаю ожидание таймера.")
            return {
                "wait": 0.0,
                "row": row,
                "col": col,
                "button_text": current_button.text,
                "work_battle": True,
                "cooldown": False,
            }

        # Alert вида «Этого босса уже победили... Приходи снова через ...»
        # означает именно cooldown. После ожидания нужно заново запросить
        # меню Work, а не пытаться открыть устаревший бой в личке.
        alert_lower = (alert_text or "").lower()
        cooldown = (
            "уже победили" in alert_lower
            or "уже был повержен" in alert_lower
            or "уже повержен" in alert_lower
        )
        if wait_seconds is not None:
            candidates.append((
                max(0.0, wait_seconds), row, col, current_button.text, cooldown
            ))
            continue

        if changed:
            changed_wait = bo_parse_wait_time(changed.raw_text or "")
            if changed_wait is not None:
                candidates.append((
                    max(0.0, changed_wait), row, col, current_button.text, False
                ))
                continue

        logger.warning(
            "[BO] Не удалось получить таймер кнопки %r; пропускаю.",
            current_button.text,
        )

    if not candidates:
        raise RuntimeError("Не удалось получить время ожидания ни от одной кнопки босса.")

    wait_seconds, row, col, button_text, cooldown = min(
        candidates, key=lambda item: item[0]
    )
    logger.info(
        "[BO] Выбран босс %r: ждать %.3f сек.; cooldown=%s",
        button_text, wait_seconds, cooldown,
    )
    return {
        "wait": wait_seconds,
        "row": row,
        "col": col,
        "button_text": button_text,
        "work_battle": False,
        "cooldown": cooldown,
    }


async def bo_get_private_chat():
    """Возвращает личный чат с MineEVO."""
    try:
        return await client.get_entity(THX_BOT)
    except Exception as exc:
        raise RuntimeError(
            f"Не удалось открыть личный чат MineEVO ({THX_BOT}): {type(exc).__name__}."
        ) from exc


async def bo_start_private_fight(selected):
    """Открывает/находит активный бой в личке MineEVO."""
    private_chat = await bo_get_private_chat()

    # Сначала один раз отправляем «бо». Если бой уже активен, MineEVO может
    # сразу вернуть сообщение боя — тогда кнопку выбора босса нажимать нельзя.
    state = await ask_mineevo("бо", timeout=BO_WAIT_TIMEOUT, chat_id=private_chat)
    if state and (
        bo_is_battle(state.raw_text or "")
        or bo_find_button_contains(state, "атаковать") is not None
    ):
        logger.info("[BO] В личке уже найден активный бой.")
        return state

    menu = state if state and bo_is_boss_menu(state.raw_text or "") else None
    if menu is None:
        menu = await bo_get_menu_retry(chat_id=private_chat, attempts=2)

    wanted = (selected.get("button_text") or "").strip()
    button = bo_find_button(menu, wanted) if wanted else None
    if not button and wanted:
        button = bo_find_button_contains(menu, wanted)
    if not button:
        row, col = selected["row"], selected["col"]
        try:
            candidate = menu.buttons[row][col]
            button = (row, col, candidate)
        except (IndexError, TypeError):
            button = None
    if not button:
        raise RuntimeError(f"В личке не найдена кнопка босса «{wanted}».")

    row, col, selected_button = button
    before_text = menu.raw_text or ""
    before_buttons = repr(menu.buttons)
    _, alert_text = await bo_click(menu, row, col)

    if bo_is_rate_limit_alert(alert_text):
        await bo_wait_seconds(bo_extract_wait_seconds(alert_text) or MINE_BUTTON_INTERVAL)

    battle = await bo_wait_after_action(
        menu.chat_id,
        menu.id,
        before_text,
        before_buttons,
        lambda m: bo_is_battle(m.raw_text or "")
        or bo_find_button_contains(m, "атаковать") is not None,
        timeout=BO_STATE_TIMEOUT,
    )
    if not battle:
        battle = await bo_wait_new_message(
            menu.chat_id, after_id=menu.id, timeout=BO_STATE_TIMEOUT
        )
    if not battle or not (
        bo_is_battle(battle.raw_text or "")
        or bo_find_button_contains(battle, "атаковать") is not None
    ):
        raise RuntimeError("После выбора босса в личке MineEVO не открылся бой.")

    logger.info("[BO] Бой открыт в личке MineEVO: %r", selected_button.text)
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

    while not bo_stop_event.is_set():
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

        # MineEVO edits the same battle message after an attack; it does not
        # necessarily send a new message. Wait for any meaningful edit of that
        # message, while independently checking for a new victory/reward post.
        updated = await bo_wait_after_action(
            chat_id,
            current.id,
            before_text,
            before_buttons,
            lambda m: (
                bo_is_battle(m.raw_text or "")
                or bo_is_victory(m.raw_text or "")
                or bo_find_button_contains(m, "атаковать") is not None
                or "награда получена" in (m.raw_text or "").lower()
            ),
            timeout=BO_STATE_TIMEOUT,
        )
        if updated:
            current = updated
            if bo_is_victory(current.raw_text or "") or "награда получена" in (current.raw_text or "").lower():
                return current
            continue

        # Victory can arrive as a separate message, so do not wait only for
        # the battle message to change.
        recent = await client.get_messages(chat_id, limit=10)
        victory_post = next((m for m in recent if not m.out and (
            bo_is_victory(m.raw_text or "") or "награда получена" in (m.raw_text or "").lower()
        )), None)
        if victory_post:
            return victory_post

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
    """Забирает награду в личке; после этого следующий цикл идёт в Work."""
    if bo_stop_event.is_set():
        raise asyncio.CancelledError

    reward = bo_find_button_contains(victory, "получить")
    if not reward:
        raise RuntimeError("Кнопка «🎉 Получить» не найдена.")

    old_id = victory.id
    before_text = victory.raw_text or ""
    before_buttons = repr(victory.buttons)
    await bo_click(victory, reward[0], reward[1])

    # MineEVO может создать отдельное сообщение или отредактировать текущее.
    reward_message = await bo_wait_after_action(
        victory.chat_id,
        victory.id,
        before_text,
        before_buttons,
        lambda m: "награда получена" in (m.raw_text or "").lower(),
        timeout=BO_STATE_TIMEOUT,
    )
    if not reward_message:
        reward_message = await bo_wait_new_message(
            victory.chat_id, after_id=old_id, timeout=2.0
        )

    if reward_message:
        logger.info("[BO] Награда получена в личке MineEVO.")
    else:
        # Сам callback уже был принят MineEVO. Не останавливаем весь цикл,
        # если подтверждение пришло в виде alert, а не сообщения.
        logger.warning("[BO] Подтверждение награды не найдено; продолжаю цикл.")

    # После получения награды MineEVO показывает единственную кнопку
    # «Вернуться к боссу». Нажимаем её один раз и завершаем действие .bo.
    return_button = None
    for source in (reward_message, victory):
        return_button = bo_find_button_contains(source, "вернуться к боссу")
        if return_button:
            break

    if not return_button:
        # Сообщение могло быть отредактировано после callback. Получаем
        # свежую версию сообщения и проверяем кнопку ещё раз.
        fresh = await bo_get_fresh_message(victory.chat_id, victory.id)
        return_button = bo_find_button_contains(fresh, "вернуться к боссу") if fresh else None

    if not return_button:
        # Если MineEVO создал отдельное сообщение с кнопкой, ищем его среди
        # последних сообщений личного чата, но не нажимаем никакие другие
        # кнопки и не выбираем другого босса.
        recent = await client.get_messages(victory.chat_id, limit=10)
        for message in recent:
            return_button = bo_find_button_contains(message, "вернуться к боссу")
            if return_button:
                victory = message
                break

    if return_button:
        await bo_click(victory, return_button[0], return_button[1])
        logger.info("[BO] Нажата единственная кнопка «Вернуться к боссу». Цикл завершён.")
    else:
        logger.warning("[BO] Кнопка «Вернуться к боссу» после награды не найдена.")

    return reward_message


async def bo_get_menu_retry(chat_id=None, attempts=3):
    """Получает меню боссов в указанном чате, соблюдая паузу между запросами."""
    last_error = None
    for attempt in range(1, attempts + 1):
        if bo_stop_event.is_set():
            raise asyncio.CancelledError

        try:
            menu = await ask_mineevo("бо", timeout=BO_WAIT_TIMEOUT, chat_id=chat_id)
            raw = menu.raw_text if menu else ""
            if menu and bo_is_boss_menu(raw):
                return menu
            logger.warning("[BO] «бо» ответ не похож на меню боссов: %r", raw)
            last_error = RuntimeError("MineEVO не прислал меню выбора босса.")
        except (TimeoutError, RuntimeError) as exc:
            last_error = exc

        if attempt < attempts:
            logger.warning(
                "[BO] Меню боссов не найдено (попытка %s/%s), повторяю «бо».",
                attempt, attempts
            )
            await bo_wait_seconds(1.0)

    raise last_error or RuntimeError("Не удалось получить меню боссов.")


async def bo_select_boss_retry(menu):
    """
    Если сообщение меню было удалено или стало недоступно после ожидания,
    снова запрашивает «бо» и продолжает автоатаку.
    """
    last_error = None
    for attempt in range(1, 4):
        if bo_stop_event.is_set():
            raise asyncio.CancelledError

        try:
            return await bo_select_boss(menu)
        except RuntimeError as exc:
            last_error = exc
            logger.warning(
                "[BO] Меню стало недоступно: %s. Отправляю «бо» заново "
                "(попытка %s/3).",
                exc, attempt
            )
            if attempt >= 3:
                break
            menu = await bo_get_menu_retry(attempts=3)

    raise last_error or RuntimeError("Не удалось выбрать босса.")


async def bo_manual_selection_loop(work_chat):
    """Продолжает .bo только после ручного выбора босса пользователем.

    Этот цикл не перебирает кнопки и не выбирает/не приоритизирует босса.
    Он лишь ждёт, пока пользователь сам нажмёт кнопку выбора в Work.
    """
    global bo_stop_event
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async def edited_handler(event):
        if future.done() or bo_stop_event.is_set():
            return
        message = event.message
        if not message or message.chat_id != work_chat:
            return
        if message.out:
            return
        if bo_is_battle(message.raw_text or ""):
            future.set_result(message)

    client.add_event_handler(edited_handler, events.MessageEdited(chats=work_chat))
    try:
        while not bo_stop_event.is_set():
            try:
                # Проверяем последние сообщения, чтобы не пропустить изменение,
                # пришедшее до регистрации обработчика.
                messages = await client.get_messages(work_chat, limit=10)
                for message in messages:
                    if not message.out and bo_is_battle(message.raw_text or ""):
                        future.set_result(message)
                        break
                if future.done():
                    break
                await asyncio.wait_for(asyncio.shield(future), timeout=2.0)
            except asyncio.TimeoutError:
                continue

        if bo_stop_event.is_set():
            return

        # Пользователь уже выбрал босса в Work. Больше никаких кликов по меню
        # выбора не выполняем. Ищем только уже открытый бой в личке.
        private_chat = await bo_get_private_chat()
        battle = await ask_mineevo("бо", timeout=BO_WAIT_TIMEOUT, chat_id=private_chat)
        if not battle or not (
            bo_is_battle(battle.raw_text or "")
            or bo_find_button_contains(battle, "атаковать") is not None
        ):
            raise RuntimeError("После ручного выбора не найден активный бой в личке MineEVO.")

        victory = await bo_fight(battle)
        if not bo_stop_event.is_set():
            try:
                await bo_reward_and_return(victory)
            except RuntimeError as exc:
                logger.warning("[BO] Не удалось получить награду: %s", exc)
    finally:
        client.remove_event_handler(edited_handler, events.MessageEdited(chats=work_chat))


async def bo_loop(work_chat):
    global bo_stop_event
    while not bo_stop_event.is_set():
        try:
            menu = await bo_get_menu_retry(chat_id=work_chat)
            selected = await bo_select_boss_retry(menu)
            if bo_stop_event.is_set():
                raise asyncio.CancelledError

            if selected.get("work_battle"):
                battle = await bo_start_private_fight(selected)
            else:
                await bo_wait_seconds(selected["wait"])
                if bo_stop_event.is_set():
                    raise asyncio.CancelledError

                # Если это был cooldown «уже победили», после ожидания
                # обязательно возвращаемся к Work и заново проверяем меню.
                if selected.get("cooldown"):
                    continue

                battle = await bo_start_private_fight(selected)

            victory = await bo_fight(battle)
            if bo_stop_event.is_set():
                raise asyncio.CancelledError

            try:
                await bo_reward_and_return(victory)
            except RuntimeError as exc:
                logger.warning(
                    "[BO] Не удалось завершить возврат после награды: %s. "
                    "Продолжаю со следующего цикла.", exc
                )

        except asyncio.CancelledError:
            logger.info("[BO] Цикл автоатаки остановлен.")
            raise
        except Exception as exc:
            # Ошибка одного босса не должна убивать .bo навсегда.
            logger.exception("[BO] Ошибка цикла автоатаки: %s", exc)
            await bo_wait_seconds(3.0)


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

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.promosource$"))
    async def promosource_handler(event):
        """Sets the current chat as the source for promo announcements."""
        config["promo_source_chat"] = event.chat_id
        config["thx_source_chat"] = event.chat_id
        config["thx_enabled"] = True
        save_config()
        await answer_and_delete(
            event,
            "✅ <b>Общий источник подключён.</b>\n"
            f"ID чата: <code>{event.chat_id}</code>\n"
            "Отслеживаю промокоды и события Thx.",
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.thxoff$"))
    async def thxoff_handler(event):
        config["thx_enabled"] = False
        save_config()
        await answer_and_delete(event, "✅ Наблюдение за событиями Thx выключено.")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.botimers$"))
    async def botimers_handler(event):
        """Starts passive observation; never presses/selects boss-menu buttons."""
        global bo_timer_watch_active, bo_timer_records
        bo_timer_records = {}
        bo_timer_watch_active = True
        private_chat = await bo_get_private_chat()

        def observe_message(message):
            if not message:
                return
            raw = message.raw_text or ""
            timer = bo_extract_wait_seconds(raw)
            # Also examine button labels: some MineEVO states put timer text there.
            labels = []
            for row in (message.buttons or []):
                for button in row:
                    label = (getattr(button, "text", "") or "").strip()
                    labels.append(label)
                    if timer is None:
                        timer = bo_parse_wait_time(label)
            if timer is None:
                return
            combined = raw + " " + " ".join(labels)
            emoji = next((key for key in BOSS_EMOJI_NAMES if key in combined), None)
            if not emoji:
                lowered = combined.casefold()
                matched_name = next(
                    (name for name in BOSS_EMOJI_NAMES.values() if name.casefold() in lowered),
                    None,
                )
                if matched_name:
                    emoji = next((em for em, name in BOSS_EMOJI_NAMES.items() if name == matched_name), None)
            if not emoji:
                return
            name = BOSS_EMOJI_NAMES[emoji]
            key = (message.chat_id, message.id)
            bo_timer_records[key] = {
                "seconds": max(0, int(timer)), "emoji": emoji,
                "name": name, "message": message,
            }

        # Collect currently visible timer-bearing messages first.
        messages = await client.get_messages(private_chat, limit=200)
        for message in reversed(list(messages)):
            observe_message(message)

        await event.edit(
            "⏱ <b>.botimers включён.</b>\n"
            "Открывай алёрты MineEVO вручную. Я собираю только таймеры,\n"
            "которые доступны как сообщения/изменения сообщений в Telegram.\n"
            "Когда закончишь, отправь <code>.botimersstop</code>."
        )

        async def watch_new(e):
            if bo_timer_watch_active and e.chat_id == private_chat:
                observe_message(e.message)
        async def watch_edit(e):
            if bo_timer_watch_active and e.chat_id == private_chat:
                observe_message(e.message)
        client.add_event_handler(watch_new, events.NewMessage(chats=private_chat))
        client.add_event_handler(watch_edit, events.MessageEdited(chats=private_chat))
        # Keep event handlers registered until .botimersstop; task is cancelled there.
        global bo_task
        async def watcher():
            try:
                while bo_timer_watch_active:
                    await asyncio.sleep(0.5)
            finally:
                client.remove_event_handler(watch_new, events.NewMessage(chats=private_chat))
                client.remove_event_handler(watch_edit, events.MessageEdited(chats=private_chat))
        bo_task = asyncio.create_task(watcher())

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.botimersstop$"))
    async def botimersstop_handler(event):
        global bo_timer_watch_active, bo_task
        bo_timer_watch_active = False
        if bo_task and not bo_task.done():
            await bo_task
        bo_task = None
        if not bo_timer_records:
            return await answer_and_delete(
                event,
                "⚠️ Не удалось распознать таймеры в доступных сообщениях. "
                "Всплывающие alert-окна Telegram не всегда передаются юзерботу как сообщения."
            )
        ordered = sorted(bo_timer_records.values(), key=lambda item: item["seconds"])
        lines = ["⏱ <b>Распознанные таймеры MineEVO</b>"]
        for i, item in enumerate(ordered, 1):
            seconds = item["seconds"]
            mins, secs = divmod(seconds, 60)
            hours, mins = divmod(mins, 60)
            formatted = (f"{hours}ч " if hours else "") + (f"{mins}м " if mins else "") + f"{secs}с"
            lines.append(f"<b>{i}.</b> {item['emoji']} {item['name']} — <code>{formatted}</code>")
        lines.extend(["", "⚠️ Выбор номера пока только показывает распознанный таймер; "
                      "запуск боя по popup-alert нельзя надёжно связать с конкретной кнопкой, "
                      "пока Telegram не передаёт данные этого alert в события юзербота."])
        await answer_and_delete(event, "\n".join(lines), delay=60)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.bo(?:off)?$"))
    async def removed_bo_handler(event):
        await answer_and_delete(
            event,
            "⚠️ Команда <code>.bo</code> удалена. Используй <code>.botimers</code> "
            "и <code>.botimersstop</code>."
        )

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

        published = {}
        reply_to = event.reply_to_msg_id if event.is_reply else None

        async def publish_waiting(response):
            data, callback_links = _message_to_helper_data(response, event.chat_id)
            source_link = {
                "source_chat": response.chat_id,
                "source_message_id": response.id,
                "destination_chat": event.chat_id,
                "callback_links": callback_links,
            }
            sent, token = await publish_through_helper(
                data, event.chat_id, reply_to=reply_to, source_link=source_link,
                media_message=response,
            )
            published.update({
                "token": token,
                "link": {**source_link, "helper_token": token},
                "sent": sent,
            })

        try:
            response = await ask_mineevo(
                args, timeout=30.0, chat_id=config["mine_work_chat"],
                on_waiting=publish_waiting,
            )
            if response is None:
                return await answer_and_delete(event, "⚠️ MineEVO не ответил.")

            if published.get("token"):
                token = published["token"]
                inline_message_id = helper_inline_ids.get(token)
                for _ in range(50):
                    if inline_message_id:
                        break
                    await asyncio.sleep(0.1)
                    inline_message_id = helper_inline_ids.get(token)
                if not inline_message_id:
                    raise RuntimeError("Helper не передал inline_message_id для обновления .evo")

                data, callback_links = _message_to_helper_data(response, event.chat_id)
                link = published["link"]
                link.update({
                    "source_chat": response.chat_id,
                    "source_message_id": response.id,
                    "callback_links": callback_links,
                })
                await update_helper_inline_message(response, link, inline_message_id)
                helper_publications[token]["source_link"] = link
            else:
                data, callback_links = _message_to_helper_data(response, event.chat_id)
                source_link = {
                    "source_chat": response.chat_id,
                    "source_message_id": response.id,
                    "destination_chat": event.chat_id,
                    "callback_links": callback_links,
                }
                await publish_through_helper(
                    data, event.chat_id, reply_to=reply_to,
                    source_link=source_link, media_message=response,
                )
            await event.delete()
        except Exception as exc:
            logger.exception("Ошибка .evo")
            safe_reason = str(exc).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if len(safe_reason) > 350:
                safe_reason = safe_reason[:347] + "..."
            await event.edit(
                "⚠️ <b>Ошибка .evo:</b> "
                f"<code>{type(exc).__name__}</code> — {safe_reason}"
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
        outgoing=True, pattern=r"^\.calc(?:\s+(all\b)?\s*(.*))?$"
    ))
    async def calc_handler(event):
        all_mode = bool(event.pattern_match.group(1))
        expr = (event.pattern_match.group(2) or "").strip()
        if not expr and event.is_reply:
            replied = await event.get_reply_message()
            expr = (replied.raw_text or "").strip() if replied else ""
            if expr.lower().startswith(".calc"):
                expr = expr[5:].strip()
        if not expr:
            return await answer_and_delete(
                event, "⚠️ Формат: <code>.calc 2+2*5</code> или <code>.calc all уравнение</code>"
            )
        try:
            if "=" in expr:
                result_text, steps = solve_equation(expr, show_steps=all_mode)
                output = f"<code>{expr}</code>\n<b>{result_text}</b>"
                if all_mode:
                    output += "\n\n<b>Пошаговое решение:</b>\n" + "\n".join(steps)
            else:
                if all_mode:
                    result, steps = calculate_expression_steps(expr)
                else:
                    result = calculate_expression(expr)
                    steps = []
                if isinstance(result, tuple):
                    result_text, steps = result
                    output = f"<code>{expr}</code>\n<b>{result_text}</b>"
                    if all_mode:
                        output += "\n\n<b>Пошаговое решение:</b>\n" + "\n".join(steps)
                else:
                    formatted = _calc_format(result)
                    output = f"<code>{expr}</code> = <b>{formatted}</b>"
                    if all_mode:
                        if not steps:
                            steps = [f"{expr} = {formatted}"]
                        output += "\n\n<b>Пошаговые вычисления:</b>\n" + "\n".join(
                            f"{i}. <code>{step}</code>" for i, step in enumerate(steps, 1)
                        )
            await event.edit(output[:3900], parse_mode="html")
        except Exception as exc:
            logger.info(".calc failed (%s)", type(exc).__name__)
            await answer_and_delete(
                event, "⚠️ Не удалось решить выражение. Проверьте запись и область определения. Для пошагового решения используйте <code>.calc all ...</code>."
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
    async def promo_source_watcher(event):
        source_chat = config.get("promo_source_chat")
        if source_chat is None or event.chat_id != source_chat:
            return

        text = event.raw_text or ""
        match = re.search(
            r"пиши\s+в\s+боте\s*:\s*промо\s+\[?([^\]\s]+)\]?",
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
        source_chat = config.get("promo_source_chat")
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
