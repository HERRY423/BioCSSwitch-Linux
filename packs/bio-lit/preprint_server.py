#!/usr/bin/env python3
"""bioRxiv / medRxiv MCP server：DOI 明细 + 关键词检索。

关键权衡：
  - bioRxiv 官方 API（api.biorxiv.org）**只支持 DOI 明细和日期区间遍历**，
    不支持关键词检索。因此关键词检索走 Europe PMC，加 `SRC:PPR` 过滤，
    再把命中 DOI 反查 biorxiv API 拿版本历史 / 发表状态。
  - 这样一个工具同时覆盖两个源：`server=biorxiv|medrxiv` 参数切换。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BR_BASE = "https://api.biorxiv.org"
_EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

server = MCPServer("bio-lit-preprint", "0.1.0")


def _validate_source(source: str) -> str:
    s = (source or "").lower()
    if s not in ("biorxiv", "medrxiv"):
        raise ValueError("source must be 'biorxiv' or 'medrxiv'")
    return s


@server.tool(
    "preprint_search",
    "Search bioRxiv or medRxiv preprints by keyword (via Europe PMC PPR filter). "
    "For version history / published-journal status, call preprint_by_doi on the returned DOIs.",
    {
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["biorxiv", "medrxiv"]},
            "query": {"type": "string"},
            "pageSize": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
            "from_year": {"type": "integer"},
            "until_year": {"type": "integer"},
        },
        "required": ["source", "query"],
    },
)
def preprint_search(source: str, query: str, pageSize: int = 25,
                    from_year: int | None = None, until_year: int | None = None):
    src = _validate_source(source)
    q_parts = [f"({query})", "SRC:PPR", f'PUBLISHER:"{src.replace("biorxiv", "Cold Spring Harbor").replace("medrxiv", "Cold Spring Harbor")}"']
    # PUBLISHER 过滤并不 100% 严丝合缝，用 preprint DOI 前缀二次过滤
    doi_prefix = "10.1101/"
    if from_year:
        q_parts.append(f"FIRST_PDATE:[{from_year} TO {until_year or '*'}]")
    q = " AND ".join(q_parts)
    data = http.get_json(_EPMC, params={
        "query": q, "format": "json", "resultType": "lite", "pageSize": pageSize,
    })
    items = ((data or {}).get("resultList") or {}).get("result") or []
    results = []
    for h in items:
        doi = h.get("doi")
        if not doi or not doi.startswith(doi_prefix):
            continue
        results.append({
            "doi": doi,
            "server": src,
            "title": h.get("title"),
            "authors": h.get("authorString"),
            "year": h.get("pubYear"),
            "cite_count": h.get("citedByCount"),
        })
    return {"results": results}


@server.tool(
    "preprint_by_doi",
    "Fetch bioRxiv/medRxiv preprint details by DOI: title/authors/abstract, all versions, and whether it was published in a journal.",
    {
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["biorxiv", "medrxiv"]},
            "doi": {"type": "string", "description": "e.g. '10.1101/2023.01.15.523456'"},
        },
        "required": ["source", "doi"],
    },
)
@memoize("preprint_doi", ttl_seconds=7 * 24 * 3600)
def preprint_by_doi(source: str, doi: str):
    src = _validate_source(source)
    doi = doi.strip()
    if doi.lower().startswith("doi:"):
        doi = doi[4:]
    data = http.get_json(f"{_BR_BASE}/details/{src}/{doi}")
    collection = (data or {}).get("collection") or []
    if not collection:
        return {"doi": doi, "server": src, "exists": False}
    latest = collection[-1]
    # 是否已被期刊发表：pubs 端点
    pub = None
    try:
        pubs_data = http.get_json(f"{_BR_BASE}/pubs/{src}/{doi}")
        pubs = (pubs_data or {}).get("collection") or []
        if pubs:
            pub = {
                "published_doi": pubs[0].get("published_doi"),
                "published_journal": pubs[0].get("published_journal"),
                "published_date": pubs[0].get("published_date"),
            }
    except Exception:  # noqa: BLE001
        pub = None
    return {
        "doi": doi,
        "server": src,
        "exists": True,
        "title": latest.get("title"),
        "authors": latest.get("authors"),
        "author_corresponding": latest.get("author_corresponding"),
        "abstract": latest.get("abstract"),
        "date": latest.get("date"),
        "version": latest.get("version"),
        "type": latest.get("type"),
        "category": latest.get("category"),
        "license": latest.get("license"),
        "all_versions": [{"version": c.get("version"), "date": c.get("date")} for c in collection],
        "published": pub,
    }


if __name__ == "__main__":
    server.run()
