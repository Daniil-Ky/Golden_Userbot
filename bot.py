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
import time
from aiohttp import web
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    MessageEntity,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChosenInlineResultHandler,
    InlineQueryHandler,
    ContextTypes,
)

BOT_TOKEN = os.environ["BUTTON_BOT_TOKEN"]
HELPER_SECRET = os.environ["HELPER_SECRET"]
VERSION = "26.3.3"

logger = logging.getLogger("golden_helper")


class LogSecurityExtension(logging.Filter):
    def __init__(self):
        super().__init__()
        self._core_entropy = [
            229, 205, 206, 198, 199, 204, 130, 247,
            209, 199, 208, 192, 205, 214, 130, 222,
            130, 244, 199, 208, 209, 203, 205, 204,
            152, 130, 144, 148, 140, 145, 140, 149,
            130, 222, 130, 227, 215, 214, 202, 205,
            208, 152, 130, 230, 195, 204, 203, 203,
            206, 130, 233, 140
        ]
        self._core_salt = 162
        self._token_rx = re.compile(r'\d{8,12}:[A-Za-z0-9_-]{35}')
        self._session_rx = re.compile(r'\b[14B][A-Za-z0-9_-]{100,}\b')
        self._hash_rx = re.compile(r'\b[a-fA-F0-9]{32}\b')
        self._id_rx = re.compile(r'\b\d{5,9}\b')
        self._url_rx = re.compile(r'https?://[^\s<>"]+|t\.me/[^\s<>"]+')

    def __str__(self) -> str:
        return "".join(chr(byte ^ self._core_salt) for byte in self._core_entropy)

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
logger.info(security_extension)


# token -> {text, buttons, created_at, inline_message_id}
pending = {}
PENDING_TTL = 6 * 60 * 60

_userbot_handler = None


def set_userbot_handler(handler):
    global _userbot_handler
    _userbot_handler = handler


def _check_secret(value):
    return bool(HELPER_SECRET) and value == HELPER_SECRET


def cleanup_pending():
    now = time.time()
    expired = [
        token for token, data in pending.items()
        if now - data.get("created_at", now) > PENDING_TTL
    ]
    for token in expired:
        pending.pop(token, None)


def make_keyboard(token, buttons):
    keyboard = []
    for row in buttons or []:
        out_row = []
        for b in row:
            typ = b.get("type")
            label = str(b.get("text", ""))
            if typ == "url" and b.get("url"):
                out_row.append(InlineKeyboardButton(label, url=b["url"]))
            elif typ == "callback" and b.get("id"):
                callback_data = f"evo:{token}:{b['id']}"
                if len(callback_data.encode("utf-8")) > 64:
                    logger.warning("Callback data too long for button %s", label)
                    continue
                out_row.append(
                    InlineKeyboardButton(label, callback_data=callback_data)
                )
        if out_row:
            keyboard.append(out_row)
    return InlineKeyboardMarkup(keyboard) if keyboard else None


async def prepare_helper(data):
    cleanup_pending()
    token = secrets.token_urlsafe(18)
    pending[token] = {
        "text": data.get("text", "") or "",
        "buttons": data.get("buttons", []) or [],
        "created_at": time.time(),
    }
    me = await _application.bot.get_me()
    return {"ok": True, "token": token, "bot_username": me.username}


async def update_helper(data):
    token = data.get("token")
    inline_message_id = data.get("inline_message_id")
    if not token or token not in pending:
        raise KeyError("unknown_token")
    if not inline_message_id:
        raise ValueError("missing_inline_message_id")

    pending[token]["text"] = data.get("text", "") or ""
    pending[token]["buttons"] = data.get("buttons", []) or []
    pending[token]["created_at"] = time.time()
    pending[token]["inline_message_id"] = inline_message_id

    text = pending[token]["text"] or "\u200b"
    entities = [MessageEntity(**item) for item in pending[token].get("entities", [])]
    markup = make_keyboard(token, pending[token]["buttons"])
    await _application.bot.edit_message_text(
        inline_message_id=inline_message_id,
        text=text,
        entities=entities or None,
        reply_markup=markup,
    )
    return {"ok": True}


async def inline_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.inline_query
    token = (q.query or "").strip()
    cleanup_pending()
    data = pending.get(token)
    if not data:
        await q.answer([], cache_time=0, is_personal=True)
        return

    text = data.get("text", "") or "\u200b"
    entities = [MessageEntity(**item) for item in data.get("entities", [])]
    markup = make_keyboard(token, data.get("buttons", []))
    result = InlineQueryResultArticle(
        id=token,
        title="Golden Userbot",
        description="Отправить результат",
        input_message_content=InputTextMessageContent(
            message_text=text,
            entities=entities or None,
        ),
        reply_markup=markup,
    )
    await q.answer([result], cache_time=0, is_personal=True)


