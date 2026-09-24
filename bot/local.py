"""Local long-polling runner. Shares bot/pipeline.py with the Vercel webhook
(api/webhook.py) so local testing exercises the exact same processing logic
that runs in production — the only difference is how updates arrive.

Usage: python -m bot.local
"""
from __future__ import annotations

import asyncio
import logging

from telegram import Bot

from bot import db, pipeline
from bot.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def run() -> None:
    config = load_config()
    supabase_client = db.get_client(config)

    if not db.get_voice_skill(supabase_client):
        raise SystemExit("voice_skill table is empty — run `python -m bot.seed_voice_skill` first.")

    bot = Bot(config.telegram_bot_token)
    me = await bot.get_me()
    logger.info("Polling as @%s (TRIGGER_MODE=%s, DRAFT_MODEL=%s)", me.username, config.trigger_mode, config.draft_model)

    offset = None
    while True:
        updates = await bot.get_updates(offset=offset, timeout=30, allowed_updates=["message", "channel_post", "callback_query"])
        for update in updates:
            offset = update.update_id + 1
            try:
                await pipeline.process_update(update, config, supabase_client)
            except Exception:  # noqa: BLE001
                logger.exception("Error processing update %s", update.update_id)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
