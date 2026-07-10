from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
sys.path.insert(0, str(PACKS))

from _lib.research_interest import ConsentRequiredError  # noqa: E402


def _load(rel: str, name: str):
    path = PACKS / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_pack_manifests_expose_servers_and_dependency_boundaries():
    partner = json.loads(
        (PACKS / "bio-research-partner" / "pack.json").read_text(encoding="utf-8")
    )
    crossmodal = json.loads(
        (PACKS / "bio-crossmodal" / "pack.json").read_text(encoding="utf-8")
    )

    assert partner["dependencies"] == partner["depends_on"]
    assert {"bio-lit", "bio-trials", "bio-kg", "bio-privacy"} <= set(
        partner["dependencies"]
    )
    assert partner["servers"][0]["name"] == "bio-research-partner"

    assert crossmodal["dependencies"] == crossmodal["depends_on"]
    assert {
        "bio-lit",
        "bio-gene",
        "bio-drug",
        "bio-trials",
        "bio-singlecell",
        "bio-spatial",
        "bio-kg",
    } <= set(crossmodal["dependencies"])
    assert crossmodal["servers"][0]["name"] == "bio-crossmodal"


def test_crossmodal_mcp_exposes_stateful_evidence_context_contract():
    module = _load("bio-crossmodal/crossmodal_server.py", "crossmodal_pack_test")
    assert {
        "crossmodal_plan_unmet_need",
        "crossmodal_reduce_evidence",
        "crossmodal_integrate_observations",
        "crossmodal_cross_validate",
        "crossmodal_rank_targets",
        "crossmodal_synthesize",
    } == set(module.server.tools)

    bundle = module.crossmodal_plan_unmet_need(
        {"disease": "glioblastoma", "unmet_need": "durable control after recurrence"}
    )
    assert bundle["context"]["records"] == []
    assert len(bundle["plan"]["steps"]) >= 12
    assert bundle["plan"]["execution_contract"]["missing_evidence_semantics"] == (
        "unknown_not_negative"
    )
    synthesis = module.crossmodal_synthesize(bundle["context"])
    assert synthesis["coverage"]["modalities_observed"] == []
    assert synthesis["ranking"]["targets"] == []


def test_research_partner_mcp_is_opt_in_local_and_deletable(tmp_path, monkeypatch):
    path = tmp_path / "partner" / "profile.json"
    monkeypatch.setenv("BIOCSSWITCH_INTEREST_PROFILE_PATH", str(path))
    module = _load(
        "bio-research-partner/research_partner_server.py", "research_partner_pack_test"
    )
    event = {
        "kind": "entity_queried",
        "topics": ["EGFR", "glioblastoma"],
        "task_type": "target-discovery",
    }

    with pytest.raises(ConsentRequiredError):
        module.research_interest_observe(event, consent=False)
    assert not path.exists()

    recorded = module.research_interest_observe(event, consent=True)
    assert recorded["raw_event_retained"] is False
    raw = path.read_text(encoding="utf-8").lower()
    assert "egfr" not in raw and "glioblastoma" not in raw

    brief = module.research_session_brief(["EGFR", "glioblastoma"])
    assert brief["network_performed"] is False
    assert brief["refresh_plan"]["status"] == "awaiting_network_consent"
    assert all(
        action["dispatch"] == "requires_consent"
        for action in brief["refresh_plan"]["actions"]
    )

    deleted = module.research_interest_delete(confirm=True)
    assert deleted["deleted"] is True
    assert not path.exists()


def test_research_partner_rejects_phi_like_topics_before_storage_or_refresh(
    tmp_path, monkeypatch
):
    path = tmp_path / "profile.json"
    monkeypatch.setenv("BIOCSSWITCH_INTEREST_PROFILE_PATH", str(path))
    module = _load(
        "bio-research-partner/research_partner_server.py", "research_partner_phi_test"
    )

    with pytest.raises(ValueError, match="possible PHI"):
        module.research_interest_observe(
            {"kind": "entity_queried", "topics": ["MRN:123456"]}, consent=True
        )
    assert not path.exists()
    with pytest.raises(ValueError, match="possible PHI"):
        module.research_refresh_plan(["patient@example.org"], allow_remote_queries=True)


def test_bio_eval_registry_can_execute_new_pack_tools(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "BIOCSSWITCH_INTEREST_PROFILE_PATH", str(tmp_path / "executor-profile.json")
    )
    bio_eval = ROOT / "test" / "bio_eval"
    sys.path.insert(0, str(bio_eval))
    import tool_executor

    tool_executor._REGISTRY = None
    names = set(tool_executor.available_tool_names())
    assert "research_interest_observe" in names
    assert "crossmodal_plan_unmet_need" in names
    assert "kg_generate_hypotheses" in names
