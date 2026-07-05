"""urllib 包装：GET JSON / GET text / POST JSON，含重试与 UA 头。

设计约束：
  - 只用 stdlib（urllib.request）—— 与 proxy/csswitch_proxy.py 保持一致。
  - 所有生物数据源 API 都是公开的、匿名可用（可选 API key 通过环境变量注入）。
  - 请求自带项目 UA，避免部分服务对空 UA 限流。
  - 只重试连接错误，不重试 4xx（服务端明确拒绝，重试无意义）。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from . import fixtures

_UA = "CSSwitch-bio-pack/0.1 (+https://github.com/SuperJJ007/CSswitch)"
_DEFAULT_HEADERS = {"User-Agent": _UA, "Accept": "application/json"}

# 进程启动即按环境变量决定是否激活 fixture 回放（CI 默认离线）。
fixtures.activate_from_env()


def _with_params(url: str, params: Optional[Dict[str, Any]]) -> str:
    if not params:
        return url
    # 过滤 None，避免把 "None" 传给上游
    clean = {k: v for k, v in params.items() if v is not None}
    if not clean:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + urllib.parse.urlencode(clean, doseq=True)


def _do(
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
    attempts: int = 3,
) -> bytes:
    # fixture 回放：命中直接返回；replay 模式未命中会 raise（保证 CI 零网络）。
    replayed = fixtures.try_replay(method, url, params, data)
    if replayed is not None:
        return replayed

    full_url = _with_params(url, params)
    h = dict(_DEFAULT_HEADERS)
    if headers:
        h.update(headers)
    req = urllib.request.Request(full_url, data=data, headers=h, method=method)
    last_err: Optional[BaseException] = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                fixtures.record(method, url, params, data, body)
                return body
        except urllib.error.HTTPError:
            # 服务端明确响应：不重试。上层根据 HTTPError.code 决策。
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < attempts - 1:
                time.sleep(0.6 * (i + 1))
                continue
    raise last_err  # type: ignore[misc]


def get_json(url: str, *, params: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None, timeout: float = 30.0) -> Any:
    body = _do("GET", url, params=params, headers=headers, timeout=timeout)
    if not body:
        return None
    return json.loads(body)


def get_text(url: str, *, params: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None, timeout: float = 30.0) -> str:
    body = _do("GET", url, params=params, headers=headers, timeout=timeout)
    return body.decode("utf-8", "replace")


def post_json(url: str, payload: Any, *, headers: Optional[Dict[str, str]] = None,
              timeout: float = 60.0) -> Any:
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    body = _do("POST", url, data=json.dumps(payload).encode(), headers=h, timeout=timeout)
    if not body:
        return None
    return json.loads(body)
