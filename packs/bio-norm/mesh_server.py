#!/usr/bin/env python3
"""MeSH MCP server：把口语医学名词 → 规范 MeSH 主题词。

工具：
  mesh_search      — 关键词 → MeSH UID + tree number
  mesh_summary     — UID → 完整记录（含 tree number / scope note / entry terms）
  mesh_tree_family — 给定 MeSH，返回同 tree 下的兄弟/子节点（"什么和它一类"）

数据源：NCBI E-utilities，db=mesh。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import entrez  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-norm-mesh", "0.1.0")


@server.tool(
    "mesh_search",
    "Search MeSH by term (concept name, synonym, or free text). Returns UIDs to feed into mesh_summary.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "retmax": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
        },
        "required": ["query"],
    },
)
def mesh_search(query: str, retmax: int = 20):
    res = entrez.esearch("mesh", query, retmax=retmax)
    return {"count": res["count"], "uids": res["ids"],
            "query_translation": res.get("query_translation")}


@server.tool(
    "mesh_summary",
    "Fetch canonical MeSH records by UID: descriptor name, tree numbers, scope note, entry terms (synonyms).",
    {
        "type": "object",
        "properties": {"uids": {"type": "array", "items": {"type": "string"}, "maxItems": 50}},
        "required": ["uids"],
    },
)
@memoize("mesh_summary", ttl_seconds=30 * 24 * 3600)
def mesh_summary(uids: list[str]):
    ids = [str(u).strip() for u in uids if str(u).strip()]
    if not ids:
        return {"results": []}
    raw = entrez.esummary("mesh", ids)
    out = []
    for uid in ids:
        s = raw.get(uid) or {}
        # Tree numbers 与 entry terms 是 MeSH 的关键字段；esummary 会返回 ds_meshterms / ds_meshtreenumberlist 等。
        out.append({
            "uid": uid,
            "descriptor_name": s.get("ds_meshui") or s.get("title"),
            "descriptor_full": s.get("ds_meshterms"),
            "tree_numbers": s.get("ds_meshtreenumberlist"),
            "scope_note": s.get("ds_scopenote"),
            "entry_terms": s.get("ds_entryterms"),
        })
    return {"results": out}


@server.tool(
    "mesh_tree_family",
    "Given a MeSH tree number (e.g. 'C04.588.180'), find siblings and children. "
    "Useful for 'what other diseases fall under the same MeSH branch as X'.",
    {
        "type": "object",
        "properties": {"tree_number": {"type": "string"}},
        "required": ["tree_number"],
    },
)
def mesh_tree_family(tree_number: str):
    tree_number = tree_number.strip()
    # 兄弟 = 同前缀去掉最后一段 + '*'；子 = 完整前缀 + '.*'
    parts = tree_number.split(".")
    if len(parts) < 1:
        return {"siblings": [], "children": []}
    sib_query = ".".join(parts[:-1]) + "[TN]" if len(parts) > 1 else "*"
    child_query = tree_number + ".*[TN]"
    try:
        sib = entrez.esearch("mesh", sib_query, retmax=50)
        child = entrez.esearch("mesh", child_query, retmax=50)
    except Exception as e:  # noqa: BLE001
        return {"siblings": [], "children": [], "error": str(e)}
    return {"siblings_uids": sib["ids"], "children_uids": child["ids"]}


if __name__ == "__main__":
    server.run()
