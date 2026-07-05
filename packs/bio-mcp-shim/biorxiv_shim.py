#!/usr/bin/env python3
"""biorxiv MCP 本地替身。走 bioRxiv/medRxiv API + Europe PMC 兜底关键词检索。

工具名对齐 Anthropic 远程 MCP：search_preprints / get_preprint / get_categories /
search_published_preprints / funder_search / get_statistics。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BR = "https://api.biorxiv.org"
_EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
server = MCPServer("biorxiv-shim", "0.1.0")


def _validate_server(s: str) -> str:
    s = (s or "biorxiv").lower()
    if s not in ("biorxiv", "medrxiv"):
        raise ValueError("server must be 'biorxiv' or 'medrxiv'")
    return s


@server.tool(
    "search_preprints",
    "[Local shim of Anthropic-hosted biorxiv] Search bioRxiv/medRxiv preprints by keyword and/or date range. "
    "Note: bioRxiv API supports date-range enumeration only; keyword search goes through Europe PMC with SRC:PPR filter.",
    {
        "type": "object",
        "properties": {
            "server": {"type": "string", "enum": ["biorxiv", "medrxiv"], "default": "biorxiv"},
            "query": {"type": "string"},
            "from_date": {"type": "string", "description": "YYYY-MM-DD"},
            "to_date": {"type": "string", "description": "YYYY-MM-DD"},
            "category": {"type": "string"},
            "page_size": {"type": "integer", "default": 25},
        },
    },
)
def search_preprints(server: str = "biorxiv", query: str | None = None,
                     from_date: str | None = None, to_date: str | None = None,
                     category: str | None = None, page_size: int = 25):
    src = _validate_server(server)
    if query:
        q = f"({query}) AND SRC:PPR"
        if category:
            q += f' AND KW:"{category}"'
        try:
            data = http.get_json(_EPMC, params={
                "query": q, "format": "json", "resultType": "lite", "pageSize": page_size,
            })
            items = ((data or {}).get("resultList") or {}).get("result") or []
            results = []
            for h in items:
                doi = h.get("doi")
                if not doi or not doi.startswith("10.1101/"):
                    continue
                results.append({
                    "doi": doi, "server": src,
                    "title": h.get("title"), "authors": h.get("authorString"),
                    "year": h.get("pubYear"), "cite_count": h.get("citedByCount"),
                })
            return {"results": results, "source": "europepmc"}
        except Exception as e:  # noqa: BLE001
            return {"results": [], "error": str(e)}
    # 无关键词 → 走 bioRxiv 日期区间
    if not (from_date and to_date):
        return {"error": "无 query 时必须给 from_date+to_date"}
    try:
        data = http.get_json(f"{_BR}/details/{src}/{from_date}/{to_date}/0")
        coll = (data or {}).get("collection") or []
        results = []
        for c in coll[:page_size]:
            if category and c.get("category") != category:
                continue
            results.append({
                "doi": c.get("doi"), "server": src,
                "title": c.get("title"), "authors": c.get("authors"),
                "date": c.get("date"), "version": c.get("version"),
                "category": c.get("category"),
            })
        return {"results": results, "source": "biorxiv_api"}
    except Exception as e:  # noqa: BLE001
        return {"results": [], "error": str(e)}


@server.tool(
    "get_preprint",
    "[Local shim] Fetch a preprint by DOI including all versions.",
    {
        "type": "object",
        "properties": {
            "server": {"type": "string", "enum": ["biorxiv", "medrxiv"], "default": "biorxiv"},
            "doi": {"type": "string"},
        },
        "required": ["doi"],
    },
)
@memoize("biorxiv_shim_get", ttl_seconds=7 * 24 * 3600)
def get_preprint(doi: str, server: str = "biorxiv"):
    src = _validate_server(server)
    doi = doi.strip()
    try:
        data = http.get_json(f"{_BR}/details/{src}/{doi}")
    except Exception as e:  # noqa: BLE001
        return {"doi": doi, "exists": False, "error": str(e)}
    coll = (data or {}).get("collection") or []
    if not coll:
        return {"doi": doi, "server": src, "exists": False}
    latest = coll[-1]
    return {
        "exists": True, "doi": doi, "server": src,
        "title": latest.get("title"), "authors": latest.get("authors"),
        "abstract": latest.get("abstract"), "date": latest.get("date"),
        "version": latest.get("version"), "category": latest.get("category"),
        "license": latest.get("license"),
        "all_versions": [{"version": c.get("version"), "date": c.get("date")} for c in coll],
    }


_CACHED_CATS: list[str] | None = None


@server.tool(
    "get_categories",
    "[Local shim] List bioRxiv/medRxiv subject categories.",
    {"type": "object", "properties": {}},
)
def get_categories():
    # bioRxiv API 没独立 categories 端点；从最新一段范围抽样。返回一个静态列表更稳。
    return {"categories": [
        "Animal Behavior and Cognition", "Biochemistry", "Bioengineering",
        "Bioinformatics", "Biophysics", "Cancer Biology", "Cell Biology",
        "Clinical Trials", "Developmental Biology", "Ecology", "Epidemiology",
        "Evolutionary Biology", "Genetics", "Genomics", "Immunology",
        "Microbiology", "Molecular Biology", "Neuroscience", "Paleontology",
        "Pathology", "Pharmacology and Toxicology", "Physiology", "Plant Biology",
        "Scientific Communication and Education", "Synthetic Biology",
        "Systems Biology", "Zoology",
    ], "note": "Static list; check biorxiv.org for the authoritative current set."}


@server.tool(
    "search_published_preprints",
    "[Local shim] Preprints that were later published in a peer-reviewed journal.",
    {
        "type": "object",
        "properties": {
            "server": {"type": "string", "enum": ["biorxiv", "medrxiv"], "default": "biorxiv"},
            "from_date": {"type": "string"},
            "to_date": {"type": "string"},
            "page_size": {"type": "integer", "default": 25},
        },
        "required": ["from_date", "to_date"],
    },
)
def search_published_preprints(from_date: str, to_date: str,
                                server: str = "biorxiv", page_size: int = 25):
    src = _validate_server(server)
    try:
        data = http.get_json(f"{_BR}/pubs/{src}/{from_date}/{to_date}/0")
    except Exception as e:  # noqa: BLE001
        return {"results": [], "error": str(e)}
    coll = (data or {}).get("collection") or []
    return {"results": [
        {"preprint_doi": c.get("preprint_doi"),
         "published_doi": c.get("published_doi"),
         "published_journal": c.get("published_journal"),
         "published_date": c.get("published_date")}
        for c in coll[:page_size]
    ]}


@server.tool(
    "funder_search",
    "[Local shim] Preprints filtered by funder.",
    {
        "type": "object",
        "properties": {
            "server": {"type": "string", "enum": ["biorxiv", "medrxiv"], "default": "biorxiv"},
            "funder": {"type": "string"},
            "from_date": {"type": "string"},
            "to_date": {"type": "string"},
            "page_size": {"type": "integer", "default": 25},
        },
        "required": ["funder"],
    },
)
def funder_search(funder: str, from_date: str | None = None, to_date: str | None = None,
                  server: str = "biorxiv", page_size: int = 25):
    src = _validate_server(server)
    # bioRxiv API 无 funder 直接过滤，用 Europe PMC + FUNDER: 语法
    q = f'FUNDER:"{funder}" AND SRC:PPR AND (10.1101 OR PUBLISHER:Cold)'
    try:
        data = http.get_json(_EPMC, params={
            "query": q, "format": "json", "resultType": "lite", "pageSize": page_size,
        })
        items = ((data or {}).get("resultList") or {}).get("result") or []
        results = [{
            "doi": h.get("doi"), "server": src,
            "title": h.get("title"), "year": h.get("pubYear"),
            "authors": h.get("authorString"),
        } for h in items if (h.get("doi") or "").startswith("10.1101/")]
        return {"results": results}
    except Exception as e:  # noqa: BLE001
        return {"results": [], "error": str(e)}


@server.tool(
    "get_statistics",
    "[Local shim] Submission / usage statistics from bioRxiv API.",
    {
        "type": "object",
        "properties": {
            "server": {"type": "string", "enum": ["biorxiv", "medrxiv"], "default": "biorxiv"},
            "interval": {"type": "string", "enum": ["m", "y"], "default": "m", "description": "m=monthly, y=yearly"},
        },
    },
)
def get_statistics(server: str = "biorxiv", interval: str = "m"):
    src = _validate_server(server)
    try:
        sub = http.get_json(f"{_BR}/sub/{src}/{interval}")
        usage = http.get_json(f"{_BR}/usage/{src}/{interval}")
        return {
            "submissions": (sub or {}).get("submissions") or [],
            "usage": (usage or {}).get("usage") or [],
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


if __name__ == "__main__":
    server.run()
