import os
import re
import asyncio
import logging
from aiohttp import web

import bot
import userbot

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("golden_launcher")


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

PORT = int(os.environ.get("PORT", "10000"))


async def main():
    public_url = (
        os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
        or os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    )
    if not public_url:
        raise RuntimeError(
            "WEBHOOK_URL или RENDER_EXTERNAL_URL обязателен для Telegram webhook."
        )

    # The two components share one Python process and one asyncio loop.
    # Helper callbacks go directly to Userbot; no USERBOT_URL/HELPER_URL hop.
    bot.set_userbot_handler(userbot.handle_helper_event)
    await bot.initialize()
    await userbot.initialize()

    webhook_path, full_webhook_url = await bot.configure_webhook(public_url)
    webhook_secret = bot.get_webhook_secret()

    app = web.Application()
    app["bot"] = bot.get_application().bot
    app["application"] = bot.get_application()
    app["webhook_secret"] = webhook_secret

    app.router.add_get("/", bot.health)
    app.router.add_post("/helper/prepare", bot.helper_prepare_http)
    app.router.add_post("/helper/update", bot.helper_update_http)
    # Kept for compatibility with old integrations; normally unused now.
    app.router.add_post("/helper/callback", userbot.helper_callback)
    app.router.add_post("/helper/inline-chosen", userbot.helper_inline_chosen)
    app.router.add_post(webhook_path, bot.telegram_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    logger.info("Golden Userbot %s started", userbot.VERSION)
    logger.info("Single Render Web Service listening on %s", PORT)
    logger.info("Telegram Helper webhook: %s", full_webhook_url)

    try:
        await userbot.client.run_until_disconnected()
    finally:
        await bot.shutdown()
        await userbot.shutdown()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
