#!/usr/bin/env python3
"""openFDA MCP server：FDA 药品标签（processing label） + 不良事件（FAERS）。

工具：
  fda_label         — 按药名 / 有效成分搜标签（indications, contraindications, warnings, DDI）
  fda_adverse       — FAERS 不良事件报告聚合（按药名 / 反应词）
  fda_recall        — 召回记录

API：https://api.fda.gov/*  匿名 40 req/min，登记后 240 req/min。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://api.fda.gov"
server = MCPServer("bio-drug-openfda", "0.1.0")


def _auth():
    key = os.environ.get("OPENFDA_API_KEY")
    return {"api_key": key} if key else {}


def _flatten_label(r: dict) -> dict:
    """openFDA label 字段是数组，取首个字符串省得答复过大。"""
    def first(k):
        v = r.get(k)
        if isinstance(v, list) and v:
            return v[0]
        return v
    return {
        "brand_name": first("openfda") and (r.get("openfda", {}).get("brand_name") or [None])[0],
        "generic_name": (r.get("openfda", {}).get("generic_name") or [None])[0]
                        if r.get("openfda") else None,
        "manufacturer": (r.get("openfda", {}).get("manufacturer_name") or [None])[0]
                        if r.get("openfda") else None,
        "indications": first("indications_and_usage"),
        "dosage": first("dosage_and_administration"),
        "contraindications": first("contraindications"),
        "warnings": first("warnings") or first("warnings_and_cautions"),
        "boxed_warning": first("boxed_warning"),
        "adverse_reactions": first("adverse_reactions"),
        "drug_interactions": first("drug_interactions"),
        "pregnancy": first("pregnancy"),
        "pediatric_use": first("pediatric_use"),
        "geriatric_use": first("geriatric_use"),
        "mechanism_of_action": first("mechanism_of_action"),
    }


@server.tool(
    "fda_label",
    "Search FDA drug labels. Query supports openFDA search syntax, "
    "e.g. 'openfda.generic_name:metformin' or 'indications_and_usage:diabetes'.",
    {
        "type": "object",
        "properties": {
            "search": {"type": "string"},
            "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
        },
        "required": ["search"],
    },
)
def fda_label(search: str, limit: int = 5):
    params = {"search": search, "limit": limit, **_auth()}
    try:
        data = http.get_json(f"{_BASE}/drug/label.json", params=params)
    except Exception as e:  # noqa: BLE001
        return {"results": [], "error": str(e)}
    return {"results": [_flatten_label(r) for r in (data or {}).get("results") or []]}


@server.tool(
    "fda_adverse",
    "Aggregate adverse-event reports (FAERS) for a drug. Counts by reaction MedDRA term.",
    {
        "type": "object",
        "properties": {
            "drug": {"type": "string", "description": "Generic or brand name"},
            "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
        },
        "required": ["drug"],
    },
)
def fda_adverse(drug: str, limit: int = 25):
    search = f'patient.drug.medicinalproduct:"{drug}" OR patient.drug.openfda.generic_name:"{drug}"'
    params = {"search": search, "count": "patient.reaction.reactionmeddrapt.exact",
              "limit": limit, **_auth()}
    try:
        data = http.get_json(f"{_BASE}/drug/event.json", params=params)
    except Exception as e:  # noqa: BLE001
        return {"reactions": [], "error": str(e)}
    return {"reactions": [
        {"term": r.get("term"), "count": r.get("count")}
        for r in (data or {}).get("results") or []
    ]}


@server.tool(
    "fda_recall",
    "Search FDA drug recall records (Enforcement Reports).",
    {
        "type": "object",
        "properties": {
            "search": {"type": "string", "description": "e.g. 'product_description:metformin'"},
            "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
        },
        "required": ["search"],
    },
)
def fda_recall(search: str, limit: int = 25):
    try:
        data = http.get_json(f"{_BASE}/drug/enforcement.json",
                             params={"search": search, "limit": limit, **_auth()})
    except Exception as e:  # noqa: BLE001
        return {"results": [], "error": str(e)}
    results = []
    for r in (data or {}).get("results") or []:
        results.append({
            "recall_number": r.get("recall_number"),
            "product": r.get("product_description"),
            "reason": r.get("reason_for_recall"),
            "classification": r.get("classification"),
            "status": r.get("status"),
            "recall_initiation_date": r.get("recall_initiation_date"),
            "distribution_pattern": r.get("distribution_pattern"),
        })
    return {"results": results}


if __name__ == "__main__":
    server.run()
