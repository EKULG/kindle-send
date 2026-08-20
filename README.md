# kindle-send

Extract a web article from any URL and send it to your Kindle as an EPUB.

```bash
kindle-send https://www.paulgraham.com/greatwork.html
```

Not affiliated with Amazon or Google.

## How it works

1. Fetches the page and extracts the main article (via [trafilatura](https://github.com/adbar/trafilatura))
2. Builds a self-contained EPUB with title, author, and images (via [ebooklib](https://github.com/aerkalov/ebooklib))
3. Emails the EPUB to your `@kindle.com` address through Gmail SMTP
4. Amazon converts it and delivers it to your Kindle library

## Install

Requires Python 3.10+. [`pipx`](https://pipx.pypa.io/) is the simplest way to install a CLI.

From GitHub:

```bash
pipx install git+https://github.com/EKULG/kindle-send.git
```

From a clone of this repository:

```bash
pipx install .
```

Or with a virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

`python -m kindle_send` works as well as the `kindle-send` command.

## One-time setup

### 1. Gmail App Password

1. Enable [2-Step Verification](https://myaccount.google.com/signinoptions/twosv) on your Google account
2. Create an [App Password](https://myaccount.google.com/apppasswords) (select Mail / Other)
3. Copy the 16-character password

### 2. Amazon Send-to-Kindle

1. Open [Manage Your Content & Devices](https://www.amazon.com/hz/mycd/digital-console/accountsettings) → **Preferences** → **Personal Document Settings**
2. Note your **Send-to-Kindle Email** (e.g. `yourname@kindle.com`)
3. Under **Approved Personal Document E-mail List**, add the Gmail address you will send from

### 3. Configure kindle-send

```bash
kindle-send --configure
```

Credentials are stored at `~/.config/kindle-send/config.toml` (mode `600`). That file holds your Gmail app password in plaintext — keep it out of this repo, and revoke the app password in your Google account if it ever leaks.

## Usage

```bash
# Extract, build EPUB, email to Kindle
kindle-send https://example.com/essay

# Override the title
kindle-send https://example.com/essay --title "My Custom Title"

# Text only (no images)
kindle-send https://example.com/essay --no-images

# Preview locally without sending
kindle-send https://example.com/essay --dry-run
kindle-send https://example.com/essay -o preview.epub
```

## Troubleshooting

**Gmail authentication failed.** Use a Google [App Password](https://myaccount.google.com/apppasswords), not your normal Gmail password. 2-Step Verification must be enabled. If you rotated the app password, run `kindle-send --configure` again (leave the password blank to keep the current one, or paste the new one).

**Email sent, but nothing appears on the Kindle.** Add the sending Gmail address to Amazon’s **Approved Personal Document E-mail List**. Delivery can take a minute or two after Amazon converts the file; the Kindle needs Wi-Fi. Check [Manage Your Content](https://www.amazon.com/hz/mycd/digital-console/) for the document.

**Could not extract article content.** The page is probably paywalled, login-gated, or rendered only in JavaScript. Use `--dry-run` or `-o preview.epub` to inspect what was extracted before sending.

**EPUB is over 50 MB.** Amazon’s Send-to-Kindle email limit is 50 MB. Retry with `--no-images`, or upload the EPUB through [Send to Kindle](https://www.amazon.com/sendtokindle) in a browser (up to 200 MB).

**No config found.** Run `kindle-send --configure` in a terminal. The file is `~/.config/kindle-send/config.toml`.

## Notes

- EPUB is the format Amazon converts most reliably for Send-to-Kindle (reflowable text, fonts, highlights).
- Images are resized automatically so typical articles stay under the email size limit.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

[MIT](LICENSE)
