from __future__ import annotations

from unittest.mock import patch

import pytest

from kindle_send.extract import (
    MAX_HTML_BYTES,
    ExtractionError,
    _paragraphs_from_plain,
    _read_capped,
    extract_article,
)
from tests.helpers import FakeResponse

ARTICLE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Great Work — café</title>
  <meta name="author" content="Paul Graham">
</head>
<body>
  <article>
    <h1>Great Work — café</h1>
    <p>If you collected lists of techniques for doing great work in a bunch
    of different fields, what would you find they had in common?</p>
    <p>{padding}</p>
  </article>
</body>
</html>
""".format(padding="More paragraph text so extraction has enough body. " * 40)


def test_rejects_invalid_urls() -> None:
    with pytest.raises(ExtractionError, match="Invalid URL"):
        extract_article("not-a-url")
    with pytest.raises(ExtractionError, match="Invalid URL"):
        extract_article("ftp://example.com/doc")
    with pytest.raises(ExtractionError, match="Invalid URL"):
        extract_article("https://")


def test_extracts_from_bytes_and_follows_canonical_url() -> None:
    page = FakeResponse(
        ARTICLE_HTML.encode("utf-8"),
        url="https://www.paulgraham.com/greatwork.html",
        headers={"Content-Type": "text/html"},
    )
    with patch("kindle_send.extract.requests.get", return_value=page) as get:
        article = extract_article("https://bit.ly/greatwork")

    get.assert_called_once()
    assert article.url == "https://www.paulgraham.com/greatwork.html"
    assert "café" in article.title or "Great Work" in article.title
    assert "<p>" in article.html
    assert not hasattr(page, "text")


def test_rejects_non_html() -> None:
    page = FakeResponse(
        b"%PDF-1.4 leftover",
        headers={"Content-Type": "application/pdf"},
    )
    with patch("kindle_send.extract.requests.get", return_value=page):
        with pytest.raises(ExtractionError, match="does not appear to be an HTML"):
            extract_article("https://example.com/file.pdf")


def test_rejects_oversize_content_length() -> None:
    page = FakeResponse(
        b"<html></html>",
        headers={
            "Content-Type": "text/html",
            "Content-Length": str(MAX_HTML_BYTES + 1),
        },
    )
    with patch("kindle_send.extract.requests.get", return_value=page):
        with pytest.raises(ExtractionError, match="too large"):
            extract_article("https://example.com/huge")


def test_read_capped_aborts_when_stream_exceeds_limit() -> None:
    page = FakeResponse(b"", chunks=[b"x" * 50, b"y" * 50])
    assert _read_capped(page, max_bytes=75) is None
    page = FakeResponse(b"", chunks=[b"hello", b" world"])
    assert _read_capped(page, max_bytes=100) == b"hello world"


def test_plain_fallback_escapes_html() -> None:
    assert _paragraphs_from_plain("a < b & c > d") == "<p>a &lt; b &amp; c &gt; d</p>"
    assert _paragraphs_from_plain("  \nkeep this\n\n") == "<p>keep this</p>"
