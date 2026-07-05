"""HTTP fixture 回放层 —— 让 bio_eval tool-loop 与 generator golden tests 都能离线跑。

设计：
  - 一个进程内单例 store，`_lib/http.py` 的 `_do()` 在每次请求前问它。
  - fixture 键 = sha1(method \\n canonical_url_with_sorted_params \\n body_sha1)。
    canonical_url 把 query 参数排序，避免顺序影响命中。
  - 三种 mode：
      replay  —— 只回放，未命中就 raise（CI 默认；保证零网络）
      record  —— 真打网络 + 落盘（首次录制用）
      auto    —— 命中回放，未命中真打并落盘（本地补录用）
  - fixture 文件：`<dir>/<key>.json`，含 request 摘要（可读）+ response（status+body）。

安全：
  - 只 JSON 序列化，不 pickle。
  - 录制时**不落 Authorization / api_key** —— 把 params 里的敏感键 redact 成 "<redacted>"，
    URL query 里的 api_key 也抹掉。fixture 进 git，绝不能带 key。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# 录制时要从 params / url 里抹掉的敏感键（大小写不敏感）
_SENSITIVE_KEYS = {"api_key", "apikey", "key", "token", "auth", "authorization",
                   "access_token", "mailto", "email", "tool"}


class _Store:
    def __init__(self):
        self.dir: Optional[Path] = None
        self.mode: str = "off"        # off | replay | record | auto
        self.hits: int = 0
        self.misses: int = 0
        self.recorded: int = 0

    def active(self) -> bool:
        return self.mode != "off" and self.dir is not None


_STORE = _Store()


def _redact_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not params:
        return {}
    out = {}
    for k, v in params.items():
        if k.lower() in _SENSITIVE_KEYS:
            out[k] = "<redacted>"
        else:
            out[k] = v
    return out


def _canonical_url(url: str, params: Optional[Dict[str, Any]]) -> str:
    """把 url + params 归一：抹敏感键、排序、拼回。也处理 url 内嵌 query。"""
    parsed = urllib.parse.urlsplit(url)
    merged: Dict[str, Any] = {}
    # url 内嵌的 query
    for k, vals in urllib.parse.parse_qs(parsed.query).items():
        merged[k] = vals[0] if len(vals) == 1 else vals
    # 传入的 params 覆盖
    for k, v in (params or {}).items():
        merged[k] = v
    # 抹敏感键
    for k in list(merged.keys()):
        if k.lower() in _SENSITIVE_KEYS:
            merged[k] = "<redacted>"
    canon_q = urllib.parse.urlencode(sorted(merged.items()), doseq=True)
    base = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return base + ("?" + canon_q if canon_q else "")


def _key(method: str, url: str, params: Optional[Dict[str, Any]], body: Optional[bytes]) -> str:
    canon = _canonical_url(url, params)
    body_sha = hashlib.sha1(body or b"").hexdigest()
    raw = f"{method.upper()}\n{canon}\n{body_sha}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def activate(fixture_dir: str | os.PathLike, mode: str = "replay") -> None:
    if mode not in ("off", "replay", "record", "auto"):
        raise ValueError(f"bad fixture mode: {mode}")
    _STORE.dir = Path(fixture_dir)
    _STORE.mode = mode
    _STORE.hits = _STORE.misses = _STORE.recorded = 0
    if mode in ("record", "auto"):
        _STORE.dir.mkdir(parents=True, exist_ok=True)


def deactivate() -> None:
    _STORE.mode = "off"
    _STORE.dir = None


def activate_from_env() -> None:
    """从环境变量自动激活：CSSWITCH_HTTP_FIXTURES=<dir>, CSSWITCH_HTTP_FIXTURE_MODE=replay|auto|record"""
    d = os.environ.get("CSSWITCH_HTTP_FIXTURES")
    if d:
        activate(d, os.environ.get("CSSWITCH_HTTP_FIXTURE_MODE", "replay"))


def stats() -> Dict[str, int]:
    return {"hits": _STORE.hits, "misses": _STORE.misses, "recorded": _STORE.recorded}


class FixtureMiss(Exception):
    """replay 模式下未命中 —— 提示需要先 record。"""


def try_replay(method: str, url: str, params: Optional[Dict[str, Any]],
               body: Optional[bytes]) -> Optional[bytes]:
    """回放阶段。命中返回 body bytes；未命中在 replay 模式 raise，其它模式返回 None（交给真网络）。"""
    if not _STORE.active():
        return None
    key = _key(method, url, params, body)
    fpath = _STORE.dir / f"{key}.json"
    if fpath.is_file():
        try:
            rec = json.loads(fpath.read_text("utf-8"))
            _STORE.hits += 1
            return (rec.get("response_body") or "").encode("utf-8")
        except Exception:
            pass
    _STORE.misses += 1
    if _STORE.mode == "replay":
        raise FixtureMiss(
            f"fixture 未命中：{method} {_canonical_url(url, params)}\n"
            f"key={key}\n用 --record 或 CSSWITCH_HTTP_FIXTURE_MODE=auto 先录制。"
        )
    return None  # record / auto 模式下交给真网络


def record(method: str, url: str, params: Optional[Dict[str, Any]],
           body: Optional[bytes], response_bytes: bytes) -> None:
    """record / auto 模式：把真实响应落盘（脱敏）。"""
    if not _STORE.active() or _STORE.mode not in ("record", "auto"):
        return
    key = _key(method, url, params, body)
    fpath = _STORE.dir / f"{key}.json"
    rec = {
        "_note": "CSSwitch bio fixture — 脱敏后可入 git，绝不含真实 key",
        "request": {
            "method": method.upper(),
            "canonical_url": _canonical_url(url, params),
            "params_redacted": _redact_params(params),
            "body_sha1": hashlib.sha1(body or b"").hexdigest(),
        },
        "response_body": response_bytes.decode("utf-8", "replace"),
    }
    fpath.write_text(json.dumps(rec, ensure_ascii=False, indent=2), "utf-8")
    try:
        os.chmod(fpath, 0o644)  # fixture 不含 key，可读
    except Exception:
        pass
    _STORE.recorded += 1
