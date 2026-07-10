"""Focused offline tests for contradiction-driven hypothesis generation."""

from __future__ import annotations

import importlib.util
import copy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
if str(PACKS) not in sys.path:
    sys.path.insert(0, str(PACKS))

from _lib import causal_kg, contradiction_hypotheses as engine  # noqa: E402


def _edges():
    return [
        {
            "id": "edge_positive",
            "subject": {"name": "STAT3", "type": "gene"},
            "relation": "causally_upregulates",
            "object": {"name": "PDL1", "type": "gene"},
            "context": "adult recurrent glioblastoma tumor",
            "model_system": "patient-derived organoid",
            "species": "human",
            "population": "adult recurrent disease",
            "tissue": "brain tumor",
            "dose": "80% CRISPRi knockdown",
            "timepoint": "6 hours",
            "endpoint": "PDL1 mRNA",
            "experiment_type": ["CRISPRi", "qPCR"],
            "study_design": "controlled perturbation",
            "evidence": ["PMID:11111111"],
            "confidence": 0.86,
            "claim_text": "STAT3 upregulates PDL1 after acute perturbation.",
            "source": "bio-lit:pubmed",
            "timestamp": "2026-01-02T00:00:00Z",
        },
        {
            "id": "edge_negative",
            "subject": {"name": "STAT3", "type": "gene"},
            "relation": "causally_downregulates",
            "object": {"name": "PDL1", "type": "gene"},
            "context": "adult recurrent glioblastoma tumor",
            "model_system": "mouse xenograft",
            "species": "mouse",
            "population": "xenograft-bearing mice",
            "tissue": "brain tumor",
            "dose": "low-dose inhibitor",
            "timepoint": "72 hours",
            "endpoint": "PDL1 protein",
            "experiment_type": ["western blot"],
            "study_design": "xenograft intervention",
            "evidence": ["DOI:10.1000/example"],
            "confidence": 0.80,
            "claim_text": "STAT3 downregulates PDL1 after chronic treatment.",
            "source": "manual-curation",
            "timestamp": "2026-01-03T00:00:00Z",
        },
    ]


