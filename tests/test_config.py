from __future__ import annotations

from pathlib import Path

import pytest

from kindle_send.config import Config, ConfigError, load_config, save_config


def _sample(**overrides: object) -> Config:
    data = dict(
        kindle_email="me@kindle.com",
        gmail_address="me@gmail.com",
        gmail_app_password="abcdefghijklmnop",
    )
    data.update(overrides)
    return Config(**data)  # type: ignore[arg-type]


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = _sample(smtp_host="smtp.example.com", smtp_port=587)
    save_config(original, path)

    loaded = load_config(path)
    assert loaded == original
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_escapes_quotes_and_backslashes(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = _sample(gmail_app_password=r'ab"c\defghijklmn')
    save_config(original, path)
    loaded = load_config(path)
    assert loaded is not None
    assert loaded.gmail_app_password == r'ab"c\defghijklmn'


def test_strips_spaces_from_app_password(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'kindle_email = "me@kindle.com"\n'
        'gmail_address = "me@gmail.com"\n'
        'gmail_app_password = "abcd efgh ijkl mnop"\n',
        encoding="utf-8",
    )
    loaded = load_config(path)
    assert loaded is not None
    assert loaded.gmail_app_password == "abcdefghijklmnop"


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.toml") is None


def test_incomplete_config_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('kindle_email = "me@kindle.com"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="incomplete"):
        load_config(path)


def test_invalid_toml_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("this is not toml {", encoding="utf-8")
    with pytest.raises(ConfigError, match="Failed to read"):
        load_config(path)
