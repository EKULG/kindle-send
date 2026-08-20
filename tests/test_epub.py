from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

from lxml import html as lxml_html
from PIL import Image

from kindle_send.epub import (
    _best_srcset_url,
    _pick_image_url,
    build_epub,
    safe_filename,
)
from kindle_send.extract import Article


def test_safe_filename_strips_punctuation_and_limits_length() -> None:
    assert safe_filename("Hello, World!") == "hello-world"
    assert safe_filename("   ") == "article"
    assert len(safe_filename("a" * 200)) == 80


def test_build_epub_without_images(tmp_path: Path) -> None:
    article = Article(
        url="https://example.com/essay",
        title="An Essay",
        html="<p>Hello &amp; welcome.</p><p>Second paragraph.</p>",
        author="Jane Doe",
        site_name="Example",
        description="A short essay.",
    )
    path = build_epub(article, tmp_path / "essay.epub", include_images=False)
    assert path.is_file()

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert any(name.endswith("article.xhtml") for name in names)
        assert any(name.endswith("title.xhtml") for name in names)
        article_xml = next(n for n in names if n.endswith("article.xhtml"))
        body = zf.read(article_xml).decode("utf-8")
        assert "Hello" in body
        assert "<img" not in body.lower()


def test_build_epub_embeds_data_uri_image(tmp_path: Path) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 30, 30)).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    article = Article(
        url="https://example.com/pic",
        title="With Image",
        html=f'<p>See below.</p><img src="data:image/png;base64,{b64}" alt="red">',
    )
    path = build_epub(article, tmp_path / "pic.epub", include_images=True)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert any("/img_001.jpg" in name or name.endswith("img_001.jpg") for name in names)
        article_xml = next(n for n in names if n.endswith("article.xhtml"))
        body = zf.read(article_xml).decode("utf-8")
        assert "images/img_001.jpg" in body
        assert "data:image" not in body


def test_best_srcset_picks_near_max_width() -> None:
    srcset = (
        "https://ex.com/a.jpg 400w, "
        "https://ex.com/b.jpg 800w, "
        "https://ex.com/c.jpg 1600w"
    )
    assert _best_srcset_url(srcset) == "https://ex.com/b.jpg"


def test_pick_image_url_prefers_srcset_and_skips_placeholders() -> None:
    frag = lxml_html.fragment_fromstring(
        '<div><img src="https://example.com/spacer.gif" '
        'data-src="https://cdn.example.com/real.jpg" '
        'srcset="https://cdn.example.com/h-400.jpg 400w, '
        'https://cdn.example.com/h-800.jpg 800w"></div>',
        create_parent=False,
    )
    img = frag.xpath(".//img")[0]
    assert (
        _pick_image_url(img, "https://example.com/article")
        == "https://cdn.example.com/h-800.jpg"
    )


def test_pick_image_url_resolves_relative_srcset() -> None:
    frag = lxml_html.fragment_fromstring(
        '<div><img srcset="/img/400.jpg 400w, /img/800.jpg 800w"></div>',
        create_parent=False,
    )
    img = frag.xpath(".//img")[0]
    assert (
        _pick_image_url(img, "https://example.com/posts/hi")
        == "https://example.com/img/800.jpg"
    )
