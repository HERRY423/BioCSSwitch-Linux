#!/usr/bin/env python3
"""PubMed MCP server：检索 + 拉元数据（含证据类型分类）。

工具：
  pubmed_search      — 关键词 → PMID 列表 + 简要摘要
  pubmed_fetch       — PMID → 完整元数据（标题/作者/期刊/年份/DOI/摘要/证据类型）
  pubmed_related     — PMID → 相关文献（ELink neighbor）

设计取舍：
  - `search` 只返回轻量摘要，避免一次拉几十篇满负荷 XML。要细节调用 `fetch`。
  - 证据类型（RCT / meta-analysis / observational / ...）在 fetch 里已算好，
    bio-audit 可直接消费，不必再算一次。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从 packs 根被脚本方式启动：`python3 packs/bio-lit/pubmed_server.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib import entrez  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-lit-pubmed", "0.1.0")


@server.tool(
    "pubmed_search",
    "Search PubMed by keyword. Returns PMIDs with title/year/journal. Use pubmed_fetch for full metadata & evidence type.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "PubMed search expression (supports [MeSH], [Title/Abstract], boolean, etc.)"},
            "retmax": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            "mindate": {"type": "string", "description": "Earliest publication date, YYYY or YYYY/MM/DD"},
            "maxdate": {"type": "string", "description": "Latest publication date"},
            "sort": {"type": "string", "enum": ["relevance", "pub_date", "author", "journal"], "default": "relevance"},
        },
        "required": ["query"],
    },
)
def pubmed_search(query: str, retmax: int = 20, mindate: str | None = None,
                  maxdate: str | None = None, sort: str = "relevance"):
    search = entrez.esearch("pubmed", query, retmax=retmax, mindate=mindate, maxdate=maxdate,
                            sort=sort if sort != "relevance" else None)
    ids = search["ids"]
    if not ids:
        return {"count": search["count"], "query_translation": search.get("query_translation"), "results": []}
    # 用 summary 拉轻量元数据，避免一次跑几十篇全 XML
    summ = entrez.esummary("pubmed", ids)
    results = []
    for pmid in ids:
        s = summ.get(pmid) or {}
        results.append({
            "pmid": pmid,
            "title": s.get("title"),
            "journal": s.get("fulljournalname") or s.get("source"),
            "year": (s.get("pubdate") or "").split(" ")[0] if s.get("pubdate") else None,
            "authors": [a.get("name") for a in (s.get("authors") or [])][:5],
            "doi": next((x.get("value") for x in (s.get("articleids") or [])
                         if x.get("idtype") == "doi"), None),
            "pmc": next((x.get("value") for x in (s.get("articleids") or [])
                         if x.get("idtype") == "pmc"), None),
        })
    return {"count": search["count"], "query_translation": search.get("query_translation"), "results": results}


@server.tool(
    "pubmed_fetch",
    "Fetch full metadata for one or more PMIDs, including abstract text and normalized evidence_type (meta-analysis / systematic-review / RCT / cohort / observational / ...).",
    {
        "type": "object",
        "properties": {
            "pmids": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
        },
        "required": ["pmids"],
    },
)
@memoize("pubmed_fetch", ttl_seconds=7 * 24 * 3600)
def pubmed_fetch(pmids: list[str]):
    ids = [str(p).strip() for p in pmids if str(p).strip()]
    if not ids:
        return {"results": []}
    xml = entrez.efetch_text("pubmed", ids, rettype="abstract", retmode="xml")
    parsed = entrez.parse_pubmed_xml(xml)
    return {"results": parsed}


@server.tool(
    "pubmed_related",
    "Find PubMed articles related to a given PMID via ELink neighbor scores.",
    {
        "type": "object",
        "properties": {
            "pmid": {"type": "string"},
            "retmax": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
        },
        "required": ["pmid"],
    },
)
def pubmed_related(pmid: str, retmax: int = 10):
    # ELink 走同一 base；这里直接调 http（entrez 只暴露了 esearch/summary/fetch）
    params = {
        "dbfrom": "pubmed", "db": "pubmed", "id": pmid, "cmd": "neighbor",
        "retmode": "json", "tool": "csswitch-bio-pack",
    }
    import os
    key = os.environ.get("NCBI_API_KEY")
    if key:
        params["api_key"] = key
    data = http.get_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi", params=params)
    linksets = ((data or {}).get("linksets") or [{}])[0]
    linkdb = (linksets.get("linksetdbs") or [{}])[0]
    linked_ids = (linkdb.get("links") or [])[:retmax]
    if not linked_ids:
        return {"related": []}
    summ = entrez.esummary("pubmed", [str(x) for x in linked_ids])
    return {"related": [
        {
            "pmid": str(pid),
            "title": (summ.get(str(pid)) or {}).get("title"),
            "year": ((summ.get(str(pid)) or {}).get("pubdate") or "").split(" ")[0] or None,
        }
        for pid in linked_ids
    ]}


if __name__ == "__main__":
    server.run()
