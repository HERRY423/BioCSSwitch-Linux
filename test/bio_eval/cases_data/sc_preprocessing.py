"""单细胞预处理类 gold cases。考核：是否调用 QC / doublet / preprocess / batch 配方，不编造结果。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schemas  # noqa: E402

CATEGORY = "sc_preprocessing"


def _score_preprocessing_provenance(ctx):
    text = (ctx["final_text"] or "").lower()
    has_fingerprint = "fingerprint" in text or "指纹" in text
    has_recipe_hash = "recipe_hash" in text or "hash" in text or "哈希" in text
    mentions_counts = "counts" in text or "raw" in text or "原始计数" in text
    return 1.0 if has_fingerprint and has_recipe_hash and mentions_counts else 0.6 if has_fingerprint and has_recipe_hash else 0.3


def _score_geneformer_id_route(ctx):
    text = (ctx["final_text"] or "").lower()
    needs_ensembl = "ensembl" in text
    converts_symbols = any(k in text for k in ["symbol", "gene symbol", "基因 id", "转换"])
    skips_log_hvg = any(k in text for k in ["不做 log", "跳过 log", "rank-value", "hvg"])
    return 1.0 if needs_ensembl and converts_symbols and skips_log_hvg else 0.6 if needs_ensembl and converts_symbols else 0.2


CASES = [
    {
        "id": "sc_prep_qc_doublet_batch",
        "prompt": "我有 10x PBMC h5ad，约 18000 个细胞，3 个 batch。请规划 QC、doublet、scanpy 预处理和 batch 整合，不要声称已经跑出结果。",
        "tools": schemas.resolve(["anndata_fingerprint", "sc_qc_thresholds", "sc_doublet_recipe", "sc_preprocess_recipe", "sc_batch_recipe"]),
        "max_tokens": 900,
        "rubric": {
            "expect_tools": ["anndata_fingerprint", "sc_doublet_recipe", "sc_preprocess_recipe", "sc_batch_recipe"],
            "gate": ["tool_invoked"],
            "custom": _score_preprocessing_provenance,
        },
    },
    {
        "id": "sc_prep_geneformer_id",
        "prompt": "这个 AnnData 的 var_names 是 gene symbol，但我要后面跑 Geneformer。请给出预处理和基因 ID 转换路线。",
        "tools": schemas.resolve(["anndata_fingerprint", "sc_geneid_convert", "sc_preprocess_recipe"]),
        "max_tokens": 800,
        "rubric": {
            "expect_tools": ["sc_geneid_convert", "sc_preprocess_recipe"],
            "gate": ["tool_invoked"],
            "custom": _score_geneformer_id_route,
        },
    },
]

for _c in CASES:
    _c["category"] = CATEGORY
    _c.setdefault("tool_choice", "auto")
