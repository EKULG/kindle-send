from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import patch

import pytest

from kindle_send import __version__
from kindle_send.cli import main
from kindle_send.extract import Article, ExtractionError


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_requires_url() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_dry_run_writes_epub(tmp_path: Path) -> None:
    article = Article(
        url="https://example.com/essay",
        title="Hello World",
        html="<p>Body text for the essay.</p>",
        author="Author",
    )
    out = tmp_path / "out.epub"
    with patch("kindle_send.cli.extract_article", return_value=article):
        rc = main(["https://example.com/essay", "--dry-run", "-o", str(out)])
    assert rc == 0
    assert out.is_file()


def test_extraction_error_returns_one() -> None:
    with patch(
        "kindle_send.cli.extract_article",
        side_effect=ExtractionError("nope"),
    ):
        assert main(["https://example.com/essay"]) == 1


def test_keyboard_interrupt_returns_130() -> None:
    with patch(
        "kindle_send.cli.extract_article",
        side_effect=KeyboardInterrupt,
    ):
        assert main(["https://example.com/essay"]) == 130


def test_python_module_entrypoint_version(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sys.argv", ["kindle-send", "--version"]):
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("kindle_send", run_name="__main__")
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out
