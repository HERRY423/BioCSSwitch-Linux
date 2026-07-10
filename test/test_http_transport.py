from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
PROXY = ROOT / "proxy"
if str(PROXY) not in sys.path:
    sys.path.insert(0, str(PROXY))

import http_transport  # noqa: E402


def test_one_client_handles_post_get_and_preserves_http_failure_body():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.url.path == "/fail":
            return httpx.Response(429, content=b"rate limited", request=request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [1]}, request=request)
        return httpx.Response(
            200,
            content=b'{"ok":true}',
            headers={"Content-Type": "application/json"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = http_transport.HTTPTransport(client=client)
    body, content_type = transport.post_bytes("https://api.example/ok", b"{}", {})
    assert body == b'{"ok":true}'
    assert content_type == "application/json"
    assert transport.get_json("https://api.example/models", {}) == {"data": [1]}

    with pytest.raises(http_transport.UpstreamHTTPError) as exc:
        transport.post_bytes("https://api.example/fail", b"{}", {}, attempts=4)
    assert exc.value.code == 429
    assert exc.value.read() == b"rate limited"
    assert calls.count(("POST", "https://api.example/fail")) == 1
    transport.close()


def test_stream_adapter_keeps_lines_and_closes_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"event: one\ndata: 1\n\n",
            headers={"Content-Type": "text/event-stream"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = http_transport.HTTPTransport(client=client)
    stream, first, content_type = transport.open_stream("https://api.example/stream", b"{}", {})
    assert first == b"event: one\n"
    assert stream.readline() == b"data: 1\n"
    assert stream.readline() == b"\n"
    assert stream.readline() == b""
    assert content_type == "text/event-stream"
    stream.close()
    transport.close()
