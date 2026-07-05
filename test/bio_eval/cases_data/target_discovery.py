"""靶点发现类 gold cases。考核：疾病→靶点、靶点→证据链，警惕 text-mining 弱证据。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schemas  # noqa: E402

CATEGORY = "target_discovery"

CASES = [
    {
        "id": "td_compile_first",
        "prompt": "用户问：「EGFR 在 GBM 里还有没有新靶点价值」。先调用 compile_research_question 把它编译成结构化任务，"
                  "再按编译出的 recommended_toolchain 起手第一步。",
        "tools": schemas.resolve(["compile_research_question", "ot_disease_associated_targets",
                                  "search_trials"]),
        "max_tokens": 900,
        "rubric": {
            "expect_tools": ["compile_research_question"],
            "primary_tool": "compile_research_question",
            "query_keywords": ["EGFR", "GBM"],
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "td_disease_targets",
        "prompt": "三阴乳腺癌（TNBC，EFO id 用 EFO_0005537 近似）有哪些高分关联靶点？"
                  "用 ot_disease_associated_targets 拉 top，报告 symbol 清单。",
        "tools": schemas.resolve(["ot_disease_associated_targets"]),
        "max_tokens": 700,
        "rubric": {
            "expect_tools": ["ot_disease_associated_targets"],
            "require_grounding": False,
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "td_target_druggable",
        "prompt": "KRAS 作为靶点，成药性怎么样？先 compound_search 看 ChEMBL 里有没有活性化合物，"
                  "再 search_trials 看有没有在研药物（intervention=sotorasib）。综合判断。",
        "tools": schemas.resolve(["compound_search", "search_trials", "ot_target_associated_diseases"]),
        "max_tokens": 900,
        "rubric": {
            "expect_tools": ["compound_search", "search_trials"],
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "td_evidence_chain",
        "prompt": "有人说「IL6 是类风湿关节炎的核心靶点」。把这句话拆成 claim，用 evidence_graph 绑证据"
                  "（你给出你认为支持的 PMID + stance），报告证据等级、适用边界、有没有反证。",
        "tools": schemas.resolve(["evidence_graph", "search_articles"]),
        "max_tokens": 1000,
        "rubric": {
            "expect_tools": ["evidence_graph"],
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "td_full_uncertainty",
        "prompt": "评估「STING 激动剂作为实体瘤新靶点」的价值。compile_research_question 起手，"
                  "检索证据后给判断，结尾**必须**给不确定性五段面板，特别是要暴露临床转化的已知失败/盲区。",
        "tools": schemas.resolve(["compile_research_question", "search_articles", "search_trials",
                                  "evidence_graph"]),
        "max_tokens": 1300,
        "rubric": {
            "expect_tools": ["compile_research_question"],
            "require_uncertainty": True,
            "gate": ["tool_invoked"],
        },
    },
    {
        "id": "td_weak_evidence_flag",
        "prompt": "某数据库给「TREM2 与阿尔茨海默病」高关联分，但可能主要来自文献共现（text-mining）。"
                  "用 evidence_graph 对这条关联做审计，区分功能证据和纯共现，别把弱证据当强证据。",
        "tools": schemas.resolve(["evidence_graph", "search_articles"]),
        "max_tokens": 1000,
        "rubric": {
            "expect_tools": ["evidence_graph"],
            "gate": ["tool_invoked"],
        },
    },
]

for _c in CASES:
    _c["category"] = CATEGORY
    _c.setdefault("tool_choice", "auto")
