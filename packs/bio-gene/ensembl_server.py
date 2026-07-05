#!/usr/bin/env python3
"""Ensembl REST MCP server：物种基因组坐标 / 转录本 / 直系同源。

工具：
  ensembl_lookup_by_symbol  — gene symbol → Ensembl 基因（可选物种）
  ensembl_lookup_by_id      — ENSG.../ENST... → 详细
  ensembl_variation         — rsID / HGVS → 变异注释（VEP-lite）
  ensembl_homologues        — Ensembl gene id → 直系同源基因（跨物种）

API：https://rest.ensembl.org
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://rest.ensembl.org"
_JSON = {"Accept": "application/json"}
server = MCPServer("bio-gene-ensembl", "0.1.0")


@server.tool(
    "ensembl_lookup_by_symbol",
    "Look up an Ensembl gene by gene symbol. Default species: 'human'. Returns Ensembl gene ID, coordinates, biotype.",
    {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "species": {"type": "string", "default": "human"},
            "expand": {"type": "boolean", "default": False, "description": "Include transcripts / exons"},
        },
        "required": ["symbol"],
    },
)
def ensembl_lookup_by_symbol(symbol: str, species: str = "human", expand: bool = False):
    params = {"expand": 1 if expand else 0}
    try:
        return http.get_json(f"{_BASE}/lookup/symbol/{species}/{symbol}",
                             params=params, headers=_JSON)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "exists": False}


@server.tool(
    "ensembl_lookup_by_id",
    "Look up an Ensembl object by stable ID (ENSG… gene, ENST… transcript, ENSP… protein).",
    {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "expand": {"type": "boolean", "default": False},
        },
        "required": ["id"],
    },
)
@memoize("ensembl_id", ttl_seconds=30 * 24 * 3600)
def ensembl_lookup_by_id(id: str, expand: bool = False):
    try:
        return http.get_json(f"{_BASE}/lookup/id/{id}",
                             params={"expand": 1 if expand else 0}, headers=_JSON)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "exists": False}


@server.tool(
    "ensembl_variation",
    "Fetch variation info for an rsID (e.g. 'rs56116432') from Ensembl / dbSNP mirror. "
    "Includes minor allele frequency across populations and clinical significance where known.",
    {
        "type": "object",
        "properties": {
            "rsid": {"type": "string"},
            "species": {"type": "string", "default": "human"},
        },
        "required": ["rsid"],
    },
)
def ensembl_variation(rsid: str, species: str = "human"):
    rsid = rsid if rsid.lower().startswith("rs") else f"rs{rsid}"
    try:
        return http.get_json(f"{_BASE}/variation/{species}/{rsid}",
                             params={"pops": 1, "phenotypes": 1}, headers=_JSON)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "exists": False}


@server.tool(
    "ensembl_homologues",
    "List orthologues / paralogues for an Ensembl gene ID.",
    {
        "type": "object",
        "properties": {
            "gene_id": {"type": "string", "description": "ENSG…"},
            "type": {"type": "string", "enum": ["orthologues", "paralogues", "all"], "default": "orthologues"},
            "target_species": {"type": "string", "description": "Optional filter, e.g. 'mus_musculus'"},
        },
        "required": ["gene_id"],
    },
)
def ensembl_homologues(gene_id: str, type: str = "orthologues",
                       target_species: str | None = None):
    params = {"type": type}
    if target_species:
        params["target_species"] = target_species
    try:
        data = http.get_json(f"{_BASE}/homology/id/{gene_id}", params=params, headers=_JSON)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "exists": False}
    hs = ((data or {}).get("data") or [{}])[0].get("homologies") or []
    return {"homologues": [{
        "target_species": h.get("target", {}).get("species"),
        "target_gene": h.get("target", {}).get("id"),
        "type": h.get("type"),
        "dn_ds": h.get("dn_ds"),
        "perc_id": h.get("target", {}).get("perc_id"),
    } for h in hs]}


if __name__ == "__main__":
    server.run()
