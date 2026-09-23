"""Vercel entrypoint. Must live at api/webhook.py so the deployed URL is
/api/webhook. One POST per Telegram update; no polling, no background work
after the response — everything happens synchronously inside do_POST.
"""
from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler

from telegram import Bot, Update

from bot import db, pipeline
from bot.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        config = load_config()

        secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret != config.telegram_webhook_secret:
            logger.warning("Rejected webhook call: bad or missing secret token.")
            self._respond(403, {"ok": False, "error": "forbidden"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError:
            self._respond(400, {"ok": False, "error": "invalid json"})
            return

        try:
            bot = Bot(config.telegram_bot_token)
            update = Update.de_json(data, bot)
            if update is None:
                self._respond(200, {"ok": True})
                return
            supabase_client = db.get_client(config)
            asyncio.run(pipeline.process_update(update, config, supabase_client))
        except Exception:  # noqa: BLE001
            # Always ack Telegram so it doesn't retry into the same failure;
            # the real error goes to Vercel's logs, never into the response.
            logger.exception("Unhandled error while processing update %s", data.get("update_id"))

        self._respond(200, {"ok": True})

    def _respond(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
