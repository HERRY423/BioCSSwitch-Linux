#!/usr/bin/env python3
"""pubmed MCP 本地替身。

工具名与 Anthropic 托管的 pubmed 远程 MCP 一致，让 Science 里的工具列表看到熟悉的
名字（search_articles / get_article_metadata / ...），但底层走 NCBI E-utilities +
用户填的 NCBI_API_KEY。虚拟登录下远程 MCP fast-fail，用户体验到的名字仍在。

对应关系（尽量对齐；名字不同请调用者放弃"字节级兼容"这个幻觉）：
  search_articles          — E-utilities esearch + esummary
  get_article_metadata     — esummary
  get_full_text_article    — efetch retmode=xml + Europe PMC 兜底
  find_related_articles    — elink neighbor
  lookup_article_by_citation — 依 citation 里的 pmid/doi 反查
  convert_article_ids      — E-utilities idconv
  get_copyright_status     — 只做启发式（PMC OA subset 判定）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import entrez, http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("pubmed-shim", "0.1.0")


@server.tool(
    "search_articles",
    "[Local shim of Anthropic-hosted pubmed] Search PubMed by keyword. Compatible with the remote MCP's tool name.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": 20},
            "min_date": {"type": "string"},
            "max_date": {"type": "string"},
            "sort": {"type": "string", "enum": ["relevance", "pub_date"], "default": "relevance"},
        },
        "required": ["query"],
    },
)
def search_articles(query: str, max_results: int = 20,
                    min_date: str | None = None, max_date: str | None = None,
                    sort: str = "relevance"):
    res = entrez.esearch("pubmed", query, retmax=max_results,
                         mindate=min_date, maxdate=max_date,
                         sort=None if sort == "relevance" else sort)
    ids = res["ids"]
    if not ids:
        return {"count": res["count"], "results": []}
    summ = entrez.esummary("pubmed", ids)
    results = []
    for pmid in ids:
        s = summ.get(pmid) or {}
        results.append({
            "pmid": pmid, "title": s.get("title"),
            "journal": s.get("fulljournalname") or s.get("source"),
            "year": (s.get("pubdate") or "").split(" ")[0] if s.get("pubdate") else None,
            "authors": [a.get("name") for a in (s.get("authors") or [])][:5],
            "doi": next((x.get("value") for x in (s.get("articleids") or [])
                         if x.get("idtype") == "doi"), None),
        })
    return {"count": res["count"], "results": results}


@server.tool(
    "get_article_metadata",
    "[Local shim] Get metadata for a PMID: title, authors, journal, year, DOI, abstract.",
    {
        "type": "object",
        "properties": {"pmid": {"type": "string"}},
        "required": ["pmid"],
    },
)
@memoize("pubmed_shim_meta", ttl_seconds=7 * 24 * 3600)
def get_article_metadata(pmid: str):
    xml = entrez.efetch_text("pubmed", [pmid], rettype="abstract", retmode="xml")
    parsed = entrez.parse_pubmed_xml(xml)
    if not parsed:
        return {"pmid": pmid, "exists": False}
    return {"exists": True, **parsed[0]}


@server.tool(
    "get_full_text_article",
    "[Local shim] Fetch full-text XML from Europe PMC for PMC OA subset. For non-OA, only metadata is returned.",
    {
        "type": "object",
        "properties": {"pmid": {"type": "string"}},
        "required": ["pmid"],
    },
)
def get_full_text_article(pmid: str):
    # 先拉 metadata 拿 pmcid
    xml = entrez.efetch_text("pubmed", [pmid], rettype="abstract", retmode="xml")
    parsed = entrez.parse_pubmed_xml(xml)
    if not parsed:
        return {"pmid": pmid, "exists": False}
    meta = parsed[0]
    # 从 esummary 找 pmcid
    summ = entrez.esummary("pubmed", [pmid])
    s = summ.get(pmid) or {}
    pmcid = next((x.get("value") for x in (s.get("articleids") or [])
                  if x.get("idtype") == "pmc"), None)
    if not pmcid:
        return {**meta, "full_text_available": False,
                "note": "无 PMC OA 版本；只返回摘要与元数据"}
    try:
        ft = http.get_text(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
        return {**meta, "full_text_available": True, "pmcid": pmcid,
                "xml": ft[:200000], "length": len(ft)}
    except Exception as e:  # noqa: BLE001
        return {**meta, "full_text_available": False, "pmcid": pmcid, "error": str(e)}


@server.tool(
    "find_related_articles",
    "[Local shim] Related articles for a PMID (ELink neighbor).",
    {
        "type": "object",
        "properties": {
            "pmid": {"type": "string"},
            "max_results": {"type": "integer", "default": 10},
        },
        "required": ["pmid"],
    },
)
def find_related_articles(pmid: str, max_results: int = 10):
    import os
    params = {"dbfrom": "pubmed", "db": "pubmed", "id": pmid, "cmd": "neighbor",
              "retmode": "json", "tool": "csswitch-bio-pack"}
    if os.environ.get("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]
    data = http.get_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi", params=params)
    linksets = ((data or {}).get("linksets") or [{}])[0]
    linkdb = (linksets.get("linksetdbs") or [{}])[0]
    ids = [str(x) for x in (linkdb.get("links") or [])[:max_results]]
    if not ids:
        return {"related": []}
    summ = entrez.esummary("pubmed", ids)
    return {"related": [
        {"pmid": pid, "title": (summ.get(pid) or {}).get("title"),
         "year": ((summ.get(pid) or {}).get("pubdate") or "").split(" ")[0] or None}
        for pid in ids
    ]}


@server.tool(
    "convert_article_ids",
    "[Local shim] Convert between PMID / DOI / PMCID via NCBI idconv.",
    {
        "type": "object",
        "properties": {
            "ids": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
            "idtype": {"type": "string", "enum": ["pmid", "doi", "pmcid"], "default": "pmid"},
        },
        "required": ["ids"],
    },
)
def convert_article_ids(ids: list[str], idtype: str = "pmid"):
    params = {"ids": ",".join(ids), "idtype": idtype, "format": "json",
              "tool": "csswitch-bio-pack"}
    try:
        data = http.get_json("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/", params=params)
        return {"records": (data or {}).get("records") or []}
    except Exception as e:  # noqa: BLE001
        return {"records": [], "error": str(e)}


@server.tool(
    "get_copyright_status",
    "[Local shim] Rough copyright/OA status: presence in PMC OA subset via esummary.",
    {
        "type": "object",
        "properties": {"pmid": {"type": "string"}},
        "required": ["pmid"],
    },
)
def get_copyright_status(pmid: str):
    summ = entrez.esummary("pubmed", [pmid])
    s = summ.get(pmid) or {}
    pmcid = next((x.get("value") for x in (s.get("articleids") or [])
                  if x.get("idtype") == "pmc"), None)
    return {
        "pmid": pmid,
        "in_pmc_oa_subset": bool(pmcid),
        "pmcid": pmcid,
        "note": "This is a heuristic; presence in PMC ≠ CC-BY license. Check the article's page for exact license.",
    }


@server.tool(
    "lookup_article_by_citation",
    "[Local shim] Resolve free-text citation → PMID via ESearch on author + year + journal.",
    {
        "type": "object",
        "properties": {
            "author": {"type": "string"},
            "year": {"type": "integer"},
            "journal": {"type": "string"},
            "title_words": {"type": "string"},
        },
    },
)
def lookup_article_by_citation(author: str | None = None, year: int | None = None,
                                journal: str | None = None, title_words: str | None = None):
    parts = []
    if author:
        parts.append(f"{author}[Author]")
    if year:
        parts.append(f"{year}[PDAT]")
    if journal:
        parts.append(f'"{journal}"[Journal]')
    if title_words:
        parts.append(f"{title_words}[Title]")
    if not parts:
        return {"error": "至少提供一个字段"}
    query = " AND ".join(parts)
    res = entrez.esearch("pubmed", query, retmax=5)
    if not res["ids"]:
        return {"query": query, "results": []}
    summ = entrez.esummary("pubmed", res["ids"])
    return {"query": query, "results": [
        {"pmid": pid, "title": (summ.get(pid) or {}).get("title"),
         "journal": (summ.get(pid) or {}).get("fulljournalname"),
         "year": ((summ.get(pid) or {}).get("pubdate") or "").split(" ")[0] or None}
        for pid in res["ids"]
    ]}


if __name__ == "__main__":
    server.run()
