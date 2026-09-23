"""Idempotent one-time/repeatable import of the notes/ backlog.

Format: one note per file under data/notes/, as .txt or .md. The filename
(without extension) is used as the note's source_id, so re-running the import
never creates duplicates (dedup on (source, source_id) in the notes table).

Usage: python -m bot.import_notes [--notes-dir data/notes]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bot import db
from bot.config import load_config


def import_notes(db_path: str, notes_dir: Path) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    if not notes_dir.exists():
        print(f"Notes directory {notes_dir} does not exist — nothing to import.")
        return inserted, skipped

    files = sorted(
        p for p in notes_dir.iterdir() if p.is_file() and p.suffix.lower() in (".txt", ".md")
    )
    for path in files:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        source_id = path.stem
        row_id = db.insert_note(db_path, source="backlog", source_id=source_id, text=text)
        if row_id is None:
            skipped += 1
        else:
            inserted += 1
    return inserted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes-dir", default="data/notes", help="Directory of note files")
    args = parser.parse_args()

    config = load_config()
    db.init_db(config.db_path)

    inserted, skipped = import_notes(config.db_path, Path(args.notes_dir))
    total = db.count_notes(config.db_path)
    print(f"Imported {inserted} new note(s), skipped {skipped} already-imported. Total notes in DB: {total}.")


if __name__ == "__main__":
    sys.exit(main() or 0)
