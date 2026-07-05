#!/usr/bin/env python3
"""NCBI 家族（Gene / ClinVar / dbSNP / GEO / SRA）—— 都走 E-utilities，一个 server 全包。

工具：
  gene_search / gene_summary        — NCBI Gene
  clinvar_search / clinvar_summary  — ClinVar 变异注释
  dbsnp_summary                     — dbSNP rsID 摘要
  geo_search / geo_summary          — GEO 数据集（GSE / GDS）
  sra_search / sra_summary          — SRA 测序档案
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import entrez  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-gene-ncbi", "0.1.0")


def _mk_search_tool(db: str, tool_name: str, description: str):
    @server.tool(
        tool_name,
        description,
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "retmax": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
    )
    def _fn(query: str, retmax: int = 20, _db=db):
        res = entrez.esearch(_db, query, retmax=retmax)
        return {"count": res["count"], "ids": res["ids"],
                "query_translation": res.get("query_translation")}
    _fn.__name__ = tool_name  # 让每次调用可辨识
    return _fn


def _mk_summary_tool(db: str, tool_name: str, description: str, id_key: str = "ids"):
    @server.tool(
        tool_name,
        description,
        {
            "type": "object",
            "properties": {id_key: {"type": "array", "items": {"type": "string"}, "maxItems": 100}},
            "required": [id_key],
        },
    )
    def _fn(_db=db, _id_key=id_key, **kwargs):
        ids = kwargs.get(_id_key) or []
        ids = [str(x) for x in ids if str(x).strip()]
        if not ids:
            return {"results": {}}
        return {"results": entrez.esummary(_db, ids)}
    _fn.__name__ = tool_name
    return _fn


# ---------- Gene ----------
_mk_search_tool("gene", "gene_search",
                "Search NCBI Gene by symbol / name / organism, e.g. 'BRCA1[gene] AND human[orgn]'.")
_mk_summary_tool("gene", "gene_summary",
                 "Summary for NCBI Gene IDs: symbol, name, chromosome, map location, description.")


# ---------- ClinVar ----------
_mk_search_tool("clinvar", "clinvar_search",
                "Search ClinVar variants, e.g. 'BRCA1 pathogenic' or 'NM_007294.4:c.5266dupC'.")
_mk_summary_tool("clinvar", "clinvar_summary",
                 "Summary for ClinVar VCV / RCV IDs: clinical significance, review status, condition.")


# ---------- dbSNP ----------
@server.tool(
    "dbsnp_summary",
    "Fetch dbSNP records by rsID (numeric part only, e.g. '113993960' for rs113993960).",
    {
        "type": "object",
        "properties": {"rsids": {"type": "array", "items": {"type": "string"}, "maxItems": 100}},
        "required": ["rsids"],
    },
)
def dbsnp_summary(rsids: list[str]):
    ids = [str(r).lstrip("rsRS") for r in rsids]
    return {"results": entrez.esummary("snp", ids)}


# ---------- GEO ----------
_mk_search_tool("gds", "geo_search",
                "Search GEO datasets / series by keyword, e.g. 'breast cancer AND expression profiling by high throughput sequencing[DataSet Type]'.")
_mk_summary_tool("gds", "geo_summary",
                 "Summary for GEO UIDs: accession (GSE/GDS/GPL), title, sample count, organism, platform.")


# ---------- SRA ----------
_mk_search_tool("sra", "sra_search",
                "Search SRA (Sequence Read Archive) by keyword, accession, or organism.")
_mk_summary_tool("sra", "sra_summary",
                 "Summary for SRA UIDs: run accession (SRR), experiment, platform, library strategy, spots.")


if __name__ == "__main__":
    server.run()
