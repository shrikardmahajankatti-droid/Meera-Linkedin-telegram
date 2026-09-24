from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx

from bot import news

FIXTURE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Niacinamide pH stability explained - Vogue India</title>
  <link>https://example.com/a</link>
  <pubDate>{recent}</pubDate>
  <source url="https://vogue.in">Vogue India</source>
</item>
<item>
  <title>Niacinamide pH stability explained - Vogue India</title>
  <link>https://example.com/a-dup</link>
  <pubDate>{recent}</pubDate>
  <source url="https://vogue.in">Vogue India</source>
</item>
<item>
  <title>Old skincare story - Old Source</title>
  <link>https://example.com/old</link>
  <pubDate>{old}</pubDate>
  <source url="https://old.example.com">Old Source</source>
</item>
</channel></rss>"""


def _rfc822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def _fixture_bytes(lookback_days: int) -> bytes:
    now = datetime.now(timezone.utc)
    recent = _rfc822(now - timedelta(hours=2))
    old = _rfc822(now - timedelta(days=lookback_days + 5))
    return FIXTURE_RSS.format(recent=recent, old=old).encode("utf-8")


def _mock_response(content: bytes, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=MagicMock(), response=resp)
    return resp


def test_parses_strips_suffix_and_caps_at_max_items():
    with patch("bot.news.httpx.get", return_value=_mock_response(_fixture_bytes(3))):
        items = news.search_news_rss("niacinamide", lookback_days=3, max_items=5, hl="en-IN", gl="IN", ceid="IN:en")

    assert len(items) == 1  # the near-duplicate is deduped, the old one is filtered out
    assert items[0].headline == "Niacinamide pH stability explained"
    assert items[0].source == "Vogue India"


def test_filters_items_older_than_lookback_window():
    with patch("bot.news.httpx.get", return_value=_mock_response(_fixture_bytes(3))):
        items = news.search_news_rss("niacinamide", lookback_days=3, max_items=5, hl="en-IN", gl="IN", ceid="IN:en")
    assert all("Old" not in item.headline for item in items)


def test_caps_at_max_items():
    now = datetime.now(timezone.utc)
    items_xml = "".join(
        f'<item><title>Story {i} - Source {i}</title><link>https://example.com/{i}</link>'
        f'<pubDate>{_rfc822(now - timedelta(hours=i))}</pubDate><source url="https://s{i}.com">Source {i}</source></item>'
        for i in range(10)
    )
    xml = f'<?xml version="1.0"?><rss version="2.0"><channel>{items_xml}</channel></rss>'.encode("utf-8")

    with patch("bot.news.httpx.get", return_value=_mock_response(xml)):
        items = news.search_news_rss("skincare", lookback_days=14, max_items=3, hl="en-IN", gl="IN", ceid="IN:en")
    assert len(items) == 3


def test_timeout_returns_empty_list_without_raising():
    with patch("bot.news.httpx.get", side_effect=httpx.TimeoutException("timed out")):
        items = news.search_news_rss("niacinamide", lookback_days=3, max_items=5, hl="en-IN", gl="IN", ceid="IN:en")
    assert items == []


def test_non_200_returns_empty_list_without_raising():
    with patch("bot.news.httpx.get", return_value=_mock_response(b"", status_code=500)):
        items = news.search_news_rss("niacinamide", lookback_days=3, max_items=5, hl="en-IN", gl="IN", ceid="IN:en")
    assert items == []


def test_malformed_xml_returns_empty_list_without_raising():
    with patch("bot.news.httpx.get", return_value=_mock_response(b"this is not xml at all <<<")):
        items = news.search_news_rss("niacinamide", lookback_days=3, max_items=5, hl="en-IN", gl="IN", ceid="IN:en")
    assert items == []


def test_url_encodes_topic_with_spaces_ampersand_and_non_ascii():
    captured = {}

    def fake_get(url, timeout):
        captured["url"] = url
        return _mock_response(b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>')

    with patch("bot.news.httpx.get", side_effect=fake_get):
        news.search_news_rss("pH & skincare café", lookback_days=3, max_items=5, hl="en-IN", gl="IN", ceid="IN:en")

    url = captured["url"]
    assert "pH+%26+skincare+caf" in url  # space -> +, & -> %26, non-ascii percent-encoded
    assert "+when:3d" in url
    assert "hl=en-IN&gl=IN&ceid=IN:en" in url


def test_feedparser_never_makes_its_own_network_call():
    """search_news_rss must hand feedparser raw bytes, never a URL string —
    otherwise feedparser would try to fetch it itself."""
    with patch("bot.news.httpx.get", return_value=_mock_response(_fixture_bytes(3))) as mock_get, patch(
        "bot.news.feedparser.parse"
    ) as mock_parse:
        mock_parse.return_value = MagicMock(bozo=False, entries=[])
        news.search_news_rss("niacinamide", lookback_days=3, max_items=5, hl="en-IN", gl="IN", ceid="IN:en")

    mock_get.assert_called_once()
    parse_arg = mock_parse.call_args[0][0]
    assert isinstance(parse_arg, bytes)
