"""Supabase-backed storage. Replaces the old SQLite layer. Nothing here ever
deletes a row — notes and drafts are append-only; only score/status/decided_at
are ever updated in place.
"""
from __future__ import annotations

from typing import Optional

from postgrest.exceptions import APIError
from supabase import Client, create_client

from bot.config import Config

UNIQUE_VIOLATION = "23505"


def get_client(config: Config) -> Client:
    return create_client(config.supabase_url, config.supabase_key)


def insert_note_if_new(client: Client, *, telegram_update_id: int, chat_id: int, text: str) -> Optional[dict]:
    """Insert a note, deduplicated on telegram_update_id (so a Telegram retry of
    the same update never produces a second note or a second draft). Returns
    the inserted row, or None if this update_id was already processed."""
    try:
        res = (
            client.table("notes")
            .insert({"telegram_update_id": telegram_update_id, "chat_id": chat_id, "text": text})
            .execute()
        )
    except APIError as exc:
        if getattr(exc, "code", None) == UNIQUE_VIOLATION:
            return None
        raise
    return res.data[0]


def update_note_score(client: Client, note_id: int, *, score: int, reason: str) -> None:
    client.table("notes").update({"score": score, "score_reason": reason}).eq("id", note_id).execute()


def insert_draft(
    client: Client,
    *,
    note_id: int,
    draft_text: str,
    model: str,
    news_headline: str | None = None,
    news_source: str | None = None,
    news_date: str | None = None,
    news_link: str | None = None,
) -> dict:
    res = (
        client.table("drafts")
        .insert(
            {
                "note_id": note_id,
                "draft_text": draft_text,
                "model": model,
                "news_headline": news_headline,
                "news_source": news_source,
                "news_date": news_date,
                "news_link": news_link,
                "status": "pending",
            }
        )
        .execute()
    )
    return res.data[0]


def update_draft_status(client: Client, draft_id: int, *, status: str, decided_at: str) -> None:
    client.table("drafts").update({"status": status, "decided_at": decided_at}).eq("id", draft_id).execute()


def get_voice_skill(client: Client) -> Optional[str]:
    res = client.table("voice_skill").select("content").order("updated_at", desc=True).limit(1).execute()
    if not res.data:
        return None
    return res.data[0]["content"]


def seed_voice_skill(client: Client, content: str) -> None:
    client.table("voice_skill").insert({"content": content}).execute()


def find_best_matching_note(client: Client, *, keywords: list[str], min_score: int | None = None) -> Optional[dict]:
    """Naive keyword-overlap match over stored notes, most recent first among
    ties. Used by TRIGGER_MODE=topic. Replaced with proper ranking once
    scoring (score >= 6 filter) lands."""
    query = client.table("notes").select("*").order("created_at", desc=True)
    if min_score is not None:
        query = query.gte("score", min_score)
    res = query.execute()
    rows = res.data or []

    keywords_lower = [k.lower() for k in keywords if k.strip()]
    if not keywords_lower:
        return rows[0] if rows else None

    best_row = None
    best_hits = 0
    for row in rows:
        text_lower = (row.get("text") or "").lower()
        hits = sum(1 for kw in keywords_lower if kw in text_lower)
        if hits > best_hits:
            best_hits = hits
            best_row = row

    return best_row if best_hits > 0 else None
