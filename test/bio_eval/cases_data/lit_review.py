"""文献综述类 gold cases。考核：检索意图对不对、结果被不被引用、综述结论是否暴露不确定性。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schemas  # noqa: E402

CATEGORY = "lit_review"

CASES = [
    {
        "id": "lit_metformin_cv_meta",
        "prompt": "帮我找 metformin 与心血管事件二级预防的一篇高被引 meta-analysis，返回 PMID。用 search_articles。",
        "tools": schemas.resolve(["search_articles", "pubmed_fetch"]),
        "max_tokens": 400,
        "rubric": {
            "expect_tools": ["search_articles"],
            "primary_tool": "search_articles",
            "query_keywords": ["metformin", "cardiovascular"],
            "require_grounding": True,
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "lit_three_topics",
        "prompt": "分别帮我查（1）阿司匹林一级预防、（2）statin 与糖尿病风险、（3）SGLT2 抑制剂心衰效应 "
                  "各 1-2 篇代表性文献 PMID。使用 search_articles，每个主题一次检索。",
        "tools": schemas.resolve(["search_articles", "pubmed_fetch"]),
        "max_tokens": 700,
        "rubric": {
            "expect_tools": ["search_articles"],
            "require_grounding": True,
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "lit_seed_expansion",
        "prompt": "我有一篇种子文献 PMID 31157855（SGLT2 与心衰）。帮我先 pubmed_fetch 拿到它的题录确认主题，"
                  "再 search_articles 扩检 3 篇同主题近 5 年文献，返回 PMID。",
        "tools": schemas.resolve(["search_articles", "pubmed_fetch"]),
        "max_tokens": 700,
        "rubric": {
            "expect_tools": ["pubmed_fetch", "search_articles"],
            "require_grounding": True,
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "lit_two_source",
        "prompt": "综述「PARP 抑制剂在 BRCA 突变卵巢癌维持治疗」的证据。用 search_articles 和 europepmc_search "
                  "各检一次，去重后给 3-5 篇关键 PMID/DOI。",
        "tools": schemas.resolve(["search_articles", "europepmc_search"]),
        "max_tokens": 800,
        "rubric": {
            "expect_tools": ["search_articles", "europepmc_search"],
            "primary_tool": "search_articles",
            "query_keywords": ["PARP", "ovarian"],
            "require_grounding": True,
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "lit_synthesis_uncertainty",
        "prompt": "系统地综述「维生素 D 补充能否降低普通人群癌症死亡率」。先 search_articles 检索证据，"
                  "然后给出综述结论，并**必须**在结尾输出不确定性五段面板："
                  "Known knowns / Known unknowns / Conflicts / Missing data / Next experiment。",
        "tools": schemas.resolve(["search_articles", "pubmed_fetch"]),
        "max_tokens": 1200,
        "rubric": {
            "expect_tools": ["search_articles"],
            "require_grounding": True,
            "require_uncertainty": True,
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "lit_conflict_surfacing",
        "prompt": "关于「β-胡萝卜素补充与肺癌风险」，文献里存在相互矛盾的结论。用 search_articles 检索，"
                  "在综述里显式指出冲突证据（哪些研究方向相反），并按证据等级排序。结尾给不确定性五段面板。",
        "tools": schemas.resolve(["search_articles", "pubmed_fetch"]),
        "max_tokens": 1200,
        "rubric": {
            "expect_tools": ["search_articles"],
            "require_grounding": True,
            "require_uncertainty": True,
            "gate": ["tool_invoked"],
        },
    },
]

for _c in CASES:
    _c["category"] = CATEGORY
    _c.setdefault("tool_choice", "auto")
