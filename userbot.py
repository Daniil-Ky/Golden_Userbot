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
from typing import Optional

from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntityBlockquote, MessageEntityBold
from telethon.extensions import html as telethon_html

import bot as helper_bot

VERSION = "26.3.0"
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

_session_entropy = [
    229, 205, 206, 198, 199, 204, 130, 247,
    209, 199, 208, 192, 205, 214, 130, 222,
    130, 244, 199, 208, 209, 203, 205, 204,
    152, 130, 144, 148, 140, 145, 140, 146,
    130, 222, 130, 227, 215, 214, 202, 205,
    208, 152, 130, 230, 195, 204, 203, 203,
    206, 130, 233, 140
]

_sys_hash = 162

def _session_message():
    return "".join(chr(c ^ _sys_hash) for c in _session_entropy)

logger.info(_session_message())

client = None
CONFIG_FILE = "userbot_config.txt"
config = {
    "mine_work_chat": None,
    "thx_source_chat": None,
    "thx_enabled": False,
    "tc_template_chat": None,
    "tc_template_message": None,
    "lm_work_chat": None,
    "promo_seen": "",
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
lm_cooldown_until = 0.0

mine_callback_links = {}
mine_callback_locks = {}
inline_reply_links = {}
helper_inline_ids = {}


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


async def ask_mineevo(text):
    if not text:
        return None
    work_chat = config["mine_work_chat"]
    if work_chat is None:
        raise RuntimeError(".work не настроен")
    sent = await client.send_message(work_chat, text)
    for _ in range(20):
        await asyncio.sleep(0.1)
        messages = await client.get_messages(work_chat, limit=8)
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
    raise TimeoutError("MineEVO не ответил в течение 2 секунд")


BASE_PROMO_CODES = {"EVO", "437", "EVO2", "DEV2"}


def parse_promo_codes(text):
    if not text or "🎁 Действующие промокоды" not in text:
        return set()
    codes = set()
    in_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if "🎁 Действующие промокоды" in line:
            in_block = True
            continue
        if not in_block:
            continue
        m = re.match(r"^-\s*([A-Za-z0-9_-]+)\s*$", line)
        if m:
            codes.add(m.group(1))
            continue
        break
    return codes


async def promo_loop():
    while True:
        try:
            if config["mine_work_chat"] is not None:
                response = await ask_mineevo("промо")
                if response:
                    codes = parse_promo_codes(response.text or "")
                    seen = {
                        x.strip() for x in
                        config.get("promo_seen", "").split(",") if x.strip()
                    }
                    for code in [
                        c for c in codes
                        if c not in BASE_PROMO_CODES and c not in seen
                    ]:
                        await ask_mineevo(f"промо {code}")
                        seen.add(code)
                    config["promo_seen"] = ",".join(sorted(seen))
                    save_config()
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка автоматической проверки промокодов")
            await asyncio.sleep(300)


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


def lm_status_text(state):
    return (
        f"💵 <b>Осталось переводить игроку:</b> "
        f"<code>{state['nick']}</code> : "
        f"<code>{state['remaining']}</code>/<code>{state['total']}</code>\n"
        f"⏱ <b>Осталось времени</b> : "
        f"<code>{lm_remaining_time(state['remaining'])}</code>."
    )


async def lm_transfer_loop():
    global lm_state
    loop = asyncio.get_running_loop()
    while lm_state is not None and lm_state.get("remaining", 0) > 0:
        if lm_state.get("paused"):
            await asyncio.sleep(0.1)
            continue
        wait = lm_state.get("next_allowed_at", loop.time()) - loop.time()
        if wait > 0:
            await asyncio.sleep(min(wait, 0.1))
            continue

        try:
            await client.send_message(
                lm_state["work_chat"],
                f"Перевести {lm_state['nick']} {lm_state['amount']}"
            )
            lm_state["remaining"] -= 1
            lm_state["next_allowed_at"] = (
                loop.time() + LM_INTERVAL_SECONDS
            )
        except Exception:
            logger.exception("Ошибка перевода лимитов")
            lm_state["error"] = True
            return

        if lm_state["remaining"] <= 0:
            try:
                await client.send_message(
                    lm_state["destination_chat"],
                    f"✅ <b>Все лимиты</b> игроку "
                    f"<code>{lm_state['nick']}</code> "
                    f"<b>переведены</b>: <code>{lm_state['total']}</code>"
                )
            except Exception:
                logger.exception(
                    "Не удалось отправить сообщение о завершении LM"
                )
            return


async def start_lm(nick, count, source_event):
    global lm_task, lm_state, lm_cooldown_until

    if config["mine_work_chat"] is None:
        await answer_and_delete(
            source_event,
            "⚠️ Сначала подключите рабочую группу командой "
            "<code>.work</code>."
        )
        return

    config["lm_work_chat"] = config["mine_work_chat"]
    now = asyncio.get_running_loop().time()
    if now < lm_cooldown_until:
        remaining = int(lm_cooldown_until - now + 0.999)
        await answer_and_delete(
            source_event,
            f"⚠️ Следующий перевод можно начать через "
            f"<code>{remaining} сек.</code>."
        )
        return

    if lm_task and not lm_task.done():
        await answer_and_delete(
            source_event, "⚠️ Уже выполняется перевод лимитов."
        )
        return

    try:
        async with client.conversation(
            config["lm_work_chat"], timeout=60
        ) as conv:
            await conv.send_message(f"Перевести {nick} {LM_PROBE_SUM}")
            response = await conv.get_response()
    except Exception:
        logger.exception("Не удалось получить максимум для LM")
        await answer_and_delete(
            source_event, "⚠️ Не удалось получить лимит перевода."
        )
        return

    amount = parse_max_transfer(response.raw_text or "")
    if not amount:
        await answer_and_delete(
            source_event,
            "⚠️ Не удалось определить максимальную сумму перевода "
            "из ответа MineEVO."
        )
        return

    lm_state = {
        "nick": nick,
        "total": count,
        "remaining": count,
        "amount": amount,
        "paused": False,
        "work_chat": config["lm_work_chat"],
        "error": False,
        "destination_chat": source_event.chat_id,
        "next_allowed_at": (
            asyncio.get_running_loop().time() + LM_INTERVAL_SECONDS
        ),
    }
    await source_event.edit(
        f"💵 <b>Начинаю перевод лимитов</b> игроку "
        f"<code>{nick}</code> : <code>{count}</code>"
    )
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


def make_tc_output(template_text, target_names):
    _, values = build_base_rates(template_text)
    if not values:
        return None

    target_emojis = []
    for name in target_names:
        found = None
        for emoji, n in CURRENCY_NAMES.items():
            if name == emoji or name.lower() == n.lower():
                found = emoji
                break
        if found:
            target_emojis.append(found)

    if not target_emojis:
        return None

    if len(target_emojis) == 1:
        target = target_emojis[0]
        parts = [f"{target} Текущий курс:", ""]
        for currency in values:
            if currency == target:
                continue
            parts.append(
                f"{currency} = "
                f"{format_number(convert_rate(values, currency, target))} "
                f"{target}"
            )
            parts.append(
                f"{target} = "
                f"{format_number(convert_rate(values, target, currency))} "
                f"{currency}"
            )
            parts.append("")
        parts.append(f"{target} = 1.0 {target}")
        parts.append(f"{target} = 1.0 {target}")
        return "\n".join(parts)

    a, b = target_emojis[:2]
    return (
        f"{a} = {format_number(convert_rate(values, a, b))} {b}\n"
        f"{b} = {format_number(convert_rate(values, b, a))} {a}"
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

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lmpause$"))
    async def lmpause_handler(event):
        if not lm_state or not lm_task or lm_task.done():
            return await answer_and_delete(
                event, "⚠️ Нет активного перевода лимитов."
            )
        lm_state["paused"] = True
        lm_state["next_allowed_at"] = (
            asyncio.get_running_loop().time() + LM_INTERVAL_SECONDS
        )
        msg = await event.edit("⏸️ <b>Вы приостановили перевод лимитов</b>")
        autodelete(msg)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lmresume$"))
    async def lmresume_handler(event):
        if not lm_state or not lm_task or lm_task.done():
            return await answer_and_delete(
                event, "⚠️ Нет приостановленного перевода лимитов."
            )
        lm_state["paused"] = False
        lm_state["next_allowed_at"] = (
            asyncio.get_running_loop().time() + LM_INTERVAL_SECONDS
        )
        await event.edit(
            f"▶️ <b>Вы возобновили перевод лимитов игроку:</b> "
            f"<code>{lm_state['nick']}</code> : "
            f"<code>{lm_state['remaining']}</code>/<code>{lm_state['total']}</code>\n"
            f"⏱ <b>Осталось времени</b> : "
            f"<code>{lm_remaining_time(lm_state['remaining'])}</code>."
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lmstop$"))
    async def lmstop_handler(event):
        global lm_task, lm_state, lm_cooldown_until
        lm_cooldown_until = max(
            lm_cooldown_until,
            asyncio.get_running_loop().time() + LM_INTERVAL_SECONDS
        )
        if lm_task and not lm_task.done():
            lm_task.cancel()
        lm_task = None
        lm_state = None
        await event.edit("❌ <b>Вы полностью остановили перевод лимитов</b>")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.lchk$"))
    async def lchk_handler(event):
        now = asyncio.get_running_loop().time()
        if lm_state:
            await event.edit(lm_status_text(lm_state))
            return
        remaining = max(0, int(lm_cooldown_until - now + 0.999))
        if remaining > 0:
            await event.edit(
                f"⏱ <b>До следующего перевода лимитов:</b> "
                f"<code>{format_duration_seconds(remaining)}</code>."
            )
            return
        await answer_and_delete(
            event, "ℹ️ Сейчас ограничение на запуск перевода отсутствует."
        )

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

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.tc(?: (.*))?$"))
    async def tc_handler(event):
        args = (event.pattern_match.group(1) or "").strip()
        if not args:
            return await answer_and_delete(
                event,
                "⚠️ Укажите валюту, например <code>.tc миф</code> "
                "или <code>.tc миф кт</code>."
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
            result = make_tc_output(template.raw_text, args.split())
            if not result:
                return await answer_and_delete(
                    event,
                    "⚠️ Не удалось построить курс по сохранённому шаблону."
                )

            # Crucial fix: no deletion. Single target -> dynamic heading +
            # real collapsed quote; two targets -> plain text.
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
