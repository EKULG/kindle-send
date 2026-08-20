"""Send an EPUB to a Kindle address via SMTP."""

from __future__ import annotations

import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from kindle_send.config import Config


class MailError(Exception):
    """Raised when the EPUB cannot be emailed to Kindle."""


def send_epub(
    config: Config,
    epub_path: Path | str,
    *,
    subject: str | None = None,
) -> None:
    """Email *epub_path* as an attachment to the configured Kindle address."""
    epub_path = Path(epub_path)
    if not epub_path.is_file():
        raise MailError(f"EPUB not found: {epub_path}")

    filename = epub_path.name
    msg = MIMEMultipart()
    msg["From"] = config.gmail_address
    msg["To"] = config.kindle_email
    msg["Subject"] = subject or filename

    msg.attach(
        MIMEText(
            "Sent by kindle-send. Convert this document for Kindle reading.",
            "plain",
            "utf-8",
        )
    )

    with epub_path.open("rb") as fh:
        attachment = MIMEApplication(fh.read(), _subtype="epub+zip")
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attachment)

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(
            config.smtp_host, config.smtp_port, context=context, timeout=60
        ) as server:
            server.login(config.gmail_address, config.gmail_app_password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "Gmail authentication failed. Check that you're using an App Password "
            "(not your normal Gmail password) and that 2-Step Verification is enabled."
        ) from exc
    except smtplib.SMTPException as exc:
        raise MailError(f"Failed to send email: {exc}") from exc
    except OSError as exc:
        raise MailError(f"Could not connect to SMTP server: {exc}") from exc
