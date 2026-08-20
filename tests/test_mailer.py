from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kindle_send.config import Config
from kindle_send.mailer import MailError, send_epub


def _config() -> Config:
    return Config(
        kindle_email="me@kindle.com",
        gmail_address="me@gmail.com",
        gmail_app_password="abcdefghijklmnop",
    )


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(MailError, match="EPUB not found"):
        send_epub(_config(), tmp_path / "missing.epub")


def test_send_epub_logs_in_and_attaches_file(tmp_path: Path) -> None:
    epub_path = tmp_path / "essay.epub"
    epub_path.write_bytes(b"PK fake epub")

    server = MagicMock()
    smtp = MagicMock()
    smtp.__enter__.return_value = server
    smtp.__exit__.return_value = None

    with patch("kindle_send.mailer.smtplib.SMTP_SSL", return_value=smtp) as smtp_cls:
        send_epub(_config(), epub_path, subject="An Essay")

    smtp_cls.assert_called_once()
    server.login.assert_called_once_with("me@gmail.com", "abcdefghijklmnop")
    server.send_message.assert_called_once()
    msg = server.send_message.call_args[0][0]
    assert msg["From"] == "me@gmail.com"
    assert msg["To"] == "me@kindle.com"
    assert msg["Subject"] == "An Essay"
    payloads = [part.get_payload(decode=True) for part in msg.walk()]
    assert b"PK fake epub" in payloads


def test_rejects_oversize_attachment(tmp_path: Path) -> None:
    epub_path = tmp_path / "essay.epub"
    epub_path.write_bytes(b"PK fake epub")
    with patch("kindle_send.mailer.MAX_ATTACHMENT_BYTES", 1):
        with patch("kindle_send.mailer.smtplib.SMTP_SSL") as smtp_cls:
            with pytest.raises(MailError, match="50 MB"):
                send_epub(_config(), epub_path)
            smtp_cls.assert_not_called()
