"""Shared test helpers. Tests must not touch the network."""

from __future__ import annotations

from typing import Iterator, Optional


class FakeResponse:
    """Minimal stand-in for ``requests.Response`` used with ``stream=True``."""

    def __init__(
        self,
        content: bytes,
        *,
        url: str = "https://example.com/article",
        status_code: int = 200,
        headers: Optional[dict[str, str]] = None,
        chunks: Optional[list[bytes]] = None,
    ) -> None:
        self._content = content
        self._chunks = chunks
        self.url = url
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} error")

    def iter_content(self, chunk_size: int = 65536) -> Iterator[bytes]:
        if self._chunks is not None:
            yield from self._chunks
            return
        data = self._content
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None
