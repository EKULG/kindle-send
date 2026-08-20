"""Build a Kindle-friendly EPUB from an extracted article."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

import requests
from ebooklib import epub
from lxml import html as lxml_html
from PIL import Image

from kindle_send.extract import Article, USER_AGENT


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
IMAGE_TIMEOUT = 15


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
        body_html, image_items = _embed_images(body_html)
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


def _embed_images(html: str) -> tuple[str, list[epub.EpubItem]]:
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
        src = (img.get("src") or "").strip()
        if not src or src.startswith("data:"):
            if src.startswith("data:") and len(src) > 200_000:
                img.drop_tree()
            continue

        if src in seen:
            img.set("src", seen[src])
            continue

        processed = _download_and_process_image(src)
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
        for attr in ("srcset", "sizes", "loading", "decoding", "data-src"):
            if attr in img.attrib:
                del img.attrib[attr]

    body = "".join(
        lxml_html.tostring(child, encoding="unicode", method="html")
        for child in wrapper
    )
    return body, items


def _download_and_process_image(
    url: str,
) -> Optional[tuple[bytes, str, str]]:
    headers = {"User-Agent": USER_AGENT, "Accept": "image/*,*/*"}
    try:
        response = requests.get(url, headers=headers, timeout=IMAGE_TIMEOUT, stream=True)
        response.raise_for_status()
        raw = response.content
    except requests.RequestException:
        return None

    if not raw or len(raw) > MAX_IMAGE_BYTES * 4:
        return None

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
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
