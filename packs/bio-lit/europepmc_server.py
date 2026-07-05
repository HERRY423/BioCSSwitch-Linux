#!/usr/bin/env python3
"""Europe PMC MCP server：跨源检索（含 preprint、专利、免费全文）。

工具：
  europepmc_search      — 关键词 → 结果列表（含 PMID/DOI/preprint 源头）
  europepmc_fulltext    — 只对 PMC OA 开放访问文章拉全文 XML（有 ID 时）
  europepmc_citations   — 某 PMID 的施引文献列表

API 文档：https://europepmc.org/RestfulWebService
限流：匿名可用，无硬性 rate limit（keep-alive 请求友好）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
server = MCPServer("bio-lit-europepmc", "0.1.0")


@server.tool(
    "europepmc_search",
    "Search Europe PMC across PubMed / PubMed Central / preprints / patents. "
    "Use SRC filter to narrow source: MED=PubMed, PMC=PMC full-text, PPR=preprint (bioRxiv/medRxiv), AGR=agricola.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "EPMC query, e.g. 'metformin AND cancer AND SRC:PPR' or 'TITLE:\"cell death\"'"},
            "pageSize": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
            "resultType": {"type": "string", "enum": ["lite", "core"], "default": "lite"},
            "cursorMark": {"type": "string", "default": "*", "description": "Pagination cursor; use next value from previous response"},
        },
        "required": ["query"],
    },
)
def europepmc_search(query: str, pageSize: int = 25, resultType: str = "lite",
                     cursorMark: str = "*"):
    data = http.get_json(f"{_BASE}/search", params={
        "query": query, "format": "json", "resultType": resultType,
        "pageSize": pageSize, "cursorMark": cursorMark,
    })
    hit_list = ((data or {}).get("resultList") or {}).get("result") or []
    results = []
    for h in hit_list:
        results.append({
            "id": h.get("id"),
            "source": h.get("source"),
            "pmid": h.get("pmid"),
            "pmcid": h.get("pmcid"),
            "doi": h.get("doi"),
            "title": h.get("title"),
            "authors": h.get("authorString"),
            "journal": h.get("journalTitle"),
            "year": h.get("pubYear"),
            "is_open_access": h.get("isOpenAccess") == "Y",
            "has_pdf": h.get("hasPDF") == "Y",
            "abstract": h.get("abstractText"),  # 仅 resultType=core 时有
            "cite_count": h.get("citedByCount"),
        })
    return {
        "hit_count": (data or {}).get("hitCount", 0),
        "next_cursor": (data or {}).get("nextCursorMark"),
        "results": results,
    }


@server.tool(
    "europepmc_fulltext",
    "Fetch full-text XML for an open-access PMC article. Only works when pmcid starts with 'PMC' and article is OA.",
    {
        "type": "object",
        "properties": {"pmcid": {"type": "string", "description": "PMC ID, e.g. 'PMC1234567'"}},
        "required": ["pmcid"],
    },
)
@memoize("epmc_fulltext", ttl_seconds=7 * 24 * 3600)
def europepmc_fulltext(pmcid: str):
    pmcid = pmcid.strip()
    if not pmcid.upper().startswith("PMC"):
        pmcid = "PMC" + pmcid
    url = f"{_BASE}/{pmcid}/fullTextXML"
    try:
        text = http.get_text(url)
    except Exception as e:  # noqa: BLE001
        return {"pmcid": pmcid, "available": False, "error": str(e)}
    return {"pmcid": pmcid, "available": True, "length": len(text), "xml": text[:200000]}


@server.tool(
    "europepmc_citations",
    "List articles citing a given PubMed article (via Europe PMC citation graph).",
    {
        "type": "object",
        "properties": {
            "pmid": {"type": "string"},
            "pageSize": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
        },
        "required": ["pmid"],
    },
)
def europepmc_citations(pmid: str, pageSize: int = 25):
    url = f"{_BASE}/MED/{pmid}/citations"
    data = http.get_json(url, params={"format": "json", "pageSize": pageSize})
    items = ((data or {}).get("citationList") or {}).get("citation") or []
    return {
        "hit_count": (data or {}).get("hitCount", 0),
        "citations": [
            {"pmid": i.get("id"), "title": i.get("title"),
             "year": i.get("pubYear"), "journal": i.get("journalAbbreviation")}
            for i in items
        ],
    }


if __name__ == "__main__":
    server.run()
