#!/usr/bin/env python3
"""审计日志 MCP。追加式 JSON-Lines 文件，便于合规审计与自查。

工具：
  audit_log_write     — 记一条：会话/上下文摘要（不记原文）、模型、时间、PHI 命中数
  audit_log_read      — 按时间 / kind 过滤查询
  audit_log_stats     — 按天 / 按模型汇总

设计原则：
  1. **只记摘要**：审计日志本身要能给第三方看，不能把 PHI 从内容窜到日志。
     `input_digest` 用 SHA-256 前 16 位（32 位十六进制），够 dedup 不够重构。
  2. **本地文件**：`~/.csswitch/audit/YYYY-MM-DD.jsonl`，0600，一天一文件便于归档。
  3. **append-only**：不提供 delete；要清理只能人工删文件（留下操作痕迹）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-privacy-audit", "0.1.0")


def _audit_dir() -> Path:
    root = os.environ.get("CSSWITCH_AUDIT_DIR")
    if root:
        return Path(root)
    home = os.environ.get("HOME")
    if not home:
        return Path("./.csswitch/audit")
    return Path(home) / ".csswitch" / "audit"


def _today_file(iso_date: str | None = None) -> Path:
    d = iso_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _audit_dir() / f"{d}.jsonl"


def _sha16(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:32]


@server.tool(
    "audit_log_write",
    "Append one audit entry to the local audit log. "
    "The tool NEVER records raw prompt content — pass a short summary + a hash of the input (SHA-256). "
    "Fields recorded: timestamp (UTC), event (e.g. 'session_start', 'phi_detected', 'redaction_applied', 'provider_switch'), "
    "provider / model in use, PHI hit counts, and a short human-readable summary you supply.",
    {
        "type": "object",
        "properties": {
            "event": {"type": "string", "description": "e.g. 'session_start', 'phi_detected', 'redaction_applied'"},
            "provider": {"type": "string", "description": "e.g. 'deepseek', 'qwen', 'official', 'local:ollama'"},
            "model": {"type": "string"},
            "summary": {"type": "string", "description": "≤ 200 chars, NO patient identifiers"},
            "phi_summary": {"type": "object", "description": "Optional: pass the `summary` field from phi_scan"},
            "input_sample": {"type": "string", "description": "Original input; will be hashed and discarded — NOT stored"},
            "extra": {"type": "object"},
        },
        "required": ["event"],
    },
)
def audit_log_write(event: str, provider: str = "", model: str = "",
                    summary: str = "", phi_summary: Dict[str, Any] | None = None,
                    input_sample: str | None = None, extra: Dict[str, Any] | None = None):
    entry: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        "provider": provider or None,
        "model": model or None,
        "summary": (summary or "")[:200],
    }
    if phi_summary:
        entry["phi"] = {
            "verdict": phi_summary.get("verdict"),
            "total": phi_summary.get("total"),
            "high_confidence": phi_summary.get("high_confidence"),
            "by_kind": phi_summary.get("by_kind"),
        }
    if input_sample is not None:
        entry["input_digest_sha256_16"] = _sha16(input_sample)
        entry["input_length"] = len(input_sample)
    if extra:
        # 防止调用方误传 raw text 到 extra 里：值超过 200 字符就截断并标记。
        clean = {}
        for k, v in extra.items():
            if isinstance(v, str) and len(v) > 200:
                clean[k] = v[:200] + "…[truncated]"
            else:
                clean[k] = v
        entry["extra"] = clean

    dst = _today_file()
    dst.parent.mkdir(parents=True, exist_ok=True)
    # 0600
    with open(dst, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    try:
        os.chmod(dst, 0o600)
    except Exception:
        pass
    return {"ok": True, "written_to": str(dst), "entry": entry}


def _iter_lines(path: Path):
    if not path.is_file():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


@server.tool(
    "audit_log_read",
    "Read audit entries in a date range (inclusive, YYYY-MM-DD). "
    "Optional filters: event kind, provider. Returns most recent first.",
    {
        "type": "object",
        "properties": {
            "date_from": {"type": "string", "description": "YYYY-MM-DD; defaults to today"},
            "date_to":   {"type": "string", "description": "YYYY-MM-DD; defaults to today"},
            "event":     {"type": "string"},
            "provider":  {"type": "string"},
            "limit":     {"type": "integer", "default": 100, "minimum": 1, "maximum": 1000},
        },
    },
)
def audit_log_read(date_from: str | None = None, date_to: str | None = None,
                   event: str | None = None, provider: str | None = None,
                   limit: int = 100):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dfrom = date_from or today
    dto = date_to or today
    d0 = datetime.strptime(dfrom, "%Y-%m-%d")
    d1 = datetime.strptime(dto, "%Y-%m-%d")
    if d1 < d0:
        d0, d1 = d1, d0
    out: List[Dict[str, Any]] = []
    day = d0
    while day <= d1:
        for entry in _iter_lines(_today_file(day.strftime("%Y-%m-%d"))):
            if event and entry.get("event") != event:
                continue
            if provider and entry.get("provider") != provider:
                continue
            out.append(entry)
        day = datetime.fromordinal(day.toordinal() + 1)
    out.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return {"count": len(out), "entries": out[:limit]}


@server.tool(
    "audit_log_stats",
    "Aggregate audit entries by day and provider. Useful for compliance reports.",
    {
        "type": "object",
        "properties": {
            "date_from": {"type": "string"},
            "date_to":   {"type": "string"},
        },
    },
)
def audit_log_stats(date_from: str | None = None, date_to: str | None = None):
    read = audit_log_read(date_from=date_from, date_to=date_to, limit=10000)
    by_day: Dict[str, Dict[str, Any]] = {}
    for e in read["entries"]:
        day = (e.get("ts") or "")[:10]
        row = by_day.setdefault(day, {"total": 0, "by_provider": {}, "by_event": {},
                                      "phi_likely": 0})
        row["total"] += 1
        p = e.get("provider") or "unknown"
        row["by_provider"][p] = row["by_provider"].get(p, 0) + 1
        ev = e.get("event") or "unknown"
        row["by_event"][ev] = row["by_event"].get(ev, 0) + 1
        if ((e.get("phi") or {}).get("verdict")) == "phi_likely":
            row["phi_likely"] += 1
    return {"by_day": by_day, "total_entries": read["count"]}


if __name__ == "__main__":
    server.run()
