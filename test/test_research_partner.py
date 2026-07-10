from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from packs._lib.proactive_research import (
    UPDATE_SCHEMA,
    ProactivePlanner,
    UpdateCandidate,
    build_proactive_refresh_plan,
    candidate_from_mapping,
    rank_research_updates,
)
from packs._lib.research_interest import (
    ConsentRequiredError,
    EventKind,
    LocalInterestStore,
    PrivacySettings,
    ProfileCorruptError,
    ResearchEvent,
    delete_research_profile,
    event_from_mapping,
    inspect_research_profile,
    record_research_event,
)


def _local_time(day: int = 5, hour: int = 10) -> datetime:
    tz = datetime.now().astimezone().tzinfo
    return datetime(2026, 7, day, hour, 0, tzinfo=tz)


def _trained_store(tmp_path, *, consent: bool = True) -> LocalInterestStore:
    store = LocalInterestStore(tmp_path / "profile.json", consent=consent)
    store.record(
        ResearchEvent(
            EventKind.PAPER_SAVED,
            topics=["EGFR", "glioblastoma"],
            task_type="lit-review",
            item_id="PMID:12345678",
            occurred_at=_local_time(),
        )
    )
    store.record(
        ResearchEvent(
            EventKind.ENTITY_QUERIED,
            topics=["EGFR"],
            task_type="target-discovery",
            occurred_at=_local_time(hour=10),
        )
    )
    return store


def test_learning_is_fail_closed_and_creates_no_files_without_consent(tmp_path):
    path = tmp_path / "private" / "profile.json"
    store = LocalInterestStore(path)

    with pytest.raises(ConsentRequiredError):
        store.record(ResearchEvent(EventKind.ENTITY_QUERIED, topics=["EGFR"]))

    assert not path.exists()
    assert not path.parent.exists()


def test_hmac_profile_contains_aggregates_but_no_raw_topic_or_item(tmp_path):
    store = _trained_store(tmp_path)
    payload = store.path.read_text(encoding="utf-8").lower()

    assert "egfr" not in payload
    assert "glioblastoma" not in payload
    assert "12345678" not in payload
    assert "hmac-sha256:" in payload
    assert "raw" not in payload

    loaded = LocalInterestStore(store.path)
    inspected = loaded.inspect(["EGFR", "glioblastoma", "TP53"])
    assert inspected["profile_exists"] is True
    assert loaded.model().was_seen("PMID:12345678", at=_local_time(day=9)) is True
    assert [row["topic"] for row in inspected["top_interests"]] == [
        "egfr",
        "glioblastoma",
    ]


def test_repeated_queries_raise_attention_and_rejection_is_weak_negative(tmp_path):
    store = _trained_store(tmp_path)
    store.record(
        ResearchEvent(
            EventKind.SUGGESTION_REJECTED,
            topics=["EGFR"],
            item_id="PMID:222",
            occurred_at=_local_time(),
        )
    )
    store.record(
        ResearchEvent(
            EventKind.ENTITY_QUERIED,
            topics=["TP53"],
            occurred_at=_local_time(),
        )
    )

    model = store.model()
    assert model.topic_score("EGFR", _local_time()) == pytest.approx(3.25)
    assert model.topic_score("TP53", _local_time()) == pytest.approx(1.0)
    assert model.topic_score("EGFR", _local_time()) > model.topic_score("TP53", _local_time())


def test_interest_decay_and_coarse_workflow_prediction(tmp_path):
    store = _trained_store(tmp_path)
    model = store.model()
    original = model.topic_score("EGFR", _local_time())
    after_half_life = model.topic_score("EGFR", _local_time() + timedelta(days=90))
    assert after_half_life == pytest.approx(original / 2, rel=1e-6)

    prediction = model.predict_workflow(_local_time(hour=10))
    assert prediction
    assert prediction[0]["time_bucket"] == "weekend:06-12"
    assert all("2026" not in row["time_bucket"] for row in prediction)


def test_local_ranking_prefers_relevant_recent_updates_and_suppresses_seen(tmp_path):
    store = _trained_store(tmp_path)
    planner = ProactivePlanner(store.model())
    now = _local_time(day=9)
    recent = UpdateCandidate(
        candidate_id="PMID:NEW",
        kind="paper",
        title="EGFR resistance states in glioblastoma",
        topics=["EGFR", "glioblastoma"],
        source="PubMed",
        published_at=now.date(),
        evidence_score=0.8,
    )
    old = UpdateCandidate(
        candidate_id="10.1101/OLD",
        kind="preprint",
        title="EGFR signaling study",
        topics=["EGFR"],
        source="bioRxiv",
        published_at=now.date() - timedelta(days=180),
    )
    unrelated = UpdateCandidate(
        candidate_id="NCT00000001",
        kind="clinical_trial",
        title="Unrelated trial",
        topics=["CFTR"],
        source="ClinicalTrials.gov",
        published_at=now.date(),
    )

    ranked = planner.rank_updates([old, unrelated, recent], at=now)
    assert [row["candidate_id"] for row in ranked["recommendations"]] == [
        "PMID:NEW",
        "10.1101/OLD",
    ]
    assert ranked["diagnostics"]["irrelevant_suppressed"] == 1
    assert ranked["privacy"]["candidate_content_persisted"] is False

    store.record(
        ResearchEvent(
            EventKind.RECOMMENDATION_SHOWN,
            item_id=recent.item_key(),
            occurred_at=now,
        )
    )
    reranked = ProactivePlanner(store.model()).rank_updates([recent, old], at=now)
    assert [row["candidate_id"] for row in reranked["recommendations"]] == [
        "10.1101/OLD"
    ]
    assert reranked["diagnostics"]["seen_suppressed"] == 1


