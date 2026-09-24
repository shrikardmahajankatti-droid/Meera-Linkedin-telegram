"""Register the production webhook with Telegram, including callback_query in
allowed_updates (the plain setWebhook curl command used during earlier manual
testing omitted it, so button presses never reached the bot).

Usage: python -m bot.set_webhook <https://your-deploy-url>/api/webhook
"""
from __future__ import annotations

import asyncio
import sys

from telegram import Bot

from bot.config import load_config

ALLOWED_UPDATES = ["message", "channel_post", "callback_query"]


async def run(url: str) -> None:
    config = load_config()
    bot = Bot(config.telegram_bot_token)
    await bot.set_webhook(url=url, secret_token=config.telegram_webhook_secret, allowed_updates=ALLOWED_UPDATES)
    info = await bot.get_webhook_info()
    print(f"Webhook set: {info.url}")
    print(f"allowed_updates: {info.allowed_updates}")
    print(f"pending_update_count: {info.pending_update_count}")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m bot.set_webhook <https://your-deploy-url>/api/webhook")
        raise SystemExit(1)
    asyncio.run(run(sys.argv[1]))


if __name__ == "__main__":
    main()
