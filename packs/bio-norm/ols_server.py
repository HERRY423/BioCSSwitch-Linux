#!/usr/bin/env python3
"""OLS4 MCP server：疾病 (MONDO/DOID)、表型 (HPO)、通路/功能 (GO)、化学 (ChEBI) 统一入口。

工具：
  ols_search       — 关键词 → 跨/单本体命中列表
  ols_lookup       — 精确 term_id → 完整详情
  ols_ancestors    — term → 上位类（用于判断"这是哪一类疾病/表型"）

数据源：https://www.ebi.ac.uk/ols4  免鉴权 JSON。
一个 server 覆盖 5 个本体，省得每个本体单独封一遍。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://www.ebi.ac.uk/ols4/api"
server = MCPServer("bio-norm-ols", "0.1.0")


# 本体白名单：拒绝把 term_id 传去别的本体上，避免 term 变成"某个奇怪本体的同名条目"。
_ALLOWED_ONTOLOGIES = {"mondo", "doid", "hp", "go", "chebi", "efo", "ncit"}


def _flatten_hit(h: dict) -> dict:
    return {
        "iri": h.get("iri"),
        "short_id": h.get("obo_id") or h.get("short_form"),
        "label": h.get("label"),
        "ontology": h.get("ontology_name"),
        "description": (h.get("description") or [None])[0] if h.get("description") else None,
        "synonyms": h.get("synonym") or [],
    }


@server.tool(
    "ols_search",
    "Search ontologies for a term. Restrict scope with `ontology` (mondo=disease, hp=HPO phenotype, go=Gene Ontology, chebi=chemicals, doid=Disease Ontology). Omit to search across all supported ontologies.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "ontology": {"type": "string", "enum": sorted(_ALLOWED_ONTOLOGIES),
                         "description": "Optional single-ontology filter"},
            "exact_only": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
        },
        "required": ["query"],
    },
)
def ols_search(query: str, ontology: str | None = None,
               exact_only: bool = False, limit: int = 20):
    params = {"q": query, "rows": limit}
    if ontology:
        params["ontology"] = ontology
    if exact_only:
        params["exact"] = "true"
    try:
        data = http.get_json(f"{_BASE}/search", params=params)
    except Exception as e:  # noqa: BLE001
        return {"query": query, "results": [], "error": str(e)}
    docs = ((data or {}).get("response") or {}).get("docs") or []
    return {
        "query": query,
        "num_found": ((data or {}).get("response") or {}).get("numFound"),
        "results": [_flatten_hit(d) for d in docs],
    }


@server.tool(
    "ols_lookup",
    "Fetch a term by its ontology + short ID (e.g. ontology='mondo', term_id='MONDO_0007254').",
    {
        "type": "object",
        "properties": {
            "ontology": {"type": "string"},
            "term_id": {"type": "string", "description": "OBO short form (with underscore), or CURIE 'MONDO:0007254'"},
        },
        "required": ["ontology", "term_id"],
    },
)
@memoize("ols_lookup", ttl_seconds=30 * 24 * 3600)
def ols_lookup(ontology: str, term_id: str):
    ontology = ontology.strip().lower()
    if ontology not in _ALLOWED_ONTOLOGIES:
        return {"error": f"ontology '{ontology}' not in whitelist"}
    short = term_id.strip().replace(":", "_")
    iri = f"http://purl.obolibrary.org/obo/{short}"
    from urllib.parse import quote
    encoded = quote(iri, safe="")
    encoded = quote(encoded, safe="")  # OLS 要求两次 URL 编码
    try:
        data = http.get_json(f"{_BASE}/ontologies/{ontology}/terms/{encoded}")
    except Exception as e:  # noqa: BLE001
        return {"exists": False, "error": str(e)}
    return {
        "exists": True,
        "iri": data.get("iri"),
        "short_id": data.get("obo_id") or data.get("short_form"),
        "label": data.get("label"),
        "description": (data.get("description") or [None])[0] if data.get("description") else None,
        "synonyms": data.get("synonyms") or [],
        "is_obsolete": data.get("is_obsolete"),
        "annotation": data.get("annotation") or {},
    }


@server.tool(
    "ols_ancestors",
    "List ancestor (broader) classes for a term. Useful to decide 'this disease is a subtype of X' or 'this pathway falls under GO:...'.",
    {
        "type": "object",
        "properties": {
            "ontology": {"type": "string"},
            "term_id": {"type": "string"},
            "limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 200},
        },
        "required": ["ontology", "term_id"],
    },
)
def ols_ancestors(ontology: str, term_id: str, limit: int = 30):
    ontology = ontology.strip().lower()
    if ontology not in _ALLOWED_ONTOLOGIES:
        return {"error": f"ontology '{ontology}' not in whitelist"}
    short = term_id.strip().replace(":", "_")
    iri = f"http://purl.obolibrary.org/obo/{short}"
    from urllib.parse import quote
    enc = quote(quote(iri, safe=""), safe="")
    try:
        data = http.get_json(f"{_BASE}/ontologies/{ontology}/terms/{enc}/ancestors",
                             params={"size": limit})
    except Exception as e:  # noqa: BLE001
        return {"ancestors": [], "error": str(e)}
    embedded = ((data or {}).get("_embedded") or {}).get("terms") or []
    return {"ancestors": [{"short_id": t.get("obo_id"), "label": t.get("label")}
                          for t in embedded[:limit]]}


if __name__ == "__main__":
    server.run()
