import os
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
