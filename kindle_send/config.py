"""Load and save kindle-send configuration."""

from __future__ import annotations

import getpass
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore


CONFIG_DIR = Path.home() / ".config" / "kindle-send"
CONFIG_PATH = CONFIG_DIR / "config.toml"


@dataclass
class Config:
    kindle_email: str
    gmail_address: str
    gmail_app_password: str
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


def load_config(path: Path = CONFIG_PATH) -> Optional[Config]:
    if not path.exists():
        return None
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception as exc:
        raise ConfigError(f"Failed to read config at {path}: {exc}") from exc

    try:
        return Config(
            kindle_email=str(data["kindle_email"]).strip(),
            gmail_address=str(data["gmail_address"]).strip(),
            gmail_app_password=str(data["gmail_app_password"]).strip().replace(" ", ""),
            smtp_host=str(data.get("smtp_host", "smtp.gmail.com")),
            smtp_port=int(data.get("smtp_port", 465)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(
            f"Config at {path} is incomplete. Run `kindle-send --configure`."
        ) from exc


def save_config(config: Config, path: Path = CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f'kindle_email = "{_escape_toml(config.kindle_email)}"\n'
        f'gmail_address = "{_escape_toml(config.gmail_address)}"\n'
        f'gmail_app_password = "{_escape_toml(config.gmail_app_password)}"\n'
        f'smtp_host = "{_escape_toml(config.smtp_host)}"\n'
        f"smtp_port = {int(config.smtp_port)}\n"
    )
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def interactive_setup(path: Path = CONFIG_PATH) -> Config:
    """Prompt the user for Kindle/Gmail settings and save them."""
    print("kindle-send first-time setup")
    print("----------------------------")
    print(
        "You need:\n"
        "  1. Your Send-to-Kindle email (Amazon → Manage Your Content & Devices\n"
        "     → Preferences → Personal Document Settings)\n"
        "  2. A Gmail address that is on Amazon's Approved Personal Document E-mail List\n"
        "  3. A Gmail App Password (Google Account → Security → 2-Step Verification\n"
        "     → App passwords)\n"
    )

    existing = load_config(path) if path.exists() else None

    kindle_email = _prompt(
        "Kindle email",
        default=existing.kindle_email if existing else None,
        validator=_looks_like_email,
    )
    gmail_address = _prompt(
        "Gmail address (sender)",
        default=existing.gmail_address if existing else None,
        validator=_looks_like_email,
    )
    gmail_app_password = _prompt(
        "Gmail app password",
        default=None,
        secret=True,
        validator=lambda s: len(s.replace(" ", "")) >= 16,
        hint="16 characters from Google App Passwords",
    )

    config = Config(
        kindle_email=kindle_email,
        gmail_address=gmail_address,
        gmail_app_password=gmail_app_password.replace(" ", ""),
    )
    saved = save_config(config, path)
    print(f"\nSaved config to {saved}")
    return config


def ensure_config(path: Path = CONFIG_PATH, *, force_setup: bool = False) -> Config:
    if force_setup:
        return interactive_setup(path)
    config = load_config(path)
    if config is None:
        if not sys.stdin.isatty():
            raise ConfigError(
                f"No config found at {path}. Run `kindle-send --configure` in a terminal."
            )
        return interactive_setup(path)
    return config


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _looks_like_email(value: str) -> bool:
    return "@" in value and "." in value.split("@")[-1]


def _prompt(
    label: str,
    *,
    default: Optional[str] = None,
    secret: bool = False,
    validator=None,
    hint: Optional[str] = None,
) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        prompt = f"{label}{suffix}: "
        if secret:
            value = getpass.getpass(prompt)
        else:
            value = input(prompt).strip()
        if not value and default:
            value = default
        if value and (validator is None or validator(value)):
            return value
        if hint:
            print(f"  Invalid value. {hint}")
        else:
            print("  Invalid value, please try again.")
