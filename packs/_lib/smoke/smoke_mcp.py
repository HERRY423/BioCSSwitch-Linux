#!/usr/bin/env python3
"""Canary MCP —— 用于 phase-1 路径验证。

启动时立刻做两件事：
  1) 在 `~/.csswitch/smoke/` 下创建一个"我起来了"标记文件，含 argv[0]、pid、启动时间、
     一个从环境变量读入的 marker（由 CSSwitch 后端注入唯一值）。
  2) 常规 stdio MCP 循环，暴露一个 `smoke_ping` 工具，回一段固定字符串。

CSSwitch 后端起 sandbox 之后：
  - 若 Science 真的读了 `mcp-servers.json`，就会 spawn 本脚本 → 标记文件出现 → 证明
    我们猜的 MCP 配置文件路径正确。
  - 若 Science 没 spawn 本脚本（用了别的路径 / schema / 或者压根不支持我们放的位置），
    标记文件不会出现 → smoke_fail，UI 上把 pack 标"实验中"。

设计要点：
  - **不做任何网络请求**。只写本地文件 + 本地 stdio。
  - **不删除标记文件**。哪怕重复起动也 append 一行，让用户能看历史。
  - **收到 stdin EOF 或 signal 就干净退出**，避免留孤儿进程。
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path


def _marker_dir() -> Path:
    root = os.environ.get("CSSWITCH_SMOKE_DIR")
    if root:
        return Path(root)
    home = os.environ.get("HOME")
    if not home:
        return Path("./.csswitch/smoke")
    return Path(home) / ".csswitch" / "smoke"


def _write_marker() -> None:
    d = _marker_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        marker = os.environ.get("CSSWITCH_SMOKE_MARKER", "unmarked")
        line = json.dumps({
            "ts": time.time(),
            "pid": os.getpid(),
            "argv": sys.argv,
            "marker": marker,
            "python": sys.executable,
        }, ensure_ascii=False)
        (d / "spawned.jsonl").open("a", encoding="utf-8").write(line + "\n")
        # 也留一个"最新一次"文件，方便 Rust 侧只读最后状态
        (d / "latest.json").write_text(line, encoding="utf-8")
        try:
            os.chmod(d / "spawned.jsonl", 0o600)
            os.chmod(d / "latest.json", 0o600)
        except Exception:
            pass
    except Exception as e:  # noqa: BLE001
        # 写 marker 失败也别崩：继续跑 MCP 循环，起码工具还能被调
        sys.stderr.write(f"[smoke_mcp] marker write failed: {e}\n")


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-mcp-smoke", "0.1.0")


@server.tool(
    "smoke_ping",
    "CSSwitch canary tool. Returns marker + pid so an outer test can prove Science reached this MCP.",
    {"type": "object", "properties": {}},
)
def smoke_ping():
    return {
        "marker": os.environ.get("CSSWITCH_SMOKE_MARKER", "unmarked"),
        "pid": os.getpid(),
        "ts": time.time(),
    }


def _cleanup(*_):
    # 退出前留个"我停了"标记，帮排查
    d = _marker_dir()
    try:
        (d / "last_exit.txt").write_text(f"{time.time()}\n{os.getpid()}\n", encoding="utf-8")
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    _write_marker()
    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)
    server.run()
    _cleanup()
