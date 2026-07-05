"""JSON 稳定性类 gold cases。考核：能否稳定输出严格、可解析、符合 schema 的 JSON。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schemas  # noqa: E402

CATEGORY = "json_stability"


def _score_parseable_only(ctx):
    """整段或 fenced block 能被 json.loads 解析即 1.0。"""
    text = ctx["final_text"] or ""
    cands = [m.group(1) for m in re.finditer(r"```(?:json)?\s*([\[{][\s\S]*?[\]}])\s*```", text)]
    cands.append(text.strip())
    for c in cands:
        try:
            json.loads(c)
            return 1.0
        except Exception:  # noqa: BLE001
            continue
    return 0.0


def _score_no_prose(ctx):
    """要求纯 JSON、无解释文本：整段就是可解析 JSON（无 fenced、无前后散文）得满分。"""
    text = (ctx["final_text"] or "").strip()
    try:
        json.loads(text)
        return 1.0
    except Exception:  # noqa: BLE001
        # 有 fenced block 但夹带散文 → 半分
        return 0.5 if re.search(r"```", text) else 0.0


CASES = [
    {
        "id": "json_evidence_table",
        "prompt": "以严格 JSON 输出一张证据表，形如："
                  "```json\n{\"claims\":[{\"claim\":\"...\",\"refs\":[{\"id_type\":\"pmid\",\"id\":\"...\"}],"
                  "\"verdict\":\"supported\"}]}\n```\n随便举 2 条医学声明。不要解释文本，只要 JSON。",
        "tools": [],
        "max_tokens": 500,
        "rubric": {
            "json_shape": {"root": "object", "require_keys": ["claims"],
                           "item_keys": ["claim", "refs", "verdict"]},
        },
    },
    {
        "id": "json_nested_strict",
        "prompt": "只输出严格 JSON（无 markdown、无解释）：一个对象，含 key `study`（字符串）、"
                  "`n`（整数）、`arms`（字符串数组，至少 2 个）、`primary_endpoint`（字符串）。"
                  "内容随便编一个虚构试验的字段即可。",
        "tools": [],
        "max_tokens": 400,
        "rubric": {
            "json_shape": {"root": "object", "require_keys": ["study", "n", "arms", "primary_endpoint"]},
            "custom": _score_no_prose,
        },
    },
    {
        "id": "json_array_of_objects",
        "prompt": "输出一个 JSON 数组，3 个元素，每个是 {\"gene\":..., \"disease\":..., \"evidence\":...}。"
                  "只要 JSON。",
        "tools": [],
        "max_tokens": 400,
        "rubric": {
            "json_shape": {"root": "array", "item_keys": ["gene", "disease", "evidence"]},
        },
    },
    {
        "id": "json_escape_hard",
        "prompt": "输出严格 JSON：{\"doi\":\"...\",\"title\":\"...\"}，title 里**故意**包含双引号和反斜杠"
                  "（例如书名号或引语），确保转义正确、仍可被解析。只要 JSON。",
        "tools": [],
        "max_tokens": 400,
        "rubric": {
            "json_shape": {"root": "object", "require_keys": ["doi", "title"]},
            "custom": _score_parseable_only,
        },
    },
    {
        "id": "json_no_trailing_prose",
        "prompt": "只输出这个 JSON，之后**不要**再写任何一句话："
                  "{\"ok\":true,\"count\":3,\"items\":[\"a\",\"b\",\"c\"]}",
        "tools": [],
        "max_tokens": 200,
        "rubric": {
            "json_shape": {"root": "object", "require_keys": ["ok", "count", "items"]},
            "custom": _score_no_prose,
        },
    },
]

for _c in CASES:
    _c["category"] = CATEGORY
    _c.setdefault("tool_choice", "auto")
