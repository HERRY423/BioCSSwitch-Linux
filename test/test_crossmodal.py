from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packs"))

from _lib.crossmodal import (  # noqa: E402
    CONTEXT_SCHEMA,
    MODALITIES,
    cross_validate,
    integrate_observations,
    new_evidence_context,
    orchestrate,
    plan_unmet_need,
    rank_targets,
    reduce_tool_result,
)


NEED = {
    "disease": "glioblastoma",
    "unmet_need": "durable control after temozolomide resistance",
    "population": "adults with recurrent disease",
    "tissue": "brain",
    "organism": "human",
}


def _observation(
    target: str,
    modality: str,
    claim_type: str,
    effect: str = "supports",
    strength: float = 0.8,
    quality: float = 0.8,
    source: str = "fixture",
):
    return {
        "target": target,
        "disease": NEED["disease"],
        "modality": modality,
        "source_pack": f"bio-{modality.replace('_', '')}",
        "source_tool": source,
        "claim_type": claim_type,
        "effect": effect,
        "strength": strength,
        "quality": quality,
        "source_ids": [f"{source}:{target}:{effect}"],
    }


def test_plan_is_dependency_aware_and_covers_all_requested_packs():
    plan = plan_unmet_need(NEED)
    assert plan["required_packs"] == [
        "bio-lit",
        "bio-gene",
        "bio-drug",
        "bio-trials",
        "bio-singlecell",
        "bio-spatial",
    ]
    assert plan["modalities"] == list(MODALITIES)

    steps = {step["step_id"]: step for step in plan["steps"]}
    assert steps["disease_target_seeds"]["arguments"]["efo_id"].startswith("$outputs.")
    assert steps["target_literature"]["foreach_target"] is True
    assert steps["single_cell_validation_recipe"]["evidence_role"] == "validation_recipe"
    assert steps["spatial_target_validation_recipe"]["evidence_role"] == "validation_recipe"
    assert steps["cross_validate_and_rank"]["kind"] == "internal"
    assert plan["execution_contract"]["recipes_are_evidence"] is False
    assert plan["execution_contract"]["missing_evidence_semantics"] == "unknown_not_negative"

    for step in steps.values():
        for dependency in step["depends_on"]:
            assert dependency in steps
            assert steps[dependency]["stage"] <= step["stage"]


def test_context_is_serializable_idempotent_and_keeps_missing_as_unknown():
    context = new_evidence_context({**NEED, "seed_targets": ["EGFR"]})
    assert context["schema"] == CONTEXT_SCHEMA
    obs = _observation("EGFR", "gene", "disease_association")
    once = integrate_observations(context, [obs])
    twice = integrate_observations(once, [obs])
    assert len(once["records"]) == 1
    assert len(twice["records"]) == 1

    validation = cross_validate(twice)
    egfr = validation["targets"][0]
    assert egfr["target"] == "EGFR"
    assert egfr["status"] == "partial"
    assert "trials" in egfr["modalities_missing"]
    assert validation["interpretation"]["missing_evidence"] == "unknown_not_contradictory"
    assert validation["conflict_count"] == 0


def test_cross_validation_requires_independent_modalities_and_flags_explicit_conflict():
    context = new_evidence_context({**NEED, "seed_targets": ["STAT3"]})
    context = integrate_observations(
        context,
        [
            _observation("STAT3", "gene", "disease_association", source="ot"),
            _observation("STAT3", "literature", "disease_association", source="pmid-1"),
            _observation("STAT3", "single_cell", "target_expression", source="sc-study"),
            _observation(
                "STAT3",
                "spatial",
                "target_expression",
                effect="contradicts",
                strength=0.7,
                source="spatial-study",
            ),
        ],
    )
    result = cross_validate(context)
    stat3 = result["targets"][0]
    by_claim = {claim["claim_type"]: claim for claim in stat3["claim_results"]}
    association = by_claim["target_disease_association"]
    assert association["status"] == "cross_modally_corroborated"
    assert association["independent_source_count"] == 2
    assert by_claim["target_expression"]["status"] == "contested"
    assert stat3["status"] == "contested"
    assert result["conflict_count"] == 1


