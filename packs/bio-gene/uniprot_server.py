#!/usr/bin/env python3
"""UniProt MCP server：蛋白检索 + 详细注释。

工具：
  uniprot_search   — 关键词 / gene / organism → 蛋白列表
  uniprot_entry    — accession（P12345 / Q9Y223 等）→ 完整注释（功能 / GO / 结构域 / 疾病）

API：REST v2 (https://rest.uniprot.org/uniprotkb)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://rest.uniprot.org/uniprotkb"
server = MCPServer("bio-gene-uniprot", "0.1.0")


def _lite(entry: dict) -> dict:
    prot = entry.get("proteinDescription") or {}
    rec = (prot.get("recommendedName") or {}).get("fullName") or {}
    genes = entry.get("genes") or []
    gene_names = [(g.get("geneName") or {}).get("value") for g in genes]
    orgs = entry.get("organism") or {}
    return {
        "accession": entry.get("primaryAccession"),
        "reviewed": entry.get("entryType") == "UniProtKB reviewed (Swiss-Prot)",
        "name": rec.get("value"),
        "gene_names": [g for g in gene_names if g],
        "organism": orgs.get("scientificName"),
        "taxon_id": orgs.get("taxonId"),
        "length": (entry.get("sequence") or {}).get("length"),
    }


@server.tool(
    "uniprot_search",
    "Search UniProtKB by keyword. Query syntax follows UniProt: e.g. 'gene:BRCA1 AND organism_id:9606', 'kinase AND reviewed:true'.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "size": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
            "reviewed_only": {"type": "boolean", "default": True},
        },
        "required": ["query"],
    },
)
def uniprot_search(query: str, size: int = 25, reviewed_only: bool = True):
    q = query if not reviewed_only or "reviewed:" in query else f"({query}) AND reviewed:true"
    data = http.get_json(f"{_BASE}/search", params={
        "query": q, "format": "json", "size": size,
    })
    hits = (data or {}).get("results") or []
    return {"results": [_lite(h) for h in hits]}


@server.tool(
    "uniprot_entry",
    "Fetch a UniProt entry by accession (e.g. 'P38398' for BRCA1). Returns function, subcellular location, PTMs, domain architecture, disease involvement, cross-refs.",
    {
        "type": "object",
        "properties": {"accession": {"type": "string"}},
        "required": ["accession"],
    },
)
@memoize("uniprot_entry", ttl_seconds=30 * 24 * 3600)
def uniprot_entry(accession: str):
    accession = accession.strip().upper()
    try:
        data = http.get_json(f"{_BASE}/{accession}.json")
    except Exception as e:  # noqa: BLE001
        return {"accession": accession, "exists": False, "error": str(e)}
    if not data:
        return {"accession": accession, "exists": False}
    lite = _lite(data)

    # 抽核心注释
    functions = []
    subcellular = []
    diseases = []
    for c in data.get("comments") or []:
        ctype = c.get("commentType")
        texts = " ".join(t.get("value", "") for t in (c.get("texts") or []))
        if ctype == "FUNCTION":
            functions.append(texts)
        elif ctype == "SUBCELLULAR LOCATION":
            locs = c.get("subcellularLocations") or []
            for L in locs:
                loc_name = ((L.get("location") or {}).get("value")) or ""
                if loc_name:
                    subcellular.append(loc_name)
        elif ctype == "DISEASE":
            disease = c.get("disease") or {}
            diseases.append({
                "name": disease.get("diseaseId"),
                "omim": (disease.get("diseaseCrossReference") or {}).get("id"),
                "description": disease.get("description"),
            })

    features = []
    for f in data.get("features") or []:
        loc = f.get("location") or {}
        start = ((loc.get("start") or {}).get("value"))
        end = ((loc.get("end") or {}).get("value"))
        features.append({
            "type": f.get("type"),
            "description": f.get("description"),
            "start": start,
            "end": end,
        })

    xrefs = {}
    for db in data.get("uniProtKBCrossReferences") or []:
        xrefs.setdefault(db.get("database"), []).append(db.get("id"))

    return {
        **lite,
        "exists": True,
        "function": functions,
        "subcellular_location": subcellular,
        "diseases": diseases,
        "features": features[:80],
        "xrefs": {k: v[:20] for k, v in xrefs.items()},
        "sequence": (data.get("sequence") or {}).get("value"),
    }


if __name__ == "__main__":
    server.run()
