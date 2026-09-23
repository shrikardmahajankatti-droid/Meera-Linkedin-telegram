from __future__ import annotations

import asyncio
import logging

from bot import db
from bot.config import load_config
from bot.handlers import build_application, startup_checks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    config = load_config()
    db.init_db(config.db_path)

    app = build_application(config)
    asyncio.get_event_loop().run_until_complete(startup_checks(config, app.bot))

    app.run_polling(allowed_updates=["message", "channel_post", "callback_query"])


if __name__ == "__main__":
    main()