def test_ranking_rewards_multimodal_support_and_does_not_infer_novelty_from_missing_trials():
    context = new_evidence_context({**NEED, "seed_targets": ["A", "B", "C"]})
    observations = [
        _observation("A", "gene", "disease_association",  strength=0.9),
        _observation("A", "literature", "disease_association", strength=0.9),
        _observation("A", "drug", "druggability", strength=0.8),
        _observation("A", "single_cell", "target_expression", strength=0.8),
        _observation("A", "spatial", "target_expression", strength=0.8),
        _observation("A", "trials", "clinical_activity", effect="neutral", strength=0.0),
        _observation("B", "gene", "disease_association", strength=0.9),
        _observation("B", "drug", "druggability", strength=0.8),
        _observation("B", "trials", "clinical_activity", strength=0.95),
        _observation("C", "gene", "disease_association", strength=0.9),
        _observation("C", "literature", "disease_association", strength=0.9),
        _observation("C", "drug", "druggability", strength=0.8),
        _observation("C", "single_cell", "target_expression", strength=0.8),
        _observation("C", "spatial", "target_expression", strength=0.8),
    ]
    context = integrate_observations(context, observations)
    result = rank_targets(context)
    rows = {row["target"]: row for row in result["targets"]}
    assert rows["A"]["score"] > rows["B"]["score"]
    assert rows["A"]["dimensions"]["clinical_novelty"] == 1.0
    assert rows["A"]["clinical_novelty_basis"] == "observed_trial_search"
    assert rows["C"]["dimensions"]["clinical_novelty"] == 0.5
    assert rows["C"]["clinical_novelty_basis"] == "unknown_no_trial_evidence"
    assert "trials" in rows["C"]["modalities_missing"]


def test_recipe_results_are_provenance_not_target_support():
    context = new_evidence_context({**NEED, "seed_targets": ["EGFR"]})
    step = {
        "step_id": "spatial_target_validation_recipe",
        "pack": "bio-spatial",
        "tool": "spatial_rare_cell_recipe",
        "evidence_role": "validation_recipe",
    }
    context = reduce_tool_result(
        context,
        step,
        {"recipe_hash": "recipe-1", "params": {"marker_genes": ["EGFR"]}},
    )
    assert context["coverage"]["recipe_records_excluded"] == 1
    assert "spatial" in context["coverage"]["modalities_missing"]
    ranked = rank_targets(context)["targets"][0]
    assert ranked["modality_scores"]["spatial"] == 0.0
    assert ranked["score"] >= 0.0


def test_open_targets_adapter_adds_gene_evidence_even_though_tool_lives_in_drug_pack():
    context = new_evidence_context(NEED)
    step = {
        "step_id": "disease_target_seeds",
        "pack": "bio-drug",
        "tool": "ot_disease_associated_targets",
    }
    context = reduce_tool_result(
        context,
        step,
        {
            "rows": [
                {
                    "score": 0.91,
                    "target": {"id": "ENSG00000146648", "approvedSymbol": "EGFR"},
                }
            ]
        },
    )
    assert context["candidates"][0]["symbol"] == "EGFR"
    assert context["records"][0]["modality"] == "gene"
    assert context["records"][0]["claim_type"] == "disease_association"


