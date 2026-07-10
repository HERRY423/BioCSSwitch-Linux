from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))

import task_router  # noqa: E402


def _request(text: str):
    return {"messages": [{"role": "user", "content": text}]}


def test_routes_crossmodal_unmet_need_before_generic_target_discovery():
    req = _request("从未满足临床需求出发，做跨模态靶点发现和证据融合")
    assert task_router.detect_task(req) == "crossmodal-discovery"
    assert task_router.TASK_PROBES["crossmodal-discovery"] == [
        "tool_use",
        "long_ctx",
        "json_stable",
    ]


def test_routes_contradiction_driven_hypothesis_generation():
    req = _request("基于矛盾证据生成竞争假设，并给出区分性实验")
    assert task_router.detect_task(req) == "hypothesis-generation"


def test_routes_local_personalized_research_partner():
    req = _request("建立隐私优先的研究兴趣模型和主动简报")
    assert task_router.detect_task(req) == "research-partner"
