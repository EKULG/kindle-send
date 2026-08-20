"""Command-line interface for kindle-send."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from kindle_send import __version__
from kindle_send.config import ConfigError, ensure_config
from kindle_send.epub import build_epub, safe_filename
from kindle_send.extract import ExtractionError, extract_article
from kindle_send.mailer import MailError, send_epub


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kindle-send",
        description="Extract a web article and send it to your Kindle as an EPUB.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="URL of the article, essay, or blog post to send",
    )
    parser.add_argument(
        "--title",
        help="Override the detected article title",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Omit images from the EPUB",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the EPUB locally without emailing it",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write the EPUB to this path without emailing it",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Run interactive setup for Kindle/Gmail credentials",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.configure:
        try:
            ensure_config(force_setup=True)
        except ConfigError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if not args.url:
        parser.error("the following arguments are required: url (or use --configure)")

    print(f"Fetching {args.url} ...")
    try:
        article = extract_article(args.url, title_override=args.title)
    except ExtractionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Extracted: {article.title}")
    if article.author:
        print(f"  Author: {article.author}")
    if article.site_name:
        print(f"  Site:   {article.site_name}")

    include_images = not args.no_images
    # --dry-run or -o alone means: write EPUB, do not email
    send_to_kindle = not args.dry_run and args.output is None

    try:
        if send_to_kindle:
            with tempfile.TemporaryDirectory(prefix="kindle-send-") as tmp:
                tmp_path = Path(tmp) / f"{safe_filename(article.title)}.epub"
                epub_path = build_epub(
                    article, tmp_path, include_images=include_images
                )
                size_kb = epub_path.stat().st_size // 1024
                print(f"Built EPUB ({size_kb} KB)")
                return _send(epub_path, article.title)

        output_path = args.output or Path(f"{safe_filename(article.title)}.epub")
        epub_path = build_epub(article, output_path, include_images=include_images)
        print(f"Wrote EPUB: {epub_path.resolve()}")
        print("Dry run complete — not sending to Kindle.")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error building EPUB: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, MailError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _send(epub_path: Path, title: str) -> int:
    try:
        config = ensure_config()
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Sending to {config.kindle_email} ...")
    try:
        send_epub(config, epub_path, subject=title)
    except MailError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Sent. It should appear in your Kindle library shortly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
