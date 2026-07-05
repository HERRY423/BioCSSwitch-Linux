#!/usr/bin/env python3
"""chembl MCP 本地替身。走 EMBL-EBI ChEMBL data API v34。

工具名对齐 Anthropic 远程 MCP：compound_search / target_search / get_bioactivity /
get_mechanism / drug_search / get_admet。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://www.ebi.ac.uk/chembl/api/data"
server = MCPServer("chembl-shim", "0.1.0")


@server.tool(
    "compound_search",
    "[Local shim of Anthropic-hosted chembl] Search compounds by name / SMILES / ChEMBL ID.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    },
)
def compound_search(query: str, limit: int = 20):
    if query.upper().startswith("CHEMBL"):
        try:
            data = http.get_json(f"{_BASE}/molecule/{query.upper()}.json")
            return {"results": [data]}
        except Exception as e:  # noqa: BLE001
            return {"results": [], "error": str(e)}
    try:
        data = http.get_json(f"{_BASE}/molecule/search.json",
                             params={"q": query, "limit": limit})
        return {"results": (data or {}).get("molecules") or []}
    except Exception as e:  # noqa: BLE001
        return {"results": [], "error": str(e)}


@server.tool(
    "target_search",
    "[Local shim] Search biological targets by gene / protein name / ChEMBL target ID.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    },
)
def target_search(query: str, limit: int = 20):
    if query.upper().startswith("CHEMBL"):
        try:
            data = http.get_json(f"{_BASE}/target/{query.upper()}.json")
            return {"results": [data]}
        except Exception as e:  # noqa: BLE001
            return {"results": [], "error": str(e)}
    try:
        data = http.get_json(f"{_BASE}/target/search.json",
                             params={"q": query, "limit": limit})
        return {"results": (data or {}).get("targets") or []}
    except Exception as e:  # noqa: BLE001
        return {"results": [], "error": str(e)}


@server.tool(
    "get_bioactivity",
    "[Local shim] IC50 / EC50 / Ki / Kd data for a compound-target pair.",
    {
        "type": "object",
        "properties": {
            "molecule_chembl_id": {"type": "string"},
            "target_chembl_id": {"type": "string"},
            "standard_type": {"type": "string"},
            "pchembl_value_gte": {"type": "number"},
            "limit": {"type": "integer", "default": 25},
        },
    },
)
def get_bioactivity(molecule_chembl_id: str | None = None,
                    target_chembl_id: str | None = None,
                    standard_type: str | None = None,
                    pchembl_value_gte: float | None = None,
                    limit: int = 25):
    params = {"limit": limit, "format": "json"}
    if molecule_chembl_id:
        params["molecule_chembl_id"] = molecule_chembl_id
    if target_chembl_id:
        params["target_chembl_id"] = target_chembl_id
    if standard_type:
        params["standard_type"] = standard_type
    if pchembl_value_gte is not None:
        params["pchembl_value__gte"] = pchembl_value_gte
    try:
        data = http.get_json(f"{_BASE}/activity.json", params=params)
        return {"activities": (data or {}).get("activities") or []}
    except Exception as e:  # noqa: BLE001
        return {"activities": [], "error": str(e)}


@server.tool(
    "get_mechanism",
    "[Local shim] Mechanism of action for a compound.",
    {
        "type": "object",
        "properties": {"molecule_chembl_id": {"type": "string"}},
        "required": ["molecule_chembl_id"],
    },
)
@memoize("chembl_shim_mechanism", ttl_seconds=30 * 24 * 3600)
def get_mechanism(molecule_chembl_id: str):
    try:
        data = http.get_json(f"{_BASE}/mechanism.json",
                             params={"molecule_chembl_id": molecule_chembl_id, "format": "json"})
        return {"mechanisms": (data or {}).get("mechanisms") or []}
    except Exception as e:  # noqa: BLE001
        return {"mechanisms": [], "error": str(e)}


@server.tool(
    "drug_search",
    "[Local shim] Search approved drugs by name / indication.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    },
)
def drug_search(query: str, limit: int = 20):
    try:
        data = http.get_json(f"{_BASE}/drug/search.json",
                             params={"q": query, "limit": limit})
        return {"results": (data or {}).get("drugs") or []}
    except Exception as e:  # noqa: BLE001
        return {"results": [], "error": str(e)}


@server.tool(
    "get_admet",
    "[Local shim] ADMET properties (from molecule properties + drug_indication endpoint).",
    {
        "type": "object",
        "properties": {"molecule_chembl_id": {"type": "string"}},
        "required": ["molecule_chembl_id"],
    },
)
@memoize("chembl_shim_admet", ttl_seconds=30 * 24 * 3600)
def get_admet(molecule_chembl_id: str):
    try:
        mol = http.get_json(f"{_BASE}/molecule/{molecule_chembl_id}.json")
    except Exception as e:  # noqa: BLE001
        return {"exists": False, "error": str(e)}
    props = mol.get("molecule_properties") or {}
    return {
        "exists": True,
        "chembl_id": mol.get("molecule_chembl_id"),
        "pref_name": mol.get("pref_name"),
        "max_phase": mol.get("max_phase"),
        "properties": {
            "mw": props.get("full_mwt"),
            "alogp": props.get("alogp"),
            "hba": props.get("hba"),
            "hbd": props.get("hbd"),
            "psa": props.get("psa"),
            "rtb": props.get("rtb"),
            "ro5_violations": props.get("num_ro5_violations"),
            "aromatic_rings": props.get("aromatic_rings"),
            "heavy_atoms": props.get("heavy_atoms"),
            "qed_weighted": props.get("qed_weighted"),
        },
        "molecule_type": mol.get("molecule_type"),
        "note": "ADMET here is derived from ChEMBL's molecule_properties; for in-vitro assays use get_bioactivity.",
    }


if __name__ == "__main__":
    server.run()
