"""S1a 非流式 golden：证明 anthropic 透传路径「不改 body」的非流式行为字节级不变。
只覆盖非 rewrite body 路径：passthrough JSON + thinking-bearing passthrough + 上游错误码
401/429/502。rewrite body 的等价由 test_anthropic_compat 的固定 nonce 接口单测覆盖。
mock 上游（零真实上游花费，守铁律 4）。

录制/回放：CSSWITCH_GOLDEN_RECORD=1 时把捕获写进 fixture（基线一次性录制）；否则读 fixture 比对。
fixture = test/golden/anthropic_nonstream.json：case -> {status, content_type, content_length, body}。
不录 Date 等动态头。不变式：content_length == len(body)。
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from _capability import loopback_available
from mock_upstream import start_mock

HERE = os.path.dirname(__file__)
PROXY = os.path.join(HERE, "..", "proxy", "csswitch_proxy.py")
FIXTURE = os.path.join(HERE, "golden", "anthropic_nonstream.json")
SEC = "goldentok"
PORT_OK = 18977   # S0 全局唯一端口：golden 成功路径
PORT_ERR = 18978  # S0 全局唯一端口：golden 错误路径（各错误码顺序复用）

# 请求矩阵（全部 shim off、非流式、无工具 → 不触发 DSML rewrite）。
CASES = {
    "basic": {"model": "claude-opus-4-8", "max_tokens": 100,
              "messages": [{"role": "user", "content": "hi"}]},
    "with_thinking": {"model": "claude-opus-4-8", "max_tokens": 100,
                      "thinking": {"type": "auto"},
                      "messages": [{"role": "user", "content": "hi"}]},
}
# 上游错误码矩阵：mock 返回 status:NNN，代理映射（401/429 透传，500→502）。
ERROR_CASES = {
    "upstream_401": ("status:401", 401),
    "upstream_429": ("status:429", 429),
    "upstream_500_maps_502": ("status:500", 502),
}


def _raw_post(port, path, body):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    req = (f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
           f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
           f"Connection: close\r\n\r\n").encode() + body
    s.sendall(req)
    chunks = []
    while True:
        d = s.recv(65536)
        if not d:
            break
        chunks.append(d)
    s.close()
    return b"".join(chunks)


def _parse(raw):
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = int(lines[0].split()[1])
    hdrs = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(b":")
        hdrs[k.strip().lower().decode()] = v.strip().decode()
    return status, hdrs, body


def _launch(port, upstream):
    env = dict(os.environ, DEEPSEEK_API_KEY="fake", CSSWITCH_UPSTREAM_URL=upstream)
    env.pop("CSSWITCH_TOOLUSE_SHIM", None)   # 默认 off
    proc = subprocess.Popen(
        [sys.executable, PROXY, "--provider", "deepseek", "--port", str(port),
         "--auth-token", SEC],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            if _raw_post(port, f"/{SEC}/v1/messages", b'{"messages":[]}'):
                break
        except OSError:
            time.sleep(0.1)
    time.sleep(0.3)
    return proc


@unittest.skipUnless(loopback_available(), "env-blocked: loopback bind/connect not permitted")
class AnthropicNonstreamGolden(unittest.TestCase):
    def _cap(self, name, status, hdrs, resp):
        self.assertEqual(len(resp), int(hdrs["content-length"]),
                         f"{name}: content-length 不变式")
        return {"status": status, "content_type": hdrs.get("content-type"),
                "content_length": int(hdrs["content-length"]),
                "body": resp.decode("utf-8", "replace")}

    def test_golden(self):
        record = os.environ.get("CSSWITCH_GOLDEN_RECORD") == "1"
        captured = {}
        # 成功路径：共用一个 json mock + 一个代理。
        up_url, _hits, shutdown = start_mock("json")
        proc = _launch(PORT_OK, up_url)
        try:
            for name, body in CASES.items():
                status, hdrs, resp = _parse(
                    _raw_post(PORT_OK, f"/{SEC}/v1/messages", json.dumps(body).encode()))
                self.assertEqual(status, 200, f"{name}: 成功应 200")
                captured[name] = self._cap(name, status, hdrs, resp)
        finally:
            proc.terminate(); proc.wait(timeout=5); shutdown()
        # 错误路径：每种状态码一个 mock + 代理（顺序复用 PORT_ERR）。
        for name, (mode, want) in ERROR_CASES.items():
            up_url, _hits, shutdown = start_mock(mode)
            proc = _launch(PORT_ERR, up_url)
            try:
                status, hdrs, resp = _parse(
                    _raw_post(PORT_ERR, f"/{SEC}/v1/messages",
                              json.dumps(CASES["basic"]).encode()))
            finally:
                proc.terminate(); proc.wait(timeout=5); shutdown()
            self.assertEqual(status, want, f"{name}: 状态码映射")
            captured[name] = self._cap(name, status, hdrs, resp)

        if record:
            os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
            with open(FIXTURE, "w") as f:
                json.dump(captured, f, ensure_ascii=False, indent=2, sort_keys=True)
            self.skipTest("golden 已录制（CSSWITCH_GOLDEN_RECORD=1），跳过比对")
        with open(FIXTURE) as f:
            expected = json.load(f)
        self.assertEqual(captured, expected)


if __name__ == "__main__":
    unittest.main()
