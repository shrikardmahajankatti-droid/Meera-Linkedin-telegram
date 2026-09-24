"""Telegram message and keyboard formatting for gate outcomes. Split out from
pipeline.py so the orchestration logic there stays readable — this module only
turns a GateResult into text/markup, no side effects.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.gate import GateResult

MAX_MESSAGE_CHARS = 4096

_CRITERIA = [
    ("relevance", "Relevance", 25),
    ("tone_match", "Tone match", 25),
    ("freshness_source", "Freshness/source", 15),
    ("value_add", "Value add", 15),
    ("novelty", "Novelty", 10),
    ("timing", "Timing", 10),
]


def format_warning_header(result: GateResult) -> str:
    weak = _weak_criteria(result)
    weak_str = ", ".join(weak) if weak else "none"
    return f"⚠️ Draft with warning — score {result.total_score}/100. Weak: {weak_str}."


def format_skip_or_blocked_message(topic: str, result: GateResult, decision_id: int) -> str:
    header = "🚫 Blocked" if result.decision == "blocked" else "⏭ Skipped"
    lines = [f'{header} — "{_truncate(topic, 200)}" (ref: {decision_id})', f"Score: {result.total_score}/100", ""]

    lines.append("Breakdown:")
    for key, label, max_score in _CRITERIA:
        score = result.scores.get(key, 0)
        reason = result.reasons.get(key, "")
        lines.append(f"• {label}: {score}/{max_score} — {_truncate(reason, 80)}")

    if result.hard_blocks:
        lines.append("")
        lines.append("Hard blocks:")
        for block in result.hard_blocks:
            lines.append(f"• {block.get('code')}: {_truncate(block.get('evidence', ''), 100)}")

    if result.gate_error:
        lines.append("")
        lines.append(f"Note: {result.gate_error}")

    if result.news_items:
        lines.append("")
        lines.append("Top news:")
        for item in result.news_items[:3]:
            lines.append(f"• {_truncate(item.headline, 100)} ({item.source})")

    return _truncate("\n".join(lines), MAX_MESSAGE_CHARS)


def format_confirm_override_message(decision: dict) -> str:
    return f"This hit a hard block: {_hard_block_codes(decision)}. Draft anyway?"


def format_override_header() -> str:
    return "✍️ Override — drafted despite a skip."


def format_hard_block_override_header(decision: dict) -> str:
    return f"⚠️ Override of hard block: {_hard_block_codes(decision)}"


def _hard_block_codes(decision: dict) -> str:
    seen: list[str] = []
    for block in decision.get("hard_blocks") or []:
        code = block.get("code", "")
        if code and code not in seen:
            seen.append(code)
    return ", ".join(seen)


def skip_or_blocked_keyboard(decision_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✍️ Draft anyway", callback_data=f"ovr:{decision_id}"), InlineKeyboardButton("🗑 Drop", callback_data=f"drop:{decision_id}")]]
    )


def confirm_override_keyboard(decision_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Yes, draft it", callback_data=f"ovr2:{decision_id}"), InlineKeyboardButton("Cancel", callback_data=f"cxl:{decision_id}")]]
    )


def _weak_criteria(result: GateResult, threshold_fraction: float = 0.5) -> list[str]:
    weak = []
    for key, label, max_score in _CRITERIA:
        if result.scores.get(key, 0) < max_score * threshold_fraction:
            weak.append(label)
    return weak


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
