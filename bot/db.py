from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('telegram', 'backlog')),
    source_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    score INTEGER,
    keywords TEXT,
    has_real_specific INTEGER,
    reason TEXT,
    used_count INTEGER NOT NULL DEFAULT 0,
    needs_transcript INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('topic', 'draft')),
    topic TEXT NOT NULL,
    matched_note_ids TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES requests(id),
    idx INTEGER NOT NULL,
    title TEXT NOT NULL,
    angle TEXT NOT NULL,
    note_ids TEXT
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES requests(id),
    note_ids TEXT,
    news_link TEXT,
    draft_text TEXT NOT NULL,
    final_text TEXT,
    flags TEXT,
    sent_at TEXT,
    decided_at TEXT,
    decision TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def cursor(db_path: str) -> Iterator[sqlite3.Cursor]:
    conn = connect(db_path)
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_note(
    db_path: str,
    *,
    source: str,
    source_id: str,
    text: str,
    needs_transcript: bool = False,
) -> Optional[int]:
    """Insert a note, deduplicated on (source, source_id). Returns the new row id,
    or None if a note with that (source, source_id) already exists."""
    with cursor(db_path) as cur:
        cur.execute(
            "SELECT id FROM notes WHERE source = ? AND source_id = ?",
            (source, source_id),
        )
        if cur.fetchone() is not None:
            return None
        cur.execute(
            """
            INSERT INTO notes (source, source_id, text, created_at, needs_transcript)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source, source_id, text, now_iso(), int(needs_transcript)),
        )
        return cur.lastrowid


def count_notes(db_path: str) -> int:
    with cursor(db_path) as cur:
        cur.execute("SELECT COUNT(*) AS c FROM notes")
        return cur.fetchone()["c"]
