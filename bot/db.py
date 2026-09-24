"""Supabase-backed storage. Nothing here ever deletes a row — notes, drafts
and gate_decisions are append-only; only score/status/decided_at (drafts),
score/score_reason (notes), and the override_* fields + draft_id/
telegram_message_id (gate_decisions) are ever updated in place.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def get_note(client: Client, note_id: int) -> Optional[dict]:
    res = client.table("notes").select("*").eq("id", note_id).execute()
    rows = res.data or []
    return rows[0] if rows else None


def update_note_score(client: Client, note_id: int, *, score: int, reason: str) -> None:
    client.table("notes").update({"score": score, "score_reason": reason}).eq("id", note_id).execute()


def mark_update_processed_if_new(client: Client, telegram_update_id: int) -> bool:
    """Dedup for updates that are never stored as notes — triggers, /override,
    callbacks. Separate from `notes` so that table stays real captured
    fragments only. Returns False if this update_id was already seen
    (a Telegram retry), True the first time."""
    try:
        client.table("processed_updates").insert({"telegram_update_id": telegram_update_id}).execute()
    except APIError as exc:
        if getattr(exc, "code", None) == UNIQUE_VIOLATION:
            return False
        raise
    return True


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
    gate_decision_id: int | None = None,
    is_override: bool = False,
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
                "gate_decision_id": gate_decision_id,
                "is_override": is_override,
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


# --- Gate decisions ---------------------------------------------------------


def insert_gate_decision(
    client: Client,
    *,
    note_id: int | None,
    topic: str,
    decision: str,
    total_score: int,
    scores: dict,
    reasons: dict,
    hard_blocks: list,
    news_items: list,
    suggested_angle: str | None,
    gate_error: str | None = None,
) -> dict:
    res = (
        client.table("gate_decisions")
        .insert(
            {
                "note_id": note_id,
                "topic": topic,
                "decision": decision,
                "total_score": total_score,
                "scores": scores,
                "reasons": reasons,
                "hard_blocks": hard_blocks,
                "news_items": news_items,
                "suggested_angle": suggested_angle,
                "gate_error": gate_error,
            }
        )
        .execute()
    )
    return res.data[0]


def get_gate_decision(client: Client, decision_id: int) -> Optional[dict]:
    res = client.table("gate_decisions").select("*").eq("id", decision_id).execute()
    rows = res.data or []
    return rows[0] if rows else None


def update_gate_decision_override(
    client: Client,
    decision_id: int,
    *,
    override_status: str,
    override_reason: str | None,
    overridden_at: str,
) -> bool:
    """Atomic compare-and-swap: only succeeds if this decision has no
    override_status yet and no linked draft. Returns True if this call won
    the race, False if a concurrent press/retry got there first — the caller
    must treat False as "already handled" and do nothing further (in
    particular, never generate or send a draft)."""
    res = (
        client.table("gate_decisions")
        .update({"override_status": override_status, "override_reason": override_reason, "overridden_at": overridden_at})
        .eq("id", decision_id)
        .is_("override_status", "null")
        .is_("draft_id", "null")
        .execute()
    )
    return bool(res.data)


def clear_gate_decision_override(client: Client, decision_id: int) -> None:
    """Roll back an override mark when drafting failed right after the
    compare-and-swap succeeded (e.g. Gemini quota exhausted), so Meera isn't
    permanently locked out of retrying that override."""
    client.table("gate_decisions").update({"override_status": None, "override_reason": None, "overridden_at": None}).eq(
        "id", decision_id
    ).execute()


def set_gate_decision_reason(client: Client, decision_id: int, *, override_reason: str) -> None:
    """Backfill a reason onto an already-overridden decision, e.g. when Meera
    replies to the skip message with free text after already pressing a
    button. Never overwrites a reason that's already set."""
    client.table("gate_decisions").update({"override_reason": override_reason}).eq("id", decision_id).is_(
        "override_reason", "null"
    ).execute()


def link_draft_to_gate_decision(client: Client, decision_id: int, *, draft_id: int, telegram_message_id: int | None) -> None:
    client.table("gate_decisions").update({"draft_id": draft_id, "telegram_message_id": telegram_message_id}).eq(
        "id", decision_id
    ).execute()


def set_gate_decision_message_id(client: Client, decision_id: int, *, telegram_message_id: int) -> None:
    client.table("gate_decisions").update({"telegram_message_id": telegram_message_id}).eq("id", decision_id).execute()


def get_recent_content_for_gate(client: Client, limit: int = 10) -> list[str]:
    """Last `limit` approved draft texts; if there are none yet, the last
    `limit` pending draft texts instead. Used as tone/novelty reference."""
    approved = (
        client.table("drafts").select("draft_text").eq("status", "approved").order("decided_at", desc=True).limit(limit).execute()
    )
    rows = approved.data or []
    if not rows:
        pending = (
            client.table("drafts").select("draft_text").eq("status", "pending").order("created_at", desc=True).limit(limit).execute()
        )
        rows = pending.data or []
    return [row["draft_text"] for row in rows if row.get("draft_text")]


def get_recent_gate_topics(client: Client, since_days: int) -> list[str]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    res = client.table("gate_decisions").select("topic").gte("created_at", cutoff).execute()
    return [row["topic"] for row in (res.data or []) if row.get("topic")]


def get_days_since_last_approved_draft(client: Client) -> float | None:
    res = client.table("drafts").select("decided_at").eq("status", "approved").order("decided_at", desc=True).limit(1).execute()
    rows = res.data or []
    if not rows or not rows[0].get("decided_at"):
        return None
    decided_at = datetime.fromisoformat(rows[0]["decided_at"].replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - decided_at).total_seconds() / 86400
