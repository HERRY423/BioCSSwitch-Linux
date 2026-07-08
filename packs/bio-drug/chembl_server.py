#!/usr/bin/env python3
"""ChEMBL MCP server：化合物 / 靶点 / 生物活性 / 机制。

工具：
  chembl_compound_search  — 按名称 / SMILES / ChEMBL ID 找化合物
  chembl_target_search    — 按 gene / protein 找靶点
  chembl_bioactivity      — 化合物 × 靶点 → IC50/EC50/Ki 定量数据
  chembl_mechanism        — 化合物 → 机制 + 直接靶点

API：https://www.ebi.ac.uk/chembl/api/data/*
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.mcp_helpers import mcp_tool, safe_http_get  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://www.ebi.ac.uk/chembl/api/data"
server = MCPServer("bio-drug-chembl", "0.1.0")


@mcp_tool(
    "chembl_compound_search",
    "Search compounds in ChEMBL by name, synonym, or ChEMBL ID (e.g. 'aspirin', 'CHEMBL25').",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
        },
        "required": ["query"],
    },
    server=server,
)
def chembl_compound_search(query: str, limit: int = 20):
    # ChEMBL 支持按 pref_name / synonym / chembl_id 检索
    if query.upper().startswith("CHEMBL"):
        res = safe_http_get(f"{_BASE}/molecule/{query.upper()}.json", timeout=30)
        if not res["ok"]:
            return {
                "results": [],
                "error": res["error"],
                "error_kind": res["error_kind"],
                "status": res["status"],
            }
        return {"results": [res["data"]]}
    data = http.get_json(f"{_BASE}/molecule/search.json",
                         params={"q": query, "limit": limit})
    return {"results": (data or {}).get("molecules") or []}


@mcp_tool(
    "chembl_target_search",
    "Search biological targets in ChEMBL by gene symbol, protein name, or ChEMBL target ID.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
        },
        "required": ["query"],
    },
    server=server,
)
def chembl_target_search(query: str, limit: int = 20):
    if query.upper().startswith("CHEMBL"):
        res = safe_http_get(f"{_BASE}/target/{query.upper()}.json", timeout=30)
        if not res["ok"]:
            return {
                "results": [],
                "error": res["error"],
                "error_kind": res["error_kind"],
                "status": res["status"],
            }
        return {"results": [res["data"]]}
    data = http.get_json(f"{_BASE}/target/search.json",
                         params={"q": query, "limit": limit})
    return {"results": (data or {}).get("targets") or []}


@server.tool(
    "chembl_bioactivity",
    "Fetch quantitative bioactivity (IC50 / EC50 / Ki / Kd) for a compound-target pair or single side. "
    "Filter by activity type or confidence score; low pchembl_value_gte weeds out weak / noisy assays.",
    {
        "type": "object",
        "properties": {
            "molecule_chembl_id": {"type": "string"},
            "target_chembl_id": {"type": "string"},
            "standard_type": {"type": "string", "description": "IC50 / EC50 / Ki / Kd / Potency"},
            "pchembl_value_gte": {"type": "number", "description": "e.g. 5 = ≥100 nM"},
            "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
        },
    },
)
def chembl_bioactivity(molecule_chembl_id: str | None = None,
                       target_chembl_id: str | None = None,
                       standard_type: str | None = None,
                       pchembl_value_gte: float | None = None,
                       limit: int = 25):
    params: dict = {"limit": limit, "format": "json"}
    if molecule_chembl_id:
        params["molecule_chembl_id"] = molecule_chembl_id
    if target_chembl_id:
        params["target_chembl_id"] = target_chembl_id
    if standard_type:
        params["standard_type"] = standard_type
    if pchembl_value_gte is not None:
        params["pchembl_value__gte"] = pchembl_value_gte
    data = http.get_json(f"{_BASE}/activity.json", params=params)
    return {"activities": (data or {}).get("activities") or []}


@server.tool(
    "chembl_mechanism",
    "List mechanism-of-action records for a compound (target + action_type).",
    {
        "type": "object",
        "properties": {"molecule_chembl_id": {"type": "string"}},
        "required": ["molecule_chembl_id"],
    },
)
@memoize("chembl_mechanism", ttl_seconds=30 * 24 * 3600)
def chembl_mechanism(molecule_chembl_id: str):
    data = http.get_json(f"{_BASE}/mechanism.json",
                         params={"molecule_chembl_id": molecule_chembl_id, "format": "json"})
    return {"mechanisms": (data or {}).get("mechanisms") or []}


if __name__ == "__main__":
    server.run()
