#!/usr/bin/env python3
"""RxNorm MCP server：药物名称规范化（品牌 ↔ 通用名 ↔ 成分）。

工具：
  rxnorm_find_rxcui   — 药名 → RxCUI
  rxnorm_related      — RxCUI → 相关概念（成分 / 品牌 / 规格）
  rxnorm_ndc          — NDC 码 → RxCUI + 属性
  rxnorm_interactions — RxCUI 列表 → 已知药物相互作用（NIH DDI API）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://rxnav.nlm.nih.gov/REST"
server = MCPServer("bio-drug-rxnorm", "0.1.0")


@server.tool(
    "rxnorm_find_rxcui",
    "Find RxCUI by drug name (brand or generic).",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "search_type": {"type": "integer", "default": 2,
                            "description": "0=exact, 1=normalized, 2=approximate"},
        },
        "required": ["name"],
    },
)
@memoize("rxnorm_find", ttl_seconds=30 * 24 * 3600)
def rxnorm_find_rxcui(name: str, search_type: int = 2):
    data = http.get_json(f"{_BASE}/rxcui.json",
                         params={"name": name, "search": search_type})
    ids = ((data or {}).get("idGroup") or {}).get("rxnormId") or []
    return {"rxcuis": ids, "name": name}


@server.tool(
    "rxnorm_related",
    "Related concepts for a RxCUI, grouped by TTY (SBD=brand, SCD=clinical drug, IN=ingredient, ...).",
    {
        "type": "object",
        "properties": {
            "rxcui": {"type": "string"},
            "tty": {"type": "string", "default": "IN+PIN+MIN+SBD+SCD"},
        },
        "required": ["rxcui"],
    },
)
def rxnorm_related(rxcui: str, tty: str = "IN+PIN+MIN+SBD+SCD"):
    data = http.get_json(f"{_BASE}/rxcui/{rxcui}/related.json",
                         params={"tty": tty})
    groups = ((data or {}).get("relatedGroup") or {}).get("conceptGroup") or []
    return {"groups": [
        {"tty": g.get("tty"),
         "concepts": [{"rxcui": c.get("rxcui"), "name": c.get("name")}
                      for c in (g.get("conceptProperties") or [])]}
        for g in groups
    ]}


@server.tool(
    "rxnorm_ndc",
    "Look up RxNorm by NDC (US drug product code).",
    {
        "type": "object",
        "properties": {"ndc": {"type": "string"}},
        "required": ["ndc"],
    },
)
def rxnorm_ndc(ndc: str):
    data = http.get_json(f"{_BASE}/ndcstatus.json", params={"ndc": ndc})
    return (data or {}).get("ndcStatus") or {}


@server.tool(
    "rxnorm_interactions",
    "Retrieve known drug-drug interactions among a list of RxCUIs "
    "(NLM DDI service). "
    "NOTE: NLM retired the public DDI endpoint in Jan 2024 — this tool falls back gracefully "
    "and returns 'endpoint_deprecated' when unreachable so LLM knows not to trust silence.",
    {
        "type": "object",
        "properties": {"rxcuis": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 20}},
        "required": ["rxcuis"],
    },
)
def rxnorm_interactions(rxcuis: list[str]):
    try:
        data = http.get_json(f"{_BASE}/interaction/list.json",
                             params={"rxcuis": " ".join(rxcuis)})
    except Exception as e:  # noqa: BLE001
        return {"endpoint_deprecated": True, "error": str(e),
                "hint": "NLM 已于 2024-01 关停公开 DDI 端点；请改用 openFDA label 里的 drug interactions 段。"}
    groups = ((data or {}).get("fullInteractionTypeGroup") or [])
    return {"groups": groups}


if __name__ == "__main__":
    server.run()
