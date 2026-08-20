"""Build a Kindle-friendly EPUB from an extracted article."""

from __future__ import annotations

import base64
import hashlib
import io
import re
from pathlib import Path
from typing import Optional
from urllib.parse import unquote_to_bytes, urljoin, urlparse
from xml.sax.saxutils import escape

import requests
from ebooklib import epub
from lxml import html as lxml_html
from PIL import Image

from kindle_send.extract import Article, USER_AGENT, _read_capped


KINDLE_CSS = """
body {
  font-family: serif;
  line-height: 1.5;
  margin: 1em;
}
h1 { font-size: 1.6em; margin: 0.8em 0 0.4em; }
h2 { font-size: 1.35em; margin: 0.8em 0 0.4em; }
h3 { font-size: 1.15em; margin: 0.7em 0 0.3em; }
p { margin: 0.6em 0; text-indent: 0; }
blockquote {
  margin: 1em 1.5em;
  font-style: italic;
  border-left: 2px solid #888;
  padding-left: 0.8em;
}
img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 1em auto;
}
pre, code {
  font-family: monospace;
  font-size: 0.9em;
}
pre {
  white-space: pre-wrap;
  background: #f4f4f4;
  padding: 0.6em;
}
ul, ol { margin: 0.6em 0 0.6em 1.4em; }
a { color: inherit; text-decoration: underline; }
.meta { color: #555; font-size: 0.95em; margin: 0.3em 0; }
.source { margin-top: 1.5em; font-size: 0.9em; color: #555; }
"""

MAX_IMAGE_WIDTH = 800
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_DOWNLOAD_BYTES = MAX_IMAGE_BYTES * 4
IMAGE_TIMEOUT = 15
_LAZY_SRC_ATTRS = ("data-src", "data-lazy-src", "data-original", "data-url")
_PLACEHOLDER_HINTS = ("placeholder", "spacer", "1x1", "pixel.gif", "blank.", "transparent")
_IMG_ATTRS_TO_DROP = (
    "srcset",
    "data-srcset",
    "sizes",
    "loading",
    "decoding",
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-url",
)


def build_epub(
    article: Article,
    output_path: Path | str,
    *,
    include_images: bool = True,
) -> Path:
    """Create an EPUB file from *article* and write it to *output_path*."""
    output_path = Path(output_path)

    book = epub.EpubBook()
    book.set_identifier(_article_id(article.url))
    book.set_title(article.title)
    book.set_language("en")

    if article.author:
        book.add_author(article.author)
    if article.description:
        book.add_metadata("DC", "description", article.description)
    book.add_metadata("DC", "source", article.url)

    style = epub.EpubItem(
        uid="style",
        file_name="style/nav.css",
        media_type="text/css",
        content=KINDLE_CSS.encode("utf-8"),
    )
    book.add_item(style)

    body_html = article.html
    if include_images:
        body_html, image_items = _embed_images(body_html, base_url=article.url)
        for item in image_items:
            book.add_item(item)
    else:
        body_html = _strip_images(body_html)

    title_page = epub.EpubHtml(
        title="Title",
        file_name="title.xhtml",
        lang="en",
    )
    title_page.set_content(_title_page_body(article))
    title_page.add_item(style)

    chapter = epub.EpubHtml(
        title=article.title,
        file_name="article.xhtml",
        lang="en",
    )
    chapter.set_content(body_html)
    chapter.add_item(style)

    book.add_item(title_page)
    book.add_item(chapter)
    book.toc = (title_page, chapter)
    book.spine = ["nav", title_page, chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book)
    return output_path


def _article_id(url: str) -> str:
    return "kindle-send-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _title_page_body(article: Article) -> str:
    parts = [f"<h1>{escape(article.title)}</h1>"]
    if article.author:
        parts.append(f'<p class="meta">By {escape(article.author)}</p>')
    if article.date:
        parts.append(f'<p class="meta">{escape(article.date)}</p>')
    if article.site_name:
        parts.append(f'<p class="meta">{escape(article.site_name)}</p>')
    parts.append(
        f'<p class="source">Source: <a href="{escape(article.url)}">'
        f"{escape(article.url)}</a></p>"
    )
    return "".join(parts)


def _strip_images(html: str) -> str:
    try:
        wrapper = lxml_html.fragment_fromstring(f"<div>{html}</div>", create_parent=False)
    except Exception:
        return re.sub(r"<img\b[^>]*>", "", html, flags=re.IGNORECASE)
    for img in wrapper.xpath(".//img"):
        img.drop_tree()
    return "".join(
        lxml_html.tostring(child, encoding="unicode", method="html")
        for child in wrapper
    )