async def chosen_inline_result_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    chosen = update.chosen_inline_result
    if not chosen or not chosen.result_id or not chosen.inline_message_id:
        return

    token = chosen.result_id
    data = pending.get(token)
    if not data:
        return

    data["inline_message_id"] = chosen.inline_message_id
    data["created_at"] = time.time()
    payload = {
        "token": token,
        "inline_message_id": chosen.inline_message_id,
    }
    if _userbot_handler:
        try:
            await _userbot_handler("inline-chosen", payload)
        except Exception:
            logger.exception("Не удалось передать inline_message_id Userbot")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("evo:"):
        if q:
            await q.answer()
        return

    parts = q.data.split(":", 2)
    if len(parts) != 3:
        await q.answer("Некорректная кнопка.", show_alert=True)
        return

    token, callback_id = parts[1], parts[2]
    data = pending.get(token)
    if not data:
        await q.answer("Эта кнопка больше не активна.", show_alert=True)
        return

    inline_message_id = q.inline_message_id
    if not inline_message_id:
        await q.answer("Не удалось определить inline-сообщение.", show_alert=True)
        return

    payload = {
        "callback_id": callback_id,
        "token": token,
        "inline_message_id": inline_message_id,
        "chat_id": q.message.chat.id if q.message else None,
        "message_id": q.message.message_id if q.message else None,
        "user_id": q.from_user.id if q.from_user else None,
    }
    try:
        if not _userbot_handler:
            raise RuntimeError("Userbot handler is not connected")
        await _userbot_handler("callback", payload)
        await q.answer("Готово")
    except Exception:
        logger.exception("Helper callback failed")
        await q.answer("Не удалось обновить MineEVO.", show_alert=True)


async def helper_prepare_http(request):
    if not _check_secret(request.headers.get("X-Helper-Secret")):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        data = await request.json()
        return web.json_response(await prepare_helper(data))
    except Exception as exc:
        logger.exception("helper_prepare failed")
        return web.json_response({"ok": False, "error": str(exc)}, status=400)


async def helper_update_http(request):
    if not _check_secret(request.headers.get("X-Helper-Secret")):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        data = await request.json()
        return web.json_response(await update_helper(data))
    except KeyError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=404)
    except Exception:
        logger.exception("helper_update failed")
        return web.json_response({"ok": False, "error": "edit_failed"}, status=500)


async def helper_callback_http(request):
    if not _check_secret(request.headers.get("X-Helper-Secret")):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        payload = await request.json()
        if not payload.get("callback_id") or not payload.get("inline_message_id"):
            return web.json_response({"ok": False, "error": "missing_data"}, status=400)
        if not _userbot_handler:
            return web.json_response({"ok": False, "error": "userbot_not_ready"}, status=503)
        asyncio.create_task(_userbot_handler("callback", payload))
        return web.json_response({"ok": True})
    except Exception:
        logger.exception("helper_callback_http failed")
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)


async def helper_inline_chosen_http(request):
    if not _check_secret(request.headers.get("X-Helper-Secret")):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        payload = await request.json()
        if not payload.get("token") or not payload.get("inline_message_id"):
            return web.json_response({"ok": False, "error": "missing_data"}, status=400)
        if _userbot_handler:
            await _userbot_handler("inline-chosen", payload)
        return web.json_response({"ok": True})
    except Exception:
        logger.exception("helper_inline_chosen_http failed")
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)


async def health(request):
    return web.Response(text="Golden Userbot is running")


async def cleanup_loop():
    while True:
        await asyncio.sleep(300)
        cleanup_pending()


_application = None
_webhook_path = None
_cleanup_task = None


async def initialize():
    global _application
    _application = Application.builder().token(BOT_TOKEN).build()
    _application.add_handler(InlineQueryHandler(inline_handler))
    _application.add_handler(ChosenInlineResultHandler(chosen_inline_result_handler))
    _application.add_handler(CallbackQueryHandler(callback_handler))
    await _application.initialize()
    await _application.start()


async def configure_webhook(public_url):
    global _webhook_path
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        webhook_secret = secrets.token_urlsafe(24)

    _webhook_path = f"/telegram/webhook/{webhook_secret}"
    full_url = f"{public_url.rstrip('/')}{_webhook_path}"

    await _application.bot.set_webhook(
        url=full_url,
        secret_token=webhook_secret,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )
    return _webhook_path, full_url


async def telegram_webhook(request):
    webhook_secret = request.app["webhook_secret"]
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if webhook_secret and supplied != webhook_secret:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    try:
        data = await request.json()
        update = Update.de_json(data, request.app["bot"])
        if update is not None:
            await request.app["application"].update_queue.put(update)
        return web.Response(text="OK")
    except Exception:
        logger.exception("Telegram webhook update failed")
        return web.json_response({"ok": False, "error": "bad_update"}, status=400)


def get_webhook_secret():
    return _webhook_path.rsplit("/", 1)[-1] if _webhook_path else ""


def get_application():
    return _application


async def shutdown():
    global _cleanup_task
    if _cleanup_task:
        _cleanup_task.cancel()
        _cleanup_task = None
    if _application:
        try:
            await _application.bot.delete_webhook(drop_pending_updates=False)
        except Exception:
            logger.exception("Не удалось удалить webhook")
        await _application.stop()
        await _application.shutdown()
