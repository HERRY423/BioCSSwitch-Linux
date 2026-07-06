"""单细胞注释类 gold cases。考核：按组织/物种选择 annotation reference 并保留不确定性。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schemas  # noqa: E402

CATEGORY = "sc_annotation"


def _score_annotation_qc(ctx):
    text = (ctx["final_text"] or "").lower()
    has_reference = any(k in text for k in ["celltypist", "reference", "model", "参考"])
    has_confidence = any(k in text for k in ["confidence", "conf_score", "置信", "qc", "umap"])
    return 1.0 if has_reference and has_confidence else 0.5 if has_reference else 0.1


def _score_cellxgene_metadata(ctx):
    text = (ctx["final_text"] or "").lower()
    has_search = "cellxgene" in text or "census" in text
    has_metadata = any(k in text for k in ["dataset_id", "n_obs", "citation", "license", "metadata", "元数据"])
    return 1.0 if has_search and has_metadata else 0.5 if has_search else 0.1


CASES = [
    {
        "id": "sc_annotation_celltypist_pbmc",
        "prompt": "PBMC 数据聚类后，我想用 CellTypist 做细胞类型注释并输出置信度 QC。请生成配方。",
        "tools": schemas.resolve(["sc_celltype_recipe"]),
        "max_tokens": 700,
        "rubric": {
            "expect_tools": ["sc_celltype_recipe"],
            "gate": ["tool_invoked"],
            "custom": _score_annotation_qc,
        },
    },
    {
        "id": "sc_annotation_reference_search",
        "prompt": "我需要找一个 human lung 的公开单细胞参考数据集辅助注释。请给 CELLxGENE 检索计划。",
        "tools": schemas.resolve(["cellxgene_search", "sc_celltype_recipe"]),
        "max_tokens": 800,
        "rubric": {
            "expect_tools": ["cellxgene_search"],
            "gate": ["tool_invoked"],
            "custom": _score_cellxgene_metadata,
        },
    },
]

for _c in CASES:
    _c["category"] = CATEGORY
    _c.setdefault("tool_choice", "auto")