def _embed_images(html: str, *, base_url: str) -> tuple[str, list[epub.EpubItem]]:
    # Wrap fragment so lxml always has a root we can serialize children from
    try:
        wrapper = lxml_html.fragment_fromstring(f"<div>{html}</div>", create_parent=False)
    except Exception:
        try:
            wrapper = lxml_html.fromstring(f"<div>{html}</div>")
        except Exception:
            return html, []

    items: list[epub.EpubItem] = []
    seen: dict[str, str] = {}
    index = 0

    for img in wrapper.xpath(".//img"):
        src = _pick_image_url(img, base_url)
        if not src:
            img.drop_tree()
            continue

        if src in seen:
            img.set("src", seen[src])
            _drop_img_attrs(img)
            continue

        processed = _load_and_process_image(src, referer=base_url)
        if processed is None:
            img.drop_tree()
            continue

        content, ext, media_type = processed
        index += 1
        file_name = f"images/img_{index:03d}.{ext}"
        item = epub.EpubItem(
            uid=f"img_{index:03d}",
            file_name=file_name,
            media_type=media_type,
            content=content,
        )
        items.append(item)
        seen[src] = file_name
        img.set("src", file_name)
        _drop_img_attrs(img)

    body = "".join(
        lxml_html.tostring(child, encoding="unicode", method="html")
        for child in wrapper
    )
    return body, items


def _drop_img_attrs(img) -> None:
    for attr in _IMG_ATTRS_TO_DROP:
        if attr in img.attrib:
            del img.attrib[attr]


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _is_placeholder_url(url: str) -> bool:
    lower = url.lower()
    return any(hint in lower for hint in _PLACEHOLDER_HINTS)


def _best_srcset_url(srcset: str) -> Optional[str]:
    """Pick the srcset candidate closest to MAX_IMAGE_WIDTH."""
    if not srcset:
        return None
    candidates: list[tuple[int, str]] = []
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split()
        candidate_url = bits[0]
        width = 0
        if len(bits) > 1:
            descriptor = bits[1]
            try:
                if descriptor.endswith("w"):
                    width = int(descriptor[:-1])
                elif descriptor.endswith("x"):
                    width = int(float(descriptor[:-1]) * MAX_IMAGE_WIDTH)
            except ValueError:
                width = 0
        candidates.append((width, candidate_url))
    if not candidates:
        return None

    def sort_key(item: tuple[int, str]) -> tuple[int, int, int]:
        width, _url = item
        if width <= 0:
            return (1, 0, 0)
        return (0, abs(width - MAX_IMAGE_WIDTH), -width)

    candidates.sort(key=sort_key)
    return candidates[0][1]


def _pick_image_url(img, base_url: str) -> Optional[str]:
    src = (img.get("src") or "").strip()
    srcset = (img.get("srcset") or img.get("data-srcset") or "").strip()
    lazy = ""
    for attr in _LAZY_SRC_ATTRS:
        lazy = (img.get(attr) or "").strip()
        if lazy:
            break

    http_candidates: list[str] = []
    best_srcset = _best_srcset_url(srcset)
    if best_srcset:
        http_candidates.append(urljoin(base_url, best_srcset))
    if lazy and not lazy.startswith("data:"):
        http_candidates.append(urljoin(base_url, lazy))
    if src and not src.startswith("data:"):
        http_candidates.append(urljoin(base_url, src))

    for candidate in http_candidates:
        if _is_http_url(candidate) and not _is_placeholder_url(candidate):
            return candidate
    for candidate in http_candidates:
        if _is_http_url(candidate):
            return candidate

    if src.startswith("data:image/"):
        return src
    if lazy.startswith("data:image/"):
        return lazy
    return None


def _decode_data_url(src: str) -> Optional[bytes]:
    if not src.startswith("data:") or "," not in src:
        return None
    header, payload = src.split(",", 1)
    try:
        if ";base64" in header.lower():
            return base64.b64decode(payload)
        return unquote_to_bytes(payload)
    except Exception:
        return None


def _download_image(url: str, *, referer: str) -> Optional[bytes]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": referer,
    }
    try:
        with requests.get(url, headers=headers, timeout=IMAGE_TIMEOUT, stream=True) as response:
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if (
                content_length
                and content_length.isdigit()
                and int(content_length) > MAX_IMAGE_DOWNLOAD_BYTES
            ):
                return None
            return _read_capped(response, MAX_IMAGE_DOWNLOAD_BYTES)
    except requests.RequestException:
        return None


def _load_and_process_image(
    url: str,
    *,
    referer: str,
) -> Optional[tuple[bytes, str, str]]:
    if url.startswith("data:"):
        raw = _decode_data_url(url)
    elif _is_http_url(url):
        raw = _download_image(url, referer=referer)
    else:
        return None

    if not raw:
        return None

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
        return None

    if image.width < 8 or image.height < 8:
        return None

    # Convert exotic modes / formats to something Kindle-friendly
    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        alpha = image.split()[-1] if image.mode in ("RGBA", "LA") else None
        if alpha is not None:
            background.paste(image.convert("RGBA"), mask=alpha)
        else:
            background.paste(image.convert("RGB"))
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    if image.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / float(image.width)
        new_size = (MAX_IMAGE_WIDTH, max(1, int(image.height * ratio)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85, optimize=True)
    data = buf.getvalue()
    if len(data) > MAX_IMAGE_BYTES:
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=60, optimize=True)
        data = buf.getvalue()
        if len(data) > MAX_IMAGE_BYTES:
            return None

    return data, "jpg", "image/jpeg"


def safe_filename(title: str) -> str:
    """Turn an article title into a filesystem-safe EPUB basename."""
    name = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip()
    name = re.sub(r"[-\s]+", "-", name)
    return (name[:80] or "article").strip("-").lower()
