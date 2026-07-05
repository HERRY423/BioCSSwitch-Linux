"""磁盘缓存：文献元数据类查询是幂等的（PMID 不会变），
凭引用做验证时缓存能把「大量重复 PMID 查询」压成 1 次 → 上游更善待、答复更快。

存放位置：$CSSWITCH_CACHE_DIR/<namespace>/<sha1(key)>.json，默认
`~/.csswitch/cache/`。目录不存在则透明降级为不缓存（不抛异常干扰主流程）。

安全：
  - 只 JSON 序列化（不 pickle，避免被恶意缓存文件反序列化攻击）。
  - 键先 sha1，避免特殊字符 / 长键触发文件名限制。
  - TTL 到期不删文件、只忽略（避免并发写竞态）。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional


def _base_dir() -> Optional[Path]:
    root = os.environ.get("CSSWITCH_CACHE_DIR")
    if root:
        return Path(root)
    home = os.environ.get("HOME")
    if not home:
        return None
    return Path(home) / ".csswitch" / "cache"


def _path(namespace: str, key: str) -> Optional[Path]:
    base = _base_dir()
    if base is None:
        return None
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return base / namespace / f"{h}.json"


def get(namespace: str, key: str, ttl_seconds: int = 24 * 3600) -> Optional[Any]:
    p = _path(namespace, key)
    if p is None or not p.is_file():
        return None
    try:
        obj = json.loads(p.read_text("utf-8"))
    except Exception:
        return None
    if not isinstance(obj, dict) or "ts" not in obj or "v" not in obj:
        return None
    if time.time() - obj["ts"] > ttl_seconds:
        return None
    return obj["v"]


def put(namespace: str, key: str, value: Any) -> None:
    p = _path(namespace, key)
    if p is None:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ts": time.time(), "v": value}, ensure_ascii=False), "utf-8")
        tmp.replace(p)
    except Exception:
        # 缓存写失败绝不影响主流程。
        pass


def memoize(namespace: str, ttl_seconds: int = 24 * 3600):
    """轻量装饰器：把 (namespace, canonical_args) 做缓存键。"""
    def deco(fn: Callable[..., Any]):
        def wrapped(*args, **kwargs):
            key = json.dumps({"a": args, "k": kwargs}, sort_keys=True, ensure_ascii=False, default=str)
            hit = get(namespace, key, ttl_seconds)
            if hit is not None:
                return hit
            v = fn(*args, **kwargs)
            put(namespace, key, v)
            return v
        return wrapped
    return deco
