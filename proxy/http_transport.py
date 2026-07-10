"""Shared pooled HTTP transport for proxy upstream calls.

The desktop proxy is long lived, so a new TCP/TLS connection per request is
both slow and wasteful. This module owns one thread-safe ``httpx.Client`` with
connection pooling and enables HTTP/2 when the optional ``h2`` dependency is
installed. HTTP status failures remain distinct from retryable transport
failures so callers can preserve upstream status semantics.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable, Iterator

try:
    import httpx
except ModuleNotFoundError:
    # Release builds bundle pure-Python runtime dependencies beside ``proxy``.
    # Source checkouts normally satisfy them through ``pip install -e .``.
    vendor = Path(__file__).resolve().parents[1] / "python-vendor"
    if vendor.is_dir() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    import httpx


HTTP2_ENABLED = importlib.util.find_spec("h2") is not None
_DEFAULT_USER_AGENT = "CSSwitch/0.3 (+https://github.com/SuperJJ007/CSSwitch)"


class UpstreamHTTPError(Exception):
    """HTTP response failure with a small, repeatably readable body."""

    def __init__(self, status_code: int, body: bytes = b"", reason: str = "") -> None:
        self.status_code = int(status_code)
        self.code = self.status_code
        self.body = bytes(body[:1_048_576])
        self.reason = reason
        suffix = f": {reason}" if reason else ""
        super().__init__(f"upstream HTTP {self.status_code}{suffix}")

    def read(self) -> bytes:
        return self.body


class StreamResponse:
    """Small file-like adapter used by the Anthropic SSE passthrough."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self._iterator: Iterator[bytes] = response.iter_bytes()
        self._buffer = bytearray()
        self._closed = False

    def readline(self, limit: int = 65_536) -> bytes:
        if self._closed:
            return b""
        limit = max(1, int(limit))
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                end = min(newline + 1, limit)
                value = bytes(self._buffer[:end])
                del self._buffer[:end]
                return value
            if len(self._buffer) >= limit:
                value = bytes(self._buffer[:limit])
                del self._buffer[:limit]
                return value
            try:
                chunk = next(self._iterator)
            except StopIteration:
                value = bytes(self._buffer)
                self._buffer.clear()
                return value
            if chunk:
                self._buffer.extend(chunk)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._response.close()

    def __enter__(self) -> "StreamResponse":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()


class HTTPTransport:
    """Pooled HTTP client with bounded retries for transport failures only."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            http2=HTTP2_ENABLED,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            headers={"User-Agent": _DEFAULT_USER_AGENT},
            trust_env=True,
        )

    @staticmethod
    def _raise_status(response: httpx.Response, body: bytes | None = None) -> None:
        if response.status_code >= 400:
            payload = response.content if body is None else body
            raise UpstreamHTTPError(response.status_code, payload, response.reason_phrase)

    @staticmethod
    def _retry(
        operation: Callable[[], Any],
        attempts: int,
        delay: float,
        on_retry: Callable[[int, int, Exception], None] | None,
    ) -> Any:
        attempts = max(1, int(attempts))
        for index in range(attempts):
            try:
                return operation()
            except httpx.TransportError as exc:
                if index >= attempts - 1:
                    raise
                if on_retry:
                    on_retry(index + 1, attempts - 1, exc)
                time.sleep(delay * (index + 1))
        raise RuntimeError("unreachable retry state")

    def post_bytes(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        *,
        attempts: int = 4,
        timeout: float = 300,
        on_retry: Callable[[int, int, Exception], None] | None = None,
    ) -> tuple[bytes, str]:
        def send() -> tuple[bytes, str]:
            response = self.client.post(url, content=data, headers=headers, timeout=timeout)
            self._raise_status(response)
            return response.content, response.headers.get("Content-Type", "application/json")

        return self._retry(send, attempts, 0.8, on_retry)

    def get_json(
        self,
        url: str,
        headers: dict[str, str],
        *,
        attempts: int = 3,
        timeout: float = 30,
        on_retry: Callable[[int, int, Exception], None] | None = None,
    ) -> Any:
        def send() -> Any:
            response = self.client.get(url, headers=headers, timeout=timeout)
            self._raise_status(response)
            return json.loads(response.content)

        return self._retry(send, attempts, 0.6, on_retry)

    def open_stream(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        *,
        attempts: int = 4,
        timeout: float = 300,
        on_retry: Callable[[int, int, Exception], None] | None = None,
    ) -> tuple[StreamResponse, bytes, str]:
        def send() -> tuple[StreamResponse, bytes, str]:
            request = self.client.build_request(
                "POST", url, content=data, headers=headers, timeout=timeout
            )
            response = self.client.send(request, stream=True)
            if response.status_code >= 400:
                try:
                    body = response.read()
                finally:
                    response.close()
                self._raise_status(response, body)
            stream = StreamResponse(response)
            try:
                first = stream.readline(65_536)
                if not first:
                    raise httpx.RemoteProtocolError("upstream returned 200 with an empty body")
                return stream, first, response.headers.get("Content-Type", "application/json")
            except Exception:
                stream.close()
                raise

        return self._retry(send, attempts, 0.8, on_retry)

    def close(self) -> None:
        self.client.close()


_LOCK = threading.Lock()
_DEFAULT: HTTPTransport | None = None


def default_transport() -> HTTPTransport:
    global _DEFAULT
    if _DEFAULT is None:
        with _LOCK:
            if _DEFAULT is None:
                _DEFAULT = HTTPTransport()
    return _DEFAULT


def set_default_transport(transport: HTTPTransport | None) -> None:
    """Replace the singleton; useful for deterministic offline tests."""

    global _DEFAULT
    with _LOCK:
        prior, _DEFAULT = _DEFAULT, transport
    if prior is not None and prior is not transport:
        prior.close()


def close_default_transport() -> None:
    set_default_transport(None)