def _load_kg_server():
    path = ROOT / "packs" / "bio-kg" / "knowledge_graph_server.py"
    spec = importlib.util.spec_from_file_location("test_hypothesis_kg_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_conflict_generation_keeps_observations_separate_from_generated_content():
    conflicts = engine.conflicts_from_triples(_edges(), min_context_similarity=0.8)

    # causal_kg emits A-vs-B and B-vs-A; the hypothesis layer must not double
    # count one scientific disagreement.
    assert len(conflicts) == 1
    result = engine.generate_hypotheses(
        conflicts,
        research_context={"disease": "glioblastoma", "decision": "mechanism adjudication"},
        experiment_constraints={"available_models": ["organoid", "xenograft"], "timeline_weeks": 12},
    )

    assert result["schema"] == "bio-kg/contradiction-hypotheses/1"
    assert result["status"] == "hypotheses_generated"
    assert result["summary"]["unique_eligible_conflicts"] == 1
    report = result["contradictions"][0]

    observed = report["observed_conflict"]
    assert observed["record_type"] == "observed_conflict"
    assert observed["validation_status"] == "recorded_not_adjudicated"
    assert observed["positive_relation"] == "causally_upregulates"
    assert observed["negative_relation"] == "causally_downregulates"
    assert "No explanatory mechanism" in observed["important_distinction"]

    hypotheses = report["generated_hypotheses"]
    assert len(hypotheses) == 5
    assert all(item["record_type"] == "generated_hypothesis" for item in hypotheses)
    assert all(item["validation_status"] == "not_tested" for item in hypotheses)
    assert all(item["epistemic_warning"].startswith("Generated explanation only") for item in hypotheses)
    assert all(prediction["record_type"] == "prediction" for item in hypotheses for prediction in item["predictions"])

    categories = {item["category"] for item in hypotheses}
    assert categories == {
        "context_effect_modification",
        "dose_or_time_dependent_sign_switch",
        "method_or_endpoint_artifact",
        "adaptive_feedback_or_intermediate",
        "one_claim_biased_or_noncausal",
    }
    assert all(item["priority"]["interpretation"].startswith("Heuristic") for item in hypotheses)


def test_metadata_differences_drive_falsifiable_hypotheses_and_data_needs():
    result = engine.generate_hypotheses(engine.conflicts_from_triples(_edges()))
    report = result["contradictions"][0]
    comparison = {
        row["dimension"]: row["status"]
        for row in report["observed_conflict"]["study_dimension_comparison"]
    }

    for dimension in ("model_system", "species", "population", "dose", "timepoint", "endpoint", "experiment_type", "study_design"):
        assert comparison[dimension] == "observed_difference"

    by_category = {item["category"]: item for item in report["generated_hypotheses"]}
    assert by_category["context_effect_modification"]["priority"]["score"] >= 0.75
    assert by_category["dose_or_time_dependent_sign_switch"]["priority"]["score"] >= 0.75
    assert by_category["method_or_endpoint_artifact"]["priority"]["score"] >= 0.75
    for item in by_category.values():
        assert item["falsification_criteria"]
        assert item["data_needed"]

    needs = report["key_data_needs"]
    quantitative = next(item for item in needs if "signed effect estimate" in item["data_needed"])
    assert quantitative["priority"] == "critical"
    assert "do not substitute KG confidence" in quantitative["collection_action"]


def test_provenance_uncertainty_and_experiment_handoff_are_auditable():
    constraints = {"budget_usd": 25000, "timeline_weeks": 10}
    first = engine.generate_hypotheses(
        engine.conflicts_from_triples(_edges()),
        experiment_constraints=constraints,
    )
    second = engine.generate_hypotheses(
        engine.conflicts_from_triples(_edges()),
        experiment_constraints=constraints,
    )
    report = first["contradictions"][0]

    # IDs and fingerprints are content-addressed, so a plan can be traced and
    # compared without relying on generation time.
    assert first["engine"]["input_fingerprint"] == second["engine"]["input_fingerprint"]
    assert report["conflict_id"] == second["contradictions"][0]["conflict_id"]
    provenance = report["evidence_provenance"]
    assert provenance["evidence_ids"] == ["DOI:10.1000/example", "PMID:11111111"]
    assert {item["edge_id"] for item in provenance["source_edges"]} == {"edge_positive", "edge_negative"}
    assert provenance["input_fingerprint"].startswith("sha256:")
    assert "generated text is never added as evidence" in provenance["provenance_rule"]

    uncertainty = report["uncertainty"]
    assert 0.0 <= uncertainty["causal_direction_uncertainty"] <= 1.0
    assert uncertainty["resolution_status"] == "unresolved"
    assert any("not statistical uncertainty" in item for item in uncertainty["limitations"])

    experiments = report["discriminating_experiments"]
    assert len(experiments) == 3
    for experiment in experiments:
        assert experiment["record_type"] == "discriminating_experiment"
        assert experiment["status"] == "proposed_not_executed"
        assert len(experiment["predicted_outcomes"]) >= 3
        assert all(item["record_type"] == "prediction" for item in experiment["predicted_outcomes"])
        handoff = experiment["bio_experiment_handoff"]
        assert handoff["target_tool"] == "bio-experiment.agentic_experiment_plan"
        assert handoff["arguments"]["budget_usd"] == constraints["budget_usd"]
        assert handoff["arguments"]["timeline_weeks"] == constraints["timeline_weeks"]
        assert handoff["arguments"]["constraints"] == {}
        assert handoff["argument_mapping"]["hoisted_constraint_keys"] == ["budget_usd", "timeline_weeks"]
        assert handoff["arguments"]["hypothesis"]
        assert "Planning scaffold only" in handoff["handoff_warning"]


def test_missing_metadata_is_reported_instead_of_fabricated():
    minimal = [
        {
            "id": "minimal_positive",
            "subject": "MYC",
            "relation": "causally_upregulates",
            "object": "CCND1",
            "context": "hepatocellular carcinoma",
            "confidence": 0.6,
        },
        {
            "id": "minimal_negative",
            "subject": "MYC",
            "relation": "causally_downregulates",
            "object": "CCND1",
            "context": "hepatocellular carcinoma",
            "confidence": 0.6,
        },
    ]
    report = engine.generate_hypotheses(engine.conflicts_from_triples(minimal))["contradictions"][0]
    missing = next(item for item in report["key_data_needs"] if item["status"] == "missing_or_incomplete")

    assert {"species", "population", "dose", "timepoint", "experiment_type"} <= set(missing["data_needed"])
    assert report["evidence_provenance"]["evidence_ids"] == []
    assert all(item["validation_status"] == "not_tested" for item in report["generated_hypotheses"])
    assert "not a calibrated posterior" in report["uncertainty"]["interpretation"]


def test_kg_server_tool_accepts_triples_or_conflict_scan_output():
    kg = _load_kg_server()
    assert "kg_generate_hypotheses" in kg.server.tools
    schema = kg.server.tools["kg_generate_hypotheses"]["inputSchema"]
    assert {"conflicts", "triples", "graph_path", "research_context", "experiment_constraints"} <= set(schema["properties"])

    scanned = kg.kg_generate_hypotheses(
        triples=_edges(),
        focus_entity="STAT3",
        context="glioblastoma",
        min_context_similarity=0.8,
    )
    assert scanned["input"]["mode"] == "kg_or_triples_scan"
    assert scanned["input"]["scanned_graph_summary"]["edges"] == 2
    assert scanned["summary"]["unique_eligible_conflicts"] == 1
    assert scanned["input"]["persistence"].startswith("none")

    scan_output = kg.kg_conflict_scan(triples=_edges(), min_context_similarity=0.8)
    supplied = kg.kg_generate_hypotheses(conflicts=scan_output["conflicts"])
    assert supplied["input"]["mode"] == "supplied_conflict_records"
    assert supplied["summary"]["unique_eligible_conflicts"] == 1


def test_optional_study_metadata_survives_kg_normalization_and_no_conflict_is_safe():
    normalized = causal_kg.normalize_triple(_edges()[0])
    assert normalized is not None
    assert normalized["species"] == "human"
    assert normalized["population"] == "adult recurrent disease"
    assert normalized["dose"] == "80% CRISPRi knockdown"
    assert normalized["timepoint"] == "6 hours"
    assert normalized["endpoint"] == "PDL1 mRNA"

    alias_edge = dict(_edges()[0])
    alias_edge.pop("model_system")
    alias_edge.pop("experiment_type")
    alias_edge.pop("timepoint")
    alias_edge.update({"model": "primary culture", "method": "flow cytometry", "time": "24 hours"})
    normalized_alias = causal_kg.normalize_triple(alias_edge)
    assert normalized_alias is not None
    assert normalized_alias["model_system"] == "primary culture"
    assert normalized_alias["experiment_type"] == ["flow cytometry"]
    assert normalized_alias["timepoint"] == "24 hours"

    result = engine.generate_hypotheses([])
    assert result["status"] == "no_eligible_contradictions"
    assert result["contradictions"] == []
    assert result["summary"]["generated_hypotheses"] == 0
    assert result["next_step"].startswith("Add or supply two curated")


def test_synthetic_ingestion_time_is_not_evidence_identity():
    edges = _edges()
    for edge in edges:
        edge.pop("timestamp", None)
    conflicts = engine.conflicts_from_triples(edges)
    changed_clock = copy.deepcopy(conflicts)
    for record in changed_clock:
        for side in ("positive_edge", "negative_edge"):
            record[side]["timestamp"] = "2099-12-31T23:59:59Z"
            record[side]["timestamp_origin"] = "generated_at_normalization"
    first = engine.generate_hypotheses(conflicts)
    second = engine.generate_hypotheses(changed_clock)
    assert first["engine"]["input_fingerprint"] == second["engine"]["input_fingerprint"]
    assert first["contradictions"][0]["evidence_provenance"]["input_fingerprint"] == second["contradictions"][0]["evidence_provenance"]["input_fingerprint"]


def test_missing_context_is_unknown_and_truncation_is_explicit():
    pairs = []
    for index in range(3):
        pairs.append(
            {
                "positive_edge": {
                    "id": f"p{index}",
                    "subject": f"GENE{index}",
                    "relation": "causally_upregulates",
                    "object": "OUTCOME",
                },
                "negative_edge": {
                    "id": f"n{index}",
                    "subject": f"GENE{index}",
                    "relation": "causally_downregulates",
                    "object": "OUTCOME",
                },
            }
        )
    result = engine.generate_hypotheses(pairs, max_conflicts=1)
    observed = result["contradictions"][0]["observed_conflict"]
    assert observed["context_similarity"] is None
    assert observed["context_overlap_status"] == "unknown_missing_context"
    assert result["summary"]["unique_eligible_conflicts"] == 3
    assert result["summary"]["reports_returned"] == 1
    assert result["summary"]["truncated"] is True
    assert result["summary"]["remaining_eligible_conflicts"] == 2