def test_orchestrate_executes_dynamic_fanout_and_returns_partial_failure_gaps():
    calls = []

    def executor(server, tool, arguments):
        calls.append((server, tool, arguments))
        if tool == "ot_search":
            return {"hits": [{"id": "EFO_0000519", "entity": "disease", "name": "glioblastoma"}]}
        if tool == "ot_disease_associated_targets":
            assert arguments["efo_id"] == "EFO_0000519"
            return {
                "rows": [
                    {
                        "score": 0.9,
                        "target": {"id": "ENSG00000146648", "approvedSymbol": "EGFR"},
                    }
                ]
            }
        if tool == "pubmed_search":
            if "EGFR" in arguments["query"]:
                return {"count": 2, "results": [{"pmid": "1"}, {"pmid": "2"}]}
            return {"count": 4, "results": [{"pmid": "10"}]}
        if tool == "europepmc_search":
            return {"hit_count": 1, "results": [{"doi": "10.1/preprint"}]}
        if tool == "ctgov_search":
            if arguments.get("term") == "EGFR":
                return {"total": 0, "results": []}
            return {"total": 3, "results": [{"nct_id": "NCT1"}]}
        if tool == "geo_search":
            return {"count": 1, "ids": ["200"]}
        if tool == "gene_search":
            assert "EGFR" in arguments["query"]
            return {"count": 1, "ids": ["1956"]}
        if tool == "uniprot_search":
            return {"results": [{"accession": "P00533"}]}
        if tool == "chembl_target_search":
            return {"results": [{"target_chembl_id": "CHEMBL203"}]}
        if tool == "sc_celltype_recipe":
            return {"recipe_hash": "sc-1", "params": arguments}
        if tool == "spatial_deconvolution_recipe":
            # Demonstrate that one modality can fail without erasing the run.
            raise RuntimeError("spatial fixture unavailable")
        if tool == "spatial_rare_cell_recipe":
            assert arguments["marker_genes"] == ["EGFR"]
            return {"recipe_hash": "sp-1", "params": arguments}
        raise AssertionError(f"unexpected tool: {tool}")

    result = orchestrate(NEED, executor, max_targets=5)
    servers = {server for server, _, _ in calls}
    assert any(server.startswith("bio-lit") for server in servers)
    assert any(server.startswith("bio-gene") for server in servers)
    assert any(server.startswith("bio-drug") for server in servers)
    assert any(server.startswith("bio-trials") for server in servers)
    assert "bio-singlecell" in servers
    assert "bio-spatial" in servers
    assert result["ranking"]["targets"][0]["target"] == "EGFR"
    assert result["errors"][0]["tool"] == "spatial_deconvolution_recipe"
    assert "single_cell" in result["context"]["coverage"]["modalities_missing"]
    assert "spatial" in result["context"]["coverage"]["modalities_missing"]


def test_same_publication_seen_through_two_packs_is_one_independent_source():
    context = new_evidence_context({**NEED, "seed_targets": ["EGFR"]})
    context = integrate_observations(
        context,
        [
            {**_observation("EGFR", "gene", "disease_association"), "source_ids": ["PMID:12345678"]},
            {**_observation("EGFR", "literature", "disease_literature_support"), "source_ids": ["12345678"]},
        ],
    )
    assert len(context["records"]) == 1
    claim = cross_validate(context)["targets"][0]["claim_results"][0]
    assert claim["claim_type"] == "target_disease_association"
    assert claim["independent_source_count"] == 1
    assert claim["status"] == "single_modality_support"


def test_claim_aliases_corroborate_but_error_results_never_mean_zero_hits():
    context = new_evidence_context({**NEED, "seed_targets": ["EGFR"]})
    context = integrate_observations(
        context,
        [
            _observation("EGFR", "gene", "disease_association", source="ENSG00000146648"),
            _observation("EGFR", "literature", "disease_literature_support", source="PMID:22222222"),
        ],
    )
    claim = cross_validate(context)["targets"][0]["claim_results"][0]
    assert claim["claim_type"] == "target_disease_association"
    assert claim["status"] == "cross_modally_corroborated"
    assert set(claim["source_claim_types"]) == {"disease_association", "disease_literature_support"}

    step = {"step_id": "target_trials", "pack": "bio-trials", "tool": "ctgov_search"}
    with pytest.raises(RuntimeError, match="timeout"):
        reduce_tool_result(context, step, {"error": "timeout"}, target="EGFR")


def test_plan_context_and_step_receipts_block_cross_disease_or_tampered_reduction():
    plan = plan_unmet_need(NEED)
    context = new_evidence_context(NEED, plan_id=plan["plan_id"])
    step = next(item for item in plan["steps"] if item["tool"] == "pubmed_search" and item["foreach_target"])
    reduced = reduce_tool_result(context, step, {"count": 1, "results": [{"pmid": "33333333"}]}, "EGFR")
    assert reduced["plan_id"] == plan["plan_id"]

    tampered = dict(step)
    tampered["tool"] = "ctgov_search"
    with pytest.raises(ValueError, match="step_receipt"):
        reduce_tool_result(context, tampered, {"total": 0}, "EGFR")

    other = new_evidence_context({"disease": "melanoma", "unmet_need": "resistance"})
    with pytest.raises(ValueError, match="unmet need"):
        orchestrate(NEED, lambda *_args: {}, initial_context=other)

    with pytest.raises(ValueError, match="at least 1"):
        orchestrate(NEED, lambda *_args: {}, max_targets=0)
