"""单细胞 DEG 类 gold cases。考核：pseudobulk vs Wilcoxon 路由。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schemas  # noqa: E402

CATEGORY = "sc_deg"


def _score_pseudobulk_method(ctx):
    text = (ctx["final_text"] or "").lower()
    has_method = "pseudobulk" in text or "pseudo-bulk" in text
    has_reps = any(k in text for k in ["replicate", "donor", "sample", "biological", "生物重复", "供体", "样本"])
    avoids_cell_reps = any(k in text for k in ["不要把细胞数当", "不能把细胞", "not treat cells", "biological replicate"])
    if has_method and has_reps:
        return 1.0
    if has_method or avoids_cell_reps:
        return 0.6
    return 0.2


def _score_marker_no_replicate(ctx):
    text = (ctx["final_text"] or "").lower()
    says_no_condition_deg = any(k in text for k in ["不能做严肃", "不能做 condition", "no biological replicate", "without replicates", "不是 condition-level"])
    gives_marker_route = any(k in text for k in ["marker", "wilcoxon", "rank_genes_groups", "cluster"])
    if says_no_condition_deg and gives_marker_route:
        return 1.0
    if says_no_condition_deg or gives_marker_route:
        return 0.5
    return 0.0


CASES = [
    {
        "id": "sc_deg_pseudobulk",
        "prompt": "我有病例/对照各 4 个 donor，已注释 cell_type。请为每个细胞类型做单细胞 DEG，优先 pseudobulk。",
        "tools": schemas.resolve(["sc_deg_recipe"]),
        "max_tokens": 700,
        "rubric": {
            "expect_tools": ["sc_deg_recipe"],
            "gate": ["tool_invoked"],
            "custom": _score_pseudobulk_method,
        },
    },
    {
        "id": "sc_deg_marker_no_replicate",
        "prompt": "我只有一个样本，想找 cluster marker。请给合适的单细胞 marker/DEG 路线，并说明不能做严肃 condition DEG。",
        "tools": schemas.resolve(["sc_deg_recipe", "sc_marker_recipe"]),
        "max_tokens": 800,
        "rubric": {
            "expect_tools": ["sc_deg_recipe"],
            "gate": ["tool_invoked"],
            "custom": _score_marker_no_replicate,
        },
    },
]

for _c in CASES:
    _c["category"] = CATEGORY
    _c.setdefault("tool_choice", "auto")
