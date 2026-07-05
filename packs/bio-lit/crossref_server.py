#!/usr/bin/env python3
"""Crossref MCP server：DOI 元数据 + 检索。用于验证 DOI 真实存在、拿引用元数据。

工具：
  crossref_by_doi   — DOI → 元数据（bio-audit 的 DOI 校验用它）
  crossref_search   — 关键词/作者/期刊 → 结果列表

礼貌用法：Crossref 推荐带 `mailto` 参数进入 polite pool，通过环境变量
`CROSSREF_MAILTO` 提供；未提供则退回 anonymous pool（限流更严）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://api.crossref.org"
server = MCPServer("bio-lit-crossref", "0.1.0")


def _polite(params: dict) -> dict:
    m = os.environ.get("CROSSREF_MAILTO")
    if m:
        params.setdefault("mailto", m)
    return params


def _flatten(msg: dict) -> dict:
    if not msg:
        return {}
    title = (msg.get("title") or [""])[0]
    ctitle = (msg.get("container-title") or [""])[0]
    year = None
    for k in ("published-print", "published-online", "issued", "created"):
        v = msg.get(k)
        if v and v.get("date-parts"):
            year = v["date-parts"][0][0]
            break
    authors = []
    for a in msg.get("author", []) or []:
        given = a.get("given", "")
        family = a.get("family", "")
        authors.append(f"{family}, {given}".strip(", "))
    return {
        "doi": msg.get("DOI"),
        "type": msg.get("type"),
        "title": title,
        "container": ctitle,
        "publisher": msg.get("publisher"),
        "year": year,
        "authors": authors[:15],
        "issn": msg.get("ISSN"),
        "url": msg.get("URL"),
        "reference_count": msg.get("reference-count"),
        "is_referenced_by_count": msg.get("is-referenced-by-count"),
        "subject": msg.get("subject"),
        "abstract": msg.get("abstract"),  # 常含 JATS 标签，调用方自己判断
    }


@server.tool(
    "crossref_by_doi",
    "Look up Crossref metadata for a DOI. Use to verify a DOI exists and get canonical title/authors/journal/year.",
    {
        "type": "object",
        "properties": {"doi": {"type": "string"}},
        "required": ["doi"],
    },
)
@memoize("crossref_doi", ttl_seconds=30 * 24 * 3600)
def crossref_by_doi(doi: str):
    doi = doi.strip()
    if doi.lower().startswith("doi:"):
        doi = doi[4:]
    if doi.lower().startswith("https://doi.org/"):
        doi = doi.split("https://doi.org/", 1)[1]
    try:
        data = http.get_json(f"{_BASE}/works/{doi}", params=_polite({}))
    except Exception as e:  # noqa: BLE001
        # HTTP 404 会走这里 —— Crossref 明确 404 意味着 DOI 不存在。
        msg = str(e)
        return {"doi": doi, "exists": False, "error": msg}
    msg = (data or {}).get("message") or {}
    flat = _flatten(msg)
    flat["exists"] = True
    return flat


@server.tool(
    "crossref_search",
    "Free-text search Crossref works. Filters supported: from-pub-date, until-pub-date, type (journal-article, book-chapter, ...).",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "rows": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            "from_year": {"type": "integer"},
            "until_year": {"type": "integer"},
            "type_filter": {"type": "string", "description": "e.g. 'journal-article', 'proceedings-article'"},
        },
        "required": ["query"],
    },
)
def crossref_search(query: str, rows: int = 20, from_year: int | None = None,
                    until_year: int | None = None, type_filter: str | None = None):
    filters = []
    if from_year:
        filters.append(f"from-pub-date:{from_year}")
    if until_year:
        filters.append(f"until-pub-date:{until_year}")
    if type_filter:
        filters.append(f"type:{type_filter}")
    params = {"query": query, "rows": rows}
    if filters:
        params["filter"] = ",".join(filters)
    data = http.get_json(f"{_BASE}/works", params=_polite(params))
    items = ((data or {}).get("message") or {}).get("items", []) or []
    return {
        "total": ((data or {}).get("message") or {}).get("total-results", 0),
        "results": [_flatten(i) for i in items],
    }


if __name__ == "__main__":
    server.run()
