"""单细胞 embedding 类 gold cases。考核：是否串联 preprocess → scFM skeleton → provenance/quality。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schemas  # noqa: E402

CATEGORY = "sc_embedding"


def _score_embedding_skeleton(ctx):
    text = (ctx["final_text"] or "").lower()
    skeleton = any(k in text for k in ["skeleton", "不可直接运行", "not runnable", "systemexit"])
    provenance = "provenance" in text or "哈希" in text or "hash" in text
    quality = any(k in text for k in ["quality", "kbet", "ilisi", "clisi", "batch mixing", "bio conservation"])
    if skeleton and provenance and quality:
        return 1.0
    if skeleton and provenance:
        return 0.7
    return 0.2


def _score_finetune_skeleton(ctx):
    text = (ctx["final_text"] or "").lower()
    skeleton = any(k in text for k in ["skeleton", "不可直接运行", "not runnable", "systemexit"])
    training_fields = any(k in text for k in ["train", "split", "hyperparameter", "超参", "f1", "accuracy", "provenance"])
    return 1.0 if skeleton and training_fields else 0.5 if skeleton else 0.0


CASES = [
    {
        "id": "sc_embed_geneformer_quality",
        "prompt": "我要用 Geneformer 给预处理后的单细胞数据算 embedding，并评估 batch mixing 和 cell type conservation。请生成计划，不要假装运行。",
        "tools": schemas.resolve(["scfm_embed_plan", "scfm_embed_quality"]),
        "max_tokens": 900,
        "rubric": {
            "expect_tools": ["scfm_embed_plan", "scfm_embed_quality"],
            "gate": ["tool_invoked"],
            "custom": _score_embedding_skeleton,
        },
    },
    {
        "id": "sc_embed_finetune_skeleton",
        "prompt": "我要微调 scGPT 做 cell type annotation。请给 fine-tuning skeleton、超参和需要记录的 provenance。",
        "tools": schemas.resolve(["scfm_finetune_plan"]),
        "max_tokens": 800,
        "rubric": {
            "expect_tools": ["scfm_finetune_plan"],
            "gate": ["tool_invoked"],
            "custom": _score_finetune_skeleton,
        },
    },
]

for _c in CASES:
    _c["category"] = CATEGORY
    _c.setdefault("tool_choice", "auto")
