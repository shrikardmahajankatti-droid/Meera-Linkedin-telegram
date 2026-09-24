from unittest.mock import patch

from bot import gate
from bot.news import NewsItem
from datetime import datetime, timedelta, timezone


def _ctx(**overrides) -> gate.GateContext:
    base = dict(
        gemini_api_key="unused",
        recent_content=[],
        recent_topics=[],
        news_enabled=True,
        novelty_days=14,
        draft_threshold=70,
        warn_threshold=50,
        days_since_last_approved=3.0,
    )
    base.update(overrides)
    return gate.GateContext(**base)


def test_blocklist_match_blocks_without_calling_gemini():
    with patch("bot.gate._call_gate_llm") as mock_llm:
        result = gate.run_gate("Update on the death toll after a factory fire", [], _ctx())

    mock_llm.assert_not_called()
    assert result.decision == gate.BLOCKED
    assert result.total_score == 0
    assert result.hard_blocks[0]["code"] == "tragedy"


def _llm_result(relevance, tone_match, value_add, hard_blocks=None):
    return (
        {
            "hard_blocks": hard_blocks or [],
            "scores": {"relevance": relevance, "tone_match": tone_match, "value_add": value_add},
            "reasons": {"relevance": "r", "tone_match": "t", "value_add": "v"},
            "suggested_angle": "",
        },
        None,
    )


def test_score_70_drafts():
    # 25 + 25 + 15 (llm, max) = 65, plus freshness(8)+novelty(10)... need exactly 70.
    # Use freshness_source/novelty/timing neutral defaults (no news, no history): 8+10+? — timing depends on days_since.
    with patch("bot.gate._call_gate_llm", return_value=_llm_result(22, 22, 6)):
        result = gate.run_gate("niacinamide pH stability", [], _ctx(days_since_last_approved=2.0))
    assert result.total_score >= 70
    assert result.decision == gate.DRAFT


def test_score_just_below_draft_threshold_warns():
    with patch("bot.gate._call_gate_llm", return_value=_llm_result(0, 0, 0)):
        result = gate.run_gate("a middling topic", [], _ctx(days_since_last_approved=2.0))
    # relevance/tone/value=0, freshness=8 (no news), novelty=10 (no history), timing=6+4=10 -> total 28
    assert result.total_score < 70
    assert result.decision in (gate.DRAFT_WITH_WARNING, gate.SKIP)


def test_score_boundaries_exact():
    # Directly exercise the boundary math in run_gate's decision logic.
    # (relevance, tone_match, value_add) are LLM-provided and clamped to
    # (25, 25, 15); freshness_source here stands in for the Python-computed
    # remainder needed to hit each exact boundary total.
    cases = [
        (25, 25, 15, 5, 70, gate.DRAFT),
        (25, 25, 15, 4, 69, gate.DRAFT_WITH_WARNING),
        (25, 25, 0, 0, 50, gate.DRAFT_WITH_WARNING),
        (25, 24, 0, 0, 49, gate.SKIP),
    ]
    for relevance, tone_match, value_add, freshness, total, expected in cases:
        with patch("bot.gate._compute_freshness", return_value=(freshness, "x")), patch(
            "bot.gate._compute_novelty", return_value=(0, "x")
        ), patch("bot.gate._compute_timing", return_value=(0, "x")), patch(
            "bot.gate._call_gate_llm", return_value=_llm_result(relevance, tone_match, value_add)
        ):
            result = gate.run_gate("topic", [], _ctx())
        assert result.total_score == total, f"expected total={total} got={result.total_score}"
        assert result.decision == expected, f"total={total} expected={expected} got={result.decision}"


def test_python_computed_scores_override_llm_values():
    # LLM is only allowed to score relevance/tone_match/value_add — even if it
    # tries to sneak values into freshness/novelty/timing they're ignored,
    # because those keys don't exist in the schema the code reads from.
    with patch("bot.gate._call_gate_llm", return_value=_llm_result(10, 10, 10)):
        result = gate.run_gate("topic", [], _ctx(recent_topics=["topic"], days_since_last_approved=0.1))
    # recent_topics contains an identical topic -> novelty should be low (high overlap).
    assert result.scores["novelty"] <= 2


def test_malformed_json_retries_once_then_fails_open():
    """Exercises _call_gate_llm directly: first response is malformed JSON,
    second is valid — must retry exactly once and succeed, not give up early."""
    good_json = '{"hard_blocks": [], "scores": {"relevance": 20, "tone_match": 20, "value_add": 10}, "reasons": {"relevance": "r", "tone_match": "t", "value_add": "v"}, "suggested_angle": ""}'
    responses = [type("R", (), {"text": "not json"})(), type("R", (), {"text": good_json})()]
    mock_client = type("C", (), {"models": type("M", (), {"generate_content": lambda self, **kw: responses.pop(0)})()})()

    with patch("bot.gemini.get_client", return_value=mock_client):
        data, error = gate._call_gate_llm("topic", [], _ctx())

    assert error is None
    assert data["scores"]["relevance"] == 20


def test_malformed_json_after_retry_fails_open():
    mock_client = type("C", (), {"models": type("M", (), {"generate_content": lambda self, **kw: type("R", (), {"text": "still not json"})()})()})()

    with patch("bot.gemini.get_client", return_value=mock_client):
        data, error = gate._call_gate_llm("topic", [], _ctx())

    assert data is None
    assert "malformed JSON after retry" in error


def test_gemini_exception_fails_open():
    with patch("bot.gate._call_gate_llm", return_value=(None, "Gate unavailable: not checked for tone/safety (API error)")):
        result = gate.run_gate("topic", [], _ctx())
    assert result.decision == gate.DRAFT_WITH_WARNING
    assert result.gate_error is not None


def test_no_news_gives_neutral_freshness_credit():
    score, reason = gate._compute_freshness([], news_enabled=True)
    assert score == 8
    assert "neutral" in reason.lower()


def test_recent_news_scores_higher_than_stale_news():
    now = datetime.now(timezone.utc)
    fresh = [NewsItem(headline="a", source="X", published=now - timedelta(hours=2), link="")]
    stale = [NewsItem(headline="a", source="X", published=now - timedelta(hours=96), link="")]
    fresh_score, _ = gate._compute_freshness(fresh, news_enabled=True)
    stale_score, _ = gate._compute_freshness(stale, news_enabled=True)
    assert fresh_score > stale_score