def test_saved_public_identifier_is_not_recommended_again(tmp_path):
    store = _trained_store(tmp_path)
    saved = UpdateCandidate(
        candidate_id="PMID:12345678",
        kind="paper",
        title="Already saved EGFR paper",
        topics=["EGFR"],
        source="PubMed",
        published_at=_local_time().date(),
    )
    ranked = ProactivePlanner(store.model()).rank_updates([saved], at=_local_time())
    assert ranked["recommendations"] == []
    assert ranked["diagnostics"]["seen_suppressed"] == 1


def test_refresh_plan_uses_local_catalog_and_is_network_gated_by_default(tmp_path):
    store = _trained_store(tmp_path)
    store.record(
        ResearchEvent(
            EventKind.WORKFLOW_OBSERVED,
            task_type="clinical-trials",
            occurred_at=_local_time(hour=10),
        )
    )
    planner = ProactivePlanner(store.model())

    blocked = planner.build_refresh_plan(
        ["EGFR", "glioblastoma", "CFTR"], at=_local_time(hour=10)
    )
    assert blocked["status"] == "awaiting_network_consent"
    assert blocked["privacy"]["network_performed"] is False
    assert all(action["dispatch"] == "requires_consent" for action in blocked["actions"])
    assert blocked["actions"][0]["tool"] == "ctgov_search"
    assert blocked["actions"][0]["server"] == "bio-trials-ctgov"
    assert {action["pack"] for action in blocked["actions"]} == {"bio-lit", "bio-trials"}
    assert "egfr" in blocked["actions"][0]["arguments"]["term"]

    allowed = planner.build_refresh_plan(
        ["EGFR", "glioblastoma"],
        at=_local_time(hour=10),
        allow_remote_queries=True,
    )
    assert allowed["status"] == "ready"
    assert all(action["dispatch"] == "ready" for action in allowed["actions"])


def test_hmac_watch_plan_needs_local_catalog_match(tmp_path):
    store = _trained_store(tmp_path)
    plan = ProactivePlanner(store.model()).build_refresh_plan(["CFTR"])
    assert plan["status"] == "insufficient_local_context"
    assert plan["actions"] == []


def test_inspect_opt_out_and_explicit_delete(tmp_path):
    store = _trained_store(tmp_path)
    key_path = store.key_path
    assert store.inspect(["EGFR"])["learning_enabled"] is True

    result = store.opt_out(delete_data=True)
    assert result == {"ok": True, "learning_enabled": False, "data_deleted": True}
    assert not store.path.exists()
    assert not key_path.exists()
    assert store.inspect()["profile_exists"] is False
    with pytest.raises(ConsentRequiredError):
        store.record(ResearchEvent(EventKind.ENTITY_QUERIED, topics=["EGFR"]))


def test_corrupt_profile_is_never_silently_overwritten(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text("not-json", encoding="utf-8")
    store = LocalInterestStore(path, consent=True)

    with pytest.raises(ProfileCorruptError):
        store.record(ResearchEvent(EventKind.ENTITY_QUERIED, topics=["EGFR"]))

    assert path.read_text(encoding="utf-8") == "not-json"


def test_strict_json_schemas_reject_raw_text_fields():
    with pytest.raises(ValueError, match="intentionally forbidden"):
        event_from_mapping(
            {"kind": "entity_queried", "topics": ["EGFR"], "raw_query": "patient text"}
        )
    with pytest.raises(ValueError, match="unsupported fields"):
        candidate_from_mapping(
            {
                "schema": UPDATE_SCHEMA,
                "candidate_id": "PMID:1",
                "kind": "paper",
                "title": "A paper",
                "topics": ["EGFR"],
                "abstract": "not accepted by the ranking boundary",
            }
        )


def test_json_friendly_mcp_functions_round_trip(tmp_path):
    path = tmp_path / "mcp-profile.json"
    result = record_research_event(
        {
            "kind": "paper_saved",
            "topics": ["BRCA1", "breast cancer"],
            "task_type": "lit-review",
            "item_id": "PMID:999",
            "occurred_at": _local_time().isoformat(),
        },
        profile_path=path,
        consent=True,
    )
    assert result["raw_event_retained"] is False
    assert inspect_research_profile(
        profile_path=path, topic_catalog=["BRCA1", "EGFR"]
    )["top_interests"][0]["topic"] == "brca1"

    ranked = rank_research_updates(
        [
            {
                "schema": UPDATE_SCHEMA,
                "candidate_id": "PMID:1000",
                "kind": "paper",
                "title": "BRCA1 update",
                "topics": ["BRCA1"],
                "source": "PubMed",
                "published_at": _local_time().date().isoformat(),
            }
        ],
        profile_path=path,
    )
    assert ranked["count"] == 1
    assert build_proactive_refresh_plan(
        ["BRCA1"], profile_path=path
    )["status"] == "awaiting_network_consent"

    with pytest.raises(ConsentRequiredError):
        delete_research_profile(profile_path=path)
    assert delete_research_profile(profile_path=path, confirm=True)["deleted"] is True
