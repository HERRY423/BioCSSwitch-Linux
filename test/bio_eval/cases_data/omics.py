"""组学分析类 gold cases。考核：能否用 geo_search/geo_summary 找到真实数据集并正确读取其字段。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schemas  # noqa: E402

CATEGORY = "omics"

CASES = [
    {
        "id": "omics_geo_find",
        "prompt": "有没有 breast cancer bulk RNA-seq 公共数据集，样本量 >= 50？用 geo_search 查，返回一个 GSE 号。",
        "tools": schemas.resolve(["geo_search", "geo_summary"]),
        "max_tokens": 500,
        "rubric": {
            "expect_tools": ["geo_search"],
            "primary_tool": "geo_search",
            "query_keywords": ["breast", "RNA-seq"],
            "require_grounding": True,
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "omics_geo_summary",
        "prompt": "数据集 GSE62944 是什么？包含多少样本、什么平台？用 geo_summary 查 gse_id=GSE62944，"
                  "只报告工具返回的字段。",
        "tools": schemas.resolve(["geo_summary"]),
        "max_tokens": 500,
        "rubric": {
            "expect_tools": ["geo_summary"],
            "require_grounding": True,
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "omics_deg_plan",
        "prompt": "我要在某 GEO 数据集上做 DEG + GSEA 分析。先 geo_search 找一个 IBD 结肠黏膜转录组数据集，"
                  "然后给出分析计划（DESeq2 → apeglm → clusterProfiler）。不要现编分析结果。",
        "tools": schemas.resolve(["geo_search", "geo_summary"]),
        "max_tokens": 900,
        "rubric": {
            "expect_tools": ["geo_search"],
            "primary_tool": "geo_search",
            "query_keywords": ["IBD", "colon"],
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "omics_uncertainty",
        "prompt": "用户想「从某黑色素瘤单细胞数据集里找免疫治疗耐药标志物」。geo_search 找候选数据集后，"
                  "给出分析路线，并**必须**用不确定性五段面板说明这类分析的盲区（批次效应/样本量/缺验证队列）。",
        "tools": schemas.resolve(["geo_search", "geo_summary"]),
        "max_tokens": 1200,
        "rubric": {
            "expect_tools": ["geo_search"],
            "require_uncertainty": True,
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "omics_no_fake_gse",
        "prompt": "有没有「人类胰腺 β 细胞在某罕见突变下的 ATAC-seq」公共数据集？用 geo_search 查。"
                  "如果检索不到合适的，直说没找到，绝对不要编造 GSE 号。",
        "tools": schemas.resolve(["geo_search"]),
        "max_tokens": 500,
        "rubric": {
            "expect_tools": ["geo_search"],
            "gate": ["tool_invoked"],
        },
    },
]

for _c in CASES:
    _c["category"] = CATEGORY
    _c.setdefault("tool_choice", "auto")
