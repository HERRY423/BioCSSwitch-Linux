"""多轮工具调用类 gold cases。考核：能否把上一轮工具结果喂给下一轮，链式完成任务。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schemas  # noqa: E402

CATEGORY = "multi_turn"


def _score_min_turns(min_turns):
    def _s(ctx):
        return 1.0 if ctx.get("n_turns", 0) >= min_turns else 0.4
    return _s


CASES = [
    {
        "id": "mt_chembl_chain",
        "prompt": "阿司匹林对 COX-1 的 IC50 大约多少？先 compound_search 拿 aspirin 的 ChEMBL id，"
                  "**再用上一步拿到的 id** 调 get_bioactivity 查活性。必须两步都走。",
        "tools": schemas.resolve(["compound_search", "get_bioactivity"]),
        "max_tokens": 700,
        "rubric": {
            "expect_tools": ["compound_search", "get_bioactivity"],
            "gate": ["tool_invoked"],
            "custom": _score_min_turns(2),
        },
    },
    {
        "id": "mt_pmid_then_verify",
        "prompt": "先 search_articles 找一篇 pembrolizumab 治疗黑色素瘤的关键 RCT，拿到 PMID 后，"
                  "**再用 evidence_verify** 校验这个 PMID 真实存在。两步都要。",
        "tools": schemas.resolve(["search_articles", "evidence_verify"]),
        "max_tokens": 900,
        "rubric": {
            "expect_tools": ["search_articles", "evidence_verify"],
            "require_grounding": True,
            "gate": ["tool_invoked"],
            "custom": _score_min_turns(2),
        },
    },
    {
        "id": "mt_trial_then_detail",
        "prompt": "先 search_trials 找一个 osimertinib 在 EGFR+ NSCLC 的 III 期试验，拿到 NCT 号后，"
                  "**再 get_trial_details** 拉它的主要终点。两步链式完成。",
        "tools": schemas.resolve(["search_trials", "get_trial_details"]),
        "max_tokens": 900,
        "rubric": {
            "expect_tools": ["search_trials", "get_trial_details"],
            "require_grounding": True,
            "gate": ["tool_invoked"],
            "custom": _score_min_turns(2),
        },
    },
    {
        "id": "mt_compile_route_execute",
        "prompt": "用户问「KRAS 在胰腺癌里有没有靶点价值」。第一轮 compile_research_question 编译，"
                  "第二轮按编译出的 toolchain 起手（如 ot_disease_associated_targets 或 search_trials）。至少两轮工具调用。",
        "tools": schemas.resolve(["compile_research_question", "ot_disease_associated_targets", "search_trials"]),
        "max_tokens": 1000,
        "rubric": {
            "expect_tools": ["compile_research_question"],
            "gate": ["tool_invoked"],
            "custom": _score_min_turns(2),
        },
    },
    {
        "id": "mt_full_pipeline",
        "prompt": "完整走一遍：① search_articles 找「二甲双胍与结直肠癌预防」证据 → ② evidence_graph 绑证据 "
                  "→ ③ uncertainty_ledger 出五段面板。三步链式，最后答复里带五段面板。",
        "tools": schemas.resolve(["search_articles", "evidence_graph", "uncertainty_ledger"]),
        "max_tokens": 1500,
        "rubric": {
            "expect_tools": ["search_articles", "evidence_graph", "uncertainty_ledger"],
            "require_uncertainty": True,
            "gate": ["tool_invoked"],
            "custom": _score_min_turns(3),
        },
    },
]

for _c in CASES:
    _c["category"] = CATEGORY
    _c.setdefault("tool_choice", "auto")
