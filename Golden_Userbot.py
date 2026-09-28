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

    def __str__(self) -> str:
        return "".join(chr(byte ^ self._core_salt) for byte in self._core_entropy)
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
