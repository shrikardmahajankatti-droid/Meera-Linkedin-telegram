"""Seed the voice_skill table from data/voice-skill.txt.

Usage: python -m bot.seed_voice_skill [path]

Always inserts a new row (voice_skill is a tiny append-only log of revisions);
runtime code always reads the most recently updated row.
"""
from __future__ import annotations

import sys
from pathlib import Path

from bot import db
from bot.config import load_config


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/voice-skill.txt")
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        print(f"{path} is empty — nothing to seed.")
        raise SystemExit(1)

    config = load_config()
    client = db.get_client(config)
    db.seed_voice_skill(client, content)
    print(f"Seeded voice_skill from {path} ({len(content)} chars).")


if __name__ == "__main__":
    main()
