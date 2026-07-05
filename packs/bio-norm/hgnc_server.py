#!/usr/bin/env python3
"""HGNC MCP server：基因/蛋白名规范化。

工具：
  hgnc_lookup_symbol  — symbol → 完整 HGNC 记录（含 previous / alias / entrez / ensembl / uniprot）
  hgnc_search         — 关键词 / 别名 → 候选列表
  hgnc_by_id          — HGNC:xxxx → 完整记录

数据源：https://rest.genenames.org  免鉴权 JSON。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://rest.genenames.org"
_H = {"Accept": "application/json"}
server = MCPServer("bio-norm-hgnc", "0.1.0")


def _flatten_doc(d: dict) -> dict:
    return {
        "hgnc_id": d.get("hgnc_id"),
        "symbol": d.get("symbol"),
        "name": d.get("name"),
        "status": d.get("status"),
        "locus_group": d.get("locus_group"),
        "locus_type": d.get("locus_type"),
        "location": d.get("location"),
        "alias_symbol": d.get("alias_symbol") or [],
        "alias_name": d.get("alias_name") or [],
        "prev_symbol": d.get("prev_symbol") or [],
        "prev_name": d.get("prev_name") or [],
        "gene_group": d.get("gene_group") or [],
        "entrez_id": d.get("entrez_id"),
        "ensembl_gene_id": d.get("ensembl_gene_id"),
        "uniprot_ids": d.get("uniprot_ids") or [],
        "refseq_accession": d.get("refseq_accession") or [],
        "mgd_id": d.get("mgd_id"),
        "rgd_id": d.get("rgd_id"),
        "omim_id": d.get("omim_id") or [],
    }


@server.tool(
    "hgnc_lookup_symbol",
    "Look up a gene by its **current** HGNC symbol (case-sensitive, e.g. 'BRCA1'). "
    "For symbols that might be historical / alias, use hgnc_search instead.",
    {
        "type": "object",
        "properties": {"symbol": {"type": "string"}},
        "required": ["symbol"],
    },
)
@memoize("hgnc_symbol", ttl_seconds=30 * 24 * 3600)
def hgnc_lookup_symbol(symbol: str):
    symbol = symbol.strip()
    try:
        data = http.get_json(f"{_BASE}/fetch/symbol/{symbol}", headers=_H)
    except Exception as e:  # noqa: BLE001
        return {"symbol": symbol, "exists": False, "error": str(e)}
    docs = ((data or {}).get("response") or {}).get("docs") or []
    if not docs:
        return {"symbol": symbol, "exists": False}
    return {"exists": True, **_flatten_doc(docs[0])}


@server.tool(
    "hgnc_search",
    "Search HGNC by symbol, alias, previous symbol, or name (fuzzy). "
    "Returns multiple candidates — use this when input might be an outdated / aliased symbol.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
        },
        "required": ["query"],
    },
)
def hgnc_search(query: str, limit: int = 10):
    query = query.strip()
    try:
        data = http.get_json(f"{_BASE}/search/{query}", headers=_H)
    except Exception as e:  # noqa: BLE001
        return {"query": query, "results": [], "error": str(e)}
    docs = ((data or {}).get("response") or {}).get("docs") or []
    results = [{
        "hgnc_id": d.get("hgnc_id"),
        "symbol": d.get("symbol"),
        "score": d.get("score"),
    } for d in docs[:limit]]
    return {"query": query, "num_found": ((data or {}).get("response") or {}).get("numFound"), "results": results}


@server.tool(
    "hgnc_by_id",
    "Fetch by HGNC ID ('HGNC:xxxx' or bare integer).",
    {
        "type": "object",
        "properties": {"hgnc_id": {"type": "string"}},
        "required": ["hgnc_id"],
    },
)
@memoize("hgnc_by_id", ttl_seconds=30 * 24 * 3600)
def hgnc_by_id(hgnc_id: str):
    hgnc_id = hgnc_id.strip()
    if hgnc_id.lower().startswith("hgnc:"):
        hgnc_id = hgnc_id[5:]
    try:
        data = http.get_json(f"{_BASE}/fetch/hgnc_id/{hgnc_id}", headers=_H)
    except Exception as e:  # noqa: BLE001
        return {"hgnc_id": hgnc_id, "exists": False, "error": str(e)}
    docs = ((data or {}).get("response") or {}).get("docs") or []
    if not docs:
        return {"hgnc_id": hgnc_id, "exists": False}
    return {"exists": True, **_flatten_doc(docs[0])}


if __name__ == "__main__":
    server.run()
