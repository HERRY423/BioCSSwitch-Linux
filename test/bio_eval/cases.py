"""生医 benchmark case 加载器。

历史上 case 与评分器都写死在本文件里（10 个 case）。需求 4 之后，case 拆进
`cases_data/<category>.py`（9 大类），评分逻辑抽进 `rubric.py`（多维评分）。
本文件只做加载与筛选，保留 `CASES` / `cases_by_ids` 供 run.py 引用（向后兼容）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from cases_data import ALL_CASES, CATEGORIES, counts_by_category

CASES: List[Dict[str, Any]] = ALL_CASES

__all__ = ["CASES", "CATEGORIES", "cases_by_ids", "counts_by_category"]


def cases_by_ids(ids: List[str] | None) -> List[Dict[str, Any]]:
    """按 case id 或 category 名筛选。None → 全部。"""
    if not ids:
        return CASES
    ids_set = set(ids)
    return [c for c in CASES if c["id"] in ids_set or c["category"] in ids_set]
