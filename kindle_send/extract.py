"""Fetch a URL and extract the main article content."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
from xml.sax.saxutils import escape

import requests
import trafilatura
from lxml import html as lxml_html
from trafilatura.settings import use_config


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

MAX_HTML_BYTES = 15 * 1024 * 1024
_CHUNK_SIZE = 64 * 1024


@dataclass
class Article:
    """Extracted article content and metadata."""

    url: str
    title: str
    html: str
    author: Optional[str] = None
    date: Optional[str] = None
    site_name: Optional[str] = None
    description: Optional[str] = None


class ExtractionError(Exception):
    """Raised when article content cannot be extracted from a URL."""


def _read_capped(response: requests.Response, max_bytes: int) -> Optional[bytes]:
    """Read a response body, aborting if it exceeds *max_bytes*."""
    buf = io.BytesIO()
    for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
        if not chunk:
            continue
        buf.write(chunk)
        if buf.tell() > max_bytes:
            return None
    return buf.getvalue()


def _fetch_html(url: str, timeout: int = 30) -> tuple[bytes, str]:
    """Download *url* as bytes and return ``(body, final_url)`` after redirects."""
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    try:
        with requests.get(url, headers=headers, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            content_length = response.headers.get("Content-Length")
            if content_length and content_length.isdigit() and int(content_length) > MAX_HTML_BYTES:
                raise ExtractionError(
                    f"Page is too large to extract ({int(content_length)} bytes)"
                )
            raw = _read_capped(response, MAX_HTML_BYTES)
            final_url = response.url
    except ExtractionError:
        raise
    except requests.RequestException as exc:
        raise ExtractionError(f"Failed to fetch URL: {exc}") from exc

    if raw is None:
        raise ExtractionError(
            f"Page is too large to extract (over {MAX_HTML_BYTES} bytes)"
        )

    looks_html = "html" in content_type.lower() or raw.lstrip()[:64].startswith(b"<")
    if not looks_html:
        raise ExtractionError(
            f"URL does not appear to be an HTML page (Content-Type: {content_type or 'unknown'})"
        )

    return raw, final_url


def _as_fragment(html: str, base_url: str) -> str:
    """Normalize extracted HTML to a body fragment with absolute URLs."""
    try:
        doc = lxml_html.document_fromstring(html)
    except Exception:
        try:
            doc = lxml_html.fromstring(html)
        except Exception:
            return html

    doc.make_links_absolute(base_url, resolve_base_href=True)

    bodies = doc.xpath("//body")
    if bodies:
        inner = "".join(
            lxml_html.tostring(child, encoding="unicode", method="html")
            for child in bodies[0]
        )
        if inner.strip():
            return inner

    # Element tree without a body wrapper
    if doc.tag.lower() == "html":
        return "".join(
            lxml_html.tostring(child, encoding="unicode", method="html")
            for child in doc
        )

    return lxml_html.tostring(doc, encoding="unicode", method="html")


def extract_article(url: str, title_override: Optional[str] = None) -> Article:
    """Fetch *url* and extract the main article body plus metadata.

    Raises:
        ExtractionError: if the page cannot be fetched or yields no article text.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ExtractionError(f"Invalid URL (expected http/https): {url}")

    downloaded, canonical_url = _fetch_html(url)

    config = use_config()
    config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")

    # Metadata pass (plain text / Document fields)
    meta = trafilatura.bare_extraction(
        downloaded,
        url=canonical_url,
        include_comments=False,
        include_tables=True,
        include_images=True,
        include_links=True,
        config=config,
        with_metadata=True,
    )

    title = author = date = site_name = description = None
    if meta is not None:
        title = getattr(meta, "title", None) or (
            meta.get("title") if isinstance(meta, dict) else None
        )
        author = getattr(meta, "author", None) or (
            meta.get("author") if isinstance(meta, dict) else None
        )
        date = getattr(meta, "date", None) or (
            meta.get("date") if isinstance(meta, dict) else None
        )
        site_name = getattr(meta, "sitename", None) or (
            meta.get("sitename") if isinstance(meta, dict) else None
        )
        description = getattr(meta, "description", None) or (
            meta.get("description") if isinstance(meta, dict) else None
        )

    # HTML body pass — real <img>/<p>/<h*> markup for EPUB
    body_html = trafilatura.extract(
        downloaded,
        url=canonical_url,
        include_comments=False,
        include_tables=True,
        include_images=True,
        include_links=True,
        output_format="html",
        config=config,
    )

    if not body_html or not body_html.strip():
        # Last resort: plain text wrapped in paragraphs
        plain = trafilatura.extract(
            downloaded,
            url=canonical_url,
            include_comments=False,
            config=config,
        )
        if plain and plain.strip():
            body_html = _paragraphs_from_plain(plain)

    if not body_html or not body_html.strip():
        raise ExtractionError(
            "Could not extract article content. The page may be paywalled, "
            "JavaScript-rendered, or not an article."
        )

    body_html = _as_fragment(body_html, canonical_url)
    if not body_html.strip():
        raise ExtractionError(
            "Could not extract article content. The page may be paywalled, "
            "JavaScript-rendered, or not an article."
        )

    final_title = (title_override or title or _fallback_title(canonical_url)).strip()
    if not final_title:
        final_title = "Untitled Article"

    return Article(
        url=canonical_url,
        title=final_title,
        html=body_html,
        author=author,
        date=date,
        site_name=site_name,
        description=description,
    )


def _paragraphs_from_plain(plain: str) -> str:
    """Wrap plain text lines in escaped ``<p>`` tags for XHTML."""
    return "".join(
        f"<p>{escape(line)}</p>" for line in plain.splitlines() if line.strip()
    )


def _fallback_title(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    if path:
        slug = path.split("/")[-1].replace("-", " ").replace("_", " ")
        return slug.title() if slug else url
    return url
