#!/usr/bin/env python3
"""Biomedical machine-learning recipe MCP (bio-ml).

This pack turns the ML report's frontier areas into BioCSSwitch-native recipe
objects: ambitious enough for multimodal foundation models, virtual cells, AI
drug discovery and self-driving labs, but strict about validation, leakage,
calibration, privacy and provenance.

It follows the project rule: MCP subprocesses do not train large models. Tools
emit deterministic hashes, non-runnable skeletons and validation contracts that
the user runs and fills locally.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import provenance as prov  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-ml", "0.1.0")

_CLAIM_SCOPES = [
    "exploratory",
    "discovery",
    "translational",
    "clinical_decision_support",
    "diagnostic_device",
]

_MODALITIES = [
    "omics",
    "single_cell",
    "spatial",
    "histology",
    "radiology",
    "ehr",
    "wearables",
    "structure",
    "chemistry",
    "assay",
]

_REPORT_MAP: Dict[str, Dict[str, Any]] = {
    "medical_imaging_and_diagnostics": {
        "frontier": "Vision and multimodal models for radiology, pathology and point-of-care diagnostics.",
        "bio_csswitch_angle": "Use validation gates, leakage-proof splits, calibration and workflow-readiness checks before clinical language.",
        "failure_modes": ["single-site overfit", "scanner/vendor shift", "probability miscalibration", "weak external validation"],
    },
    "single_cell_spatial_and_virtual_cells": {
        "frontier": "Single-cell/spatial foundation models and perturbation predictors that move toward virtual-cell behavior.",
        "bio_csswitch_angle": "Route to bio-singlecell, bio-scfm and bio-spatial; require domain baselines, perturbation controls and provenance.",
        "failure_modes": ["zero-shot overclaiming", "batch leakage", "cell-state label circularity", "missing perturbation validation"],
    },
    "drug_discovery_and_generative_biology": {
        "frontier": "ML-supported target discovery, structure-aware screening, molecule generation and protein/binder design.",
        "bio_csswitch_angle": "Tie bio-drug, bio-gene, structure recipes, ADMET and counter-experiment gates into staged go/no-go plans.",
        "failure_modes": ["docking-only claims", "activity without selectivity", "no ADMET triage", "no orthogonal assay"],
    },
    "ehr_foundation_models_and_digital_twins": {
        "frontier": "Longitudinal clinical models, guideline-grounded decision support and patient-specific simulation.",
        "bio_csswitch_angle": "Require PHI-sensitive mode, FHIR/OMOP mapping, calibration, subgroup audits and prospective/silent evaluation.",
        "failure_modes": ["PHI leakage", "temporal drift", "shortcut learning", "unclear clinical utility"],
    },
    "federated_and_privacy_preserving_ml": {
        "frontier": "Multi-institutional learning without centralizing raw patient data.",
        "bio_csswitch_angle": "Generate federated protocol skeletons with site contracts, secure aggregation, DP budget and audit logs.",
        "failure_modes": ["site heterogeneity", "incomplete governance", "untracked updates", "privacy budget not reported"],
    },
    "self_driving_labs_and_ai_coscientists": {
        "frontier": "Closed-loop experiment proposal, execution, analysis and next-experiment selection.",
        "bio_csswitch_angle": "Keep human approval, assay QC, stopping rules and evidence ledger in the loop.",
        "failure_modes": ["automation without assay validation", "unbounded search", "unsafe protocol generation", "weak negative controls"],
    },
}


def _hash(tool: str, params: Dict[str, Any]) -> str:
    return prov.content_hash({"tool": tool, "params": params})


def _scope_requirements(scope: str, n_sites: int = 1) -> List[str]:
    req = {
        "exploratory": ["locked_provenance", "leakage_audit"],
        "discovery": ["locked_provenance", "leakage_audit", "baseline_model"],
        "translational": [
            "locked_provenance",
            "leakage_audit",
            "baseline_model",
            "external_validation",
            "calibration",
            "subgroup_bias_audit",
        ],
        "clinical_decision_support": [
            "locked_provenance",
            "leakage_audit",
            "baseline_model",
            "external_validation",
            "calibration",
            "subgroup_bias_audit",
            "interpretability_or_rationale",
            "prospective_or_silent_evaluation",
            "drift_monitoring",
        ],
        "diagnostic_device": [
            "locked_provenance",
            "leakage_audit",
            "baseline_model",
            "multi_site_external_validation",
            "calibration",
            "subgroup_bias_audit",
            "interpretability_or_rationale",
            "prospective_or_silent_evaluation",
            "drift_monitoring",
            "locked_test_set_and_prespecified_endpoint",
        ],
    }.get(scope, req_default())
    if scope in {"translational", "clinical_decision_support", "diagnostic_device"} and n_sites < 2:
        req = req + ["at_least_two_sites_or_documented_external_cohort"]
    return req


def req_default() -> List[str]:
    return ["locked_provenance", "leakage_audit"]


def _allowed_language(verdict: str, scope: str) -> str:
    if verdict == "ready_for_claim_scope":
        return f"May use {scope.replace('_', ' ')} wording if all filled artifacts are attached."
    if scope in {"clinical_decision_support", "diagnostic_device"}:
        return "Use research-only or hypothesis-generating language; do not imply clinical use."
    if scope == "translational":
        return "Use translational-pilot language only after the missing validation items are completed."
    return "Use exploratory language and state missing validation explicitly."


def _split_rules(modalities: List[str], claim_scope: str) -> List[str]:
    rules = [
        "Split by patient/donor/site before any patch, cell, spot or visit expansion.",
        "Freeze train/validation/test manifests and record split_hash before model selection.",
        "Keep preprocessing fit steps inside training folds to prevent normalization leakage.",
    ]
    if "histology" in modalities or "radiology" in modalities:
        rules.append("Block all tiles/images from the same slide/study/patient from crossing splits.")
    if "single_cell" in modalities or "spatial" in modalities:
        rules.append("Aggregate performance at donor/sample level; cells/spots are not independent biological replicates.")
    if "ehr" in modalities or "wearables" in modalities:
        rules.append("Use temporal splits or deployment-time simulation for longitudinal prediction.")
    if claim_scope in {"translational", "clinical_decision_support", "diagnostic_device"}:
        rules.append("Hold out an external site/cohort that is never touched during architecture or threshold selection.")
    return rules


def _metrics_for_task(task_type: str, outcome_type: str) -> Dict[str, Any]:
    if task_type in {"classification", "diagnosis", "risk_prediction"}:
        primary = "AUROC plus AUPRC if classes are imbalanced"
        secondary = ["calibration slope/intercept", "Brier score", "decision-curve net benefit", "subgroup performance"]
    elif task_type in {"survival", "time_to_event"}:
        primary = "time-dependent C-index or integrated AUC"
        secondary = ["calibration at clinically relevant horizons", "decision curve", "subgroup performance"]
    elif task_type in {"regression", "biomarker_prediction"}:
        primary = "MAE/RMSE with bootstrap CI"
        secondary = ["calibration", "rank correlation", "error by site/subgroup"]
    elif task_type in {"perturbation_prediction", "virtual_cell"}:
        primary = "held-out perturbation correlation plus direction-of-effect accuracy"
        secondary = ["top-k DEG recovery", "AUPRC for responder genes", "OOD cell-state performance"]
    else:
        primary = f"task-specific primary metric for {outcome_type}"
        secondary = ["bootstrap CI", "calibration if probabilistic", "subgroup/site performance"]
    return {"primary": primary, "secondary": secondary}


def _skeleton_header(title: str) -> str:
    return f'''# {"=" * 68}
# SKELETON - NOT RUNNABLE AS-IS
# {title}
# Fill dataset-specific loaders, pin package/model versions, freeze split
# manifests, and attach provenance before removing this guard.
# {"=" * 68}
raise SystemExit("SKELETON: fill TODOs, pin versions, freeze splits, then remove this guard")
'''


@server.tool(
    "biomedical_ml_capability_map",
    "Return a BioCSSwitch-oriented map of biomedical ML frontiers, failure modes and pack/tool handoffs. "
    "Use first when the user asks for a machine-learning section, disruptive biomedical AI strategy or ML roadmap.",
    {
        "type": "object",
        "properties": {
            "focus": {"type": "string"},
        },
    },
)
def biomedical_ml_capability_map(focus: Optional[str] = None):
    focus_key = (focus or "").strip().lower().replace("-", "_").replace(" ", "_")
    domains = _REPORT_MAP
    if focus_key:
        domains = {k: v for k, v in _REPORT_MAP.items() if focus_key in k or focus_key in " ".join(v.get("failure_modes", [])).lower()}
    return {
        "source_context": {
            "local_report": "ML_in_Medicine_and_Biology_Report.md",
            "prepared": "July 2026",
            "distilled_themes": [
                "multimodal medical foundation models",
                "single-cell/spatial foundation models and virtual cells",
                "structure-aware and generative drug discovery",
                "privacy-preserving multi-site learning",
                "external validation, calibration, interpretability and drift monitoring",
                "self-driving laboratories with human-in-the-loop controls",
            ],
        },
        "domains": domains,
        "bio_csswitch_design_principles": [
            "Generate recipes, skeletons and provenance rather than silently running heavy ML inside MCP.",
            "Make validation gates first-class tools; a breakthrough claim must pass a claim-scope gate.",
            "Treat foundation models as representations requiring baselines, fine-tuning plans and external validation.",
            "Keep PHI, site governance and reproducibility visible before training starts.",
        ],
        "recommended_tools": [
            "ml_study_design_recipe",
            "multimodal_foundation_model_plan",
            "virtual_cell_perturbation_plan",
            "ai_drug_discovery_ml_plan",
            "federated_learning_recipe",
            "biomedical_ml_validation_gate",
            "self_driving_lab_plan",
        ],
    }


@server.tool(
    "ml_study_design_recipe",
    "Generate a rigorous biomedical ML study design recipe with leakage-proof splits, baselines, metrics, "
    "calibration, bias audit, provenance and claim-scope validation requirements.",
    {
        "type": "object",
        "properties": {
            "task_type": {"type": "string", "default": "classification"},
            "data_modalities": {"type": "array", "items": {"type": "string", "enum": _MODALITIES}},
            "claim_scope": {"type": "string", "enum": _CLAIM_SCOPES, "default": "discovery"},
            "outcome_type": {"type": "string", "default": "biomedical_endpoint"},
            "n_sites": {"type": "integer", "default": 1},
            "n_subjects": {"type": "integer", "default": 0},
            "sensitive_data": {"type": "boolean", "default": False},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def ml_study_design_recipe(
    task_type: str = "classification",
    data_modalities: Optional[List[str]] = None,
    claim_scope: str = "discovery",
    outcome_type: str = "biomedical_endpoint",
    n_sites: int = 1,
    n_subjects: int = 0,
    sensitive_data: bool = False,
    seed: int = 0,
):
    modalities = data_modalities or ["omics"]
    params = {
        "task_type": task_type,
        "data_modalities": modalities,
        "claim_scope": claim_scope,
        "outcome_type": outcome_type,
        "n_sites": n_sites,
        "n_subjects": n_subjects,
        "sensitive_data": sensitive_data,
        "seed": seed,
    }
    recipe_hash = _hash("ml_study_design_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "split_strategy": _split_rules(modalities, claim_scope),
        "baseline_contract": [
            "Compare against a simple interpretable baseline before claiming deep-learning lift.",
            "For tabular/EHR tasks: logistic/Cox/gradient boosting baseline with identical split.",
            "For imaging/pathology: morphology/radiomics or ImageNet/self-supervised baseline.",
            "For single-cell/spatial: scVI/marker/deconvolution baselines via bio-scfm or bio-spatial.",
        ],
        "metrics": _metrics_for_task(task_type, outcome_type),
        "validation_requirements": _scope_requirements(claim_scope, n_sites),
        "privacy_and_governance": [
            "Route PHI-like data through bio-privacy sensitive-mode before external providers.",
            "Record data-use permissions, cohort inclusion/exclusion and site identifiers in provenance.",
            "If raw data cannot centralize, use federated_learning_recipe instead of ad hoc file exchange.",
        ] if sensitive_data else [
            "Even non-PHI biomedical data needs license and consent boundary documentation.",
        ],
        "script": _render_study_design_script(task_type, modalities, claim_scope, outcome_type, seed),
        "provenance_skeleton": {
            "schema": "bio-ml/study-design-provenance/1",
            "recipe_hash": recipe_hash,
            "data": {"dataset_manifest_sha256": "<FILL>", "modalities": modalities, "n_sites": n_sites},
            "split": {"split_manifest_sha256": "<FILL>", "split_unit": "<FILL patient/donor/site>", "frozen_before_training": "<FILL true/false>"},
            "model": {"family": "<FILL>", "version": "<FILL>", "hyperparameter_plan_hash": "<FILL>"},
            "metrics": {"primary": "<FILL>", "bootstrap_ci": "<FILL>"},
            "audits": {"leakage_audit": "<FILL>", "calibration": "<FILL>", "subgroup_bias": "<FILL>"},
        },
        "warnings": [
            "Do not report cell/tile/visit-level random splits as patient-level generalization.",
            "Do not use clinical or diagnostic wording unless biomedical_ml_validation_gate passes that scope.",
        ],
    }


def _render_study_design_script(task_type: str, modalities: List[str], claim_scope: str, outcome_type: str, seed: int) -> str:
    return _skeleton_header(f"Biomedical ML study design for {task_type} / {outcome_type}") + f'''
import json
import numpy as np

np.random.seed({seed})
plan = {{
    "task_type": "{task_type}",
    "modalities": {modalities!r},
    "claim_scope": "{claim_scope}",
    "outcome_type": "{outcome_type}",
    "required_files": ["dataset_manifest.tsv", "split_manifest.tsv", "model_card.md"],
}}
# TODO: build dataset_manifest with patient_id/donor_id/site_id/timepoint/modality/source_hash.
# TODO: freeze split_manifest before model selection.
# TODO: run baselines and candidate models on the same locked split.
json.dump(plan, open("bio_ml_study_plan.json", "w"), indent=2)
'''


@server.tool(
    "multimodal_foundation_model_plan",
    "Generate a non-runnable plan for multimodal biomedical foundation models across omics, imaging, EHR, spatial, "
    "structure or chemistry data, with fusion strategy, baselines and validation contract.",
    {
        "type": "object",
        "properties": {
            "modalities": {"type": "array", "items": {"type": "string", "enum": _MODALITIES}},
            "task": {"type": "string", "default": "patient_or_sample_representation"},
            "fusion_strategy": {"type": "string", "enum": ["late_fusion", "cross_attention", "contrastive_alignment", "mixture_of_experts"], "default": "contrastive_alignment"},
            "claim_scope": {"type": "string", "enum": _CLAIM_SCOPES, "default": "discovery"},
            "n_sites": {"type": "integer", "default": 1},
            "sensitive_data": {"type": "boolean", "default": False},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def multimodal_foundation_model_plan(
    modalities: Optional[List[str]] = None,
    task: str = "patient_or_sample_representation",
    fusion_strategy: str = "contrastive_alignment",
    claim_scope: str = "discovery",
    n_sites: int = 1,
    sensitive_data: bool = False,
    seed: int = 0,
):
    mods = modalities or ["omics", "histology"]
    params = {
        "modalities": mods,
        "task": task,
        "fusion_strategy": fusion_strategy,
        "claim_scope": claim_scope,
        "n_sites": n_sites,
        "sensitive_data": sensitive_data,
        "seed": seed,
    }
    plan_hash = _hash("multimodal_foundation_model_plan", params)
    return {
        "plan_hash": plan_hash,
        "artifact_type": "skeleton",
        "runnable": False,
        "architecture_plan": {
            "encoders": _encoder_plan(mods),
            "fusion": fusion_strategy,
            "missing_modality_policy": "train with modality dropout; report performance by available-modality subset",
            "output": task,
        },
        "baseline_matrix": _baseline_matrix(mods),
        "validation_contract": _scope_requirements(claim_scope, n_sites) + [
            "modality ablation study",
            "site/platform-stratified metrics",
            "calibration if predictions affect decisions",
            "bootstrap CI for every headline metric",
        ],
        "script": _render_multimodal_script(mods, fusion_strategy, task, seed),
        "provenance_skeleton": {
            "schema": "bio-ml/multimodal-fm-provenance/1",
            "plan_hash": plan_hash,
            "modalities": {m: {"manifest_sha256": "<FILL>", "preprocess_hash": "<FILL>"} for m in mods},
            "model": {"encoder_versions": "<FILL>", "fusion_strategy": fusion_strategy, "checkpoint": "<FILL>"},
            "split": {"split_hash": "<FILL>", "split_unit": "<FILL patient/donor/site>"},
            "metrics": {"primary": "<FILL>", "ablations": "<FILL>", "external_validation": "<FILL>"},
        },
        "handoffs": _handoffs_for_modalities(mods, sensitive_data),
        "warnings": [
            "Do not claim multimodal superiority without an ablation and a single-modality baseline.",
            "Do not let one modality leak labels from another modality's preprocessing or annotations.",
        ],
    }


def _encoder_plan(modalities: List[str]) -> Dict[str, str]:
    choices = {
        "omics": "tabular/sequence encoder with pathway-aware baseline",
        "single_cell": "bio-scfm embedding plus scVI baseline",
        "spatial": "bio-spatial foundation-model or graph encoder plus marker/deconvolution baseline",
        "histology": "tile encoder with donor/slide split and stain-normalization audit",
        "radiology": "3D/2D imaging encoder with scanner/site covariates",
        "ehr": "longitudinal transformer or sparse temporal model with FHIR/OMOP mapping",
        "wearables": "time-series encoder with temporal drift checks",
        "structure": "protein/complex encoder with structure-confidence fields",
        "chemistry": "molecular graph/diffusion encoder with ADMET constraints",
        "assay": "tabular assay encoder with plate/batch correction",
    }
    return {m: choices.get(m, "domain-specific encoder with explicit baseline") for m in modalities}


def _baseline_matrix(modalities: List[str]) -> List[Dict[str, str]]:
    rows = []
    for m in modalities:
        baseline = {
            "omics": "elastic net / XGBoost with pathway features",
            "single_cell": "scVI or marker-score baseline",
            "spatial": "squidpy graph + marker/deconvolution baseline",
            "histology": "radiomics or frozen image encoder baseline",
            "radiology": "radiomics / clinical-score baseline",
            "ehr": "logistic/Cox/gradient boosting structured-data baseline",
            "structure": "docking/sequence-conservation baseline",
            "chemistry": "fingerprint + random forest / matched molecular pair baseline",
        }.get(m, "simple interpretable baseline")
        rows.append({"modality": m, "baseline": baseline})
    rows.append({"modality": "fusion", "baseline": "best single modality plus late-fusion baseline"})
    return rows


def _handoffs_for_modalities(modalities: List[str], sensitive_data: bool) -> List[str]:
    handoffs = []
    if "single_cell" in modalities:
        handoffs.append("bio-scfm.scfm_model_matrix and scfm_embed_quality")
    if "spatial" in modalities or "histology" in modalities:
        handoffs.append("bio-spatial.spatial_platform_matrix and spatial_translation_readiness_gate")
    if "chemistry" in modalities or "structure" in modalities:
        handoffs.append("bio-drug and downstream structure/docking recipes")
    if sensitive_data or "ehr" in modalities:
        handoffs.append("bio-privacy sensitive-mode and federated_learning_recipe")
    handoffs.append("bio-audit evidence_graph / uncertainty_ledger for biomedical claims")
    return handoffs


def _render_multimodal_script(modalities: List[str], fusion_strategy: str, task: str, seed: int) -> str:
    return _skeleton_header(f"Multimodal foundation-model plan: {task}") + f'''
import json
import numpy as np

np.random.seed({seed})
plan = {{
    "modalities": {modalities!r},
    "fusion_strategy": "{fusion_strategy}",
    "task": "{task}",
    "required_controls": ["best_single_modality", "late_fusion", "modality_ablation", "shuffled_label"],
}}
# TODO: load modality manifests and split before deriving tiles/cells/time windows.
# TODO: train/fit encoders only on train split; freeze threshold on validation split.
# TODO: evaluate on external site/cohort if claim_scope requires it.
json.dump(plan, open("multimodal_fm_plan.json", "w"), indent=2)
'''


@server.tool(
    "federated_learning_recipe",
    "Generate a privacy-preserving multi-site ML recipe with site contracts, interoperability layer, secure aggregation "
    "or differential privacy, validation and audit provenance.",
    {
        "type": "object",
        "properties": {
            "num_sites": {"type": "integer", "default": 2},
            "interoperability_standard": {"type": "string", "enum": ["FHIR", "OMOP", "AnnData", "custom"], "default": "FHIR"},
            "privacy_mode": {"type": "string", "enum": ["federated_averaging", "secure_aggregation", "differential_privacy", "split_learning"], "default": "secure_aggregation"},
            "task_type": {"type": "string", "default": "risk_prediction"},
            "claim_scope": {"type": "string", "enum": _CLAIM_SCOPES, "default": "translational"},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def federated_learning_recipe(
    num_sites: int = 2,
    interoperability_standard: str = "FHIR",
    privacy_mode: str = "secure_aggregation",
    task_type: str = "risk_prediction",
    claim_scope: str = "translational",
    seed: int = 0,
):
    params = {
        "num_sites": num_sites,
        "interoperability_standard": interoperability_standard,
        "privacy_mode": privacy_mode,
        "task_type": task_type,
        "claim_scope": claim_scope,
        "seed": seed,
    }
    recipe_hash = _hash("federated_learning_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "site_contract": [
            "Each site keeps raw data local and exports only model updates/metrics allowed by governance.",
            "Each site records cohort definition, coding map, local preprocessing hash and local split hash.",
            "A central coordinator aggregates signed updates and returns versioned global checkpoints.",
            "Report site-level metrics; do not hide failure at a minority site behind pooled performance.",
        ],
        "privacy_contract": _privacy_contract(privacy_mode),
        "interoperability_contract": [
            f"Map local variables into {interoperability_standard} before model feature extraction.",
            "Version concept sets, units, time windows and missingness rules.",
            "Run local schema validation before federated rounds start.",
        ],
        "validation_requirements": _scope_requirements(claim_scope, max(num_sites, 1)),
        "script": _render_federated_script(num_sites, interoperability_standard, privacy_mode, task_type, seed),
        "provenance_skeleton": {
            "schema": "bio-ml/federated-learning-provenance/1",
            "recipe_hash": recipe_hash,
            "sites": [{"site_id": f"site_{i+1}", "local_manifest_sha256": "<FILL>", "local_split_hash": "<FILL>"} for i in range(max(1, num_sites))],
            "privacy": {"mode": privacy_mode, "dp_epsilon": "<FILL if used>", "secure_aggregation": privacy_mode == "secure_aggregation"},
            "rounds": {"n_rounds": "<FILL>", "checkpoint_hashes": "<FILL>"},
            "metrics": {"site_level": "<FILL>", "pooled": "<FILL>", "external": "<FILL>"},
        },
        "warnings": [
            "Federated learning reduces raw-data movement; it does not remove the need for governance or privacy accounting.",
            "Do not compare against centralized training unless centralization is legally and ethically allowed.",
        ],
    }


def _privacy_contract(mode: str) -> List[str]:
    if mode == "differential_privacy":
        return ["Set epsilon/delta before training.", "Clip gradients locally.", "Report privacy budget spent per round."]
    if mode == "secure_aggregation":
        return ["Use secure aggregation so the coordinator cannot inspect individual site updates.", "Record update signatures and dropped-site events."]
    if mode == "split_learning":
        return ["Define cut layer and activation-sharing policy.", "Audit reconstruction risk from shared activations."]
    return ["Use federated averaging with signed model updates.", "Record update norms to detect unstable or poisoned rounds."]


def _render_federated_script(num_sites: int, standard: str, privacy_mode: str, task_type: str, seed: int) -> str:
    return _skeleton_header("Federated biomedical ML protocol") + f'''
import json
import numpy as np

np.random.seed({seed})
protocol = {{
    "num_sites": {num_sites},
    "interoperability_standard": "{standard}",
    "privacy_mode": "{privacy_mode}",
    "task_type": "{task_type}",
    "rounds": [],
}}
# TODO: implement with your approved federated runtime (Flower, NVFlare, TensorFlow Federated, or institutional stack).
# TODO: validate local schemas and freeze local split hashes before round 1.
# TODO: collect site-level metrics and privacy/audit artifacts after each round.
json.dump(protocol, open("federated_protocol_plan.json", "w"), indent=2)
'''


@server.tool(
    "virtual_cell_perturbation_plan",
    "Generate a virtual-cell or perturbation-response ML plan with scFM/spatial handoffs, perturbation splits, "
    "negative controls, baseline models and provenance fields.",
    {
        "type": "object",
        "properties": {
            "perturbation_type": {"type": "string", "enum": ["crispr", "compound", "cytokine", "disease_state", "genetic_variant"], "default": "crispr"},
            "model_family": {"type": "string", "enum": ["scfm_finetune", "graph_neural_network", "causal_latent_model", "multimodal_fm"], "default": "scfm_finetune"},
            "assay": {"type": "string", "default": "scRNA-seq"},
            "cell_context": {"type": "string", "default": "generic_cell_state"},
            "endpoint": {"type": "string", "default": "gene_expression_response"},
            "use_spatial_context": {"type": "boolean", "default": False},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def virtual_cell_perturbation_plan(
    perturbation_type: str = "crispr",
    model_family: str = "scfm_finetune",
    assay: str = "scRNA-seq",
    cell_context: str = "generic_cell_state",
    endpoint: str = "gene_expression_response",
    use_spatial_context: bool = False,
    seed: int = 0,
):
    params = {
        "perturbation_type": perturbation_type,
        "model_family": model_family,
        "assay": assay,
        "cell_context": cell_context,
        "endpoint": endpoint,
        "use_spatial_context": use_spatial_context,
        "seed": seed,
    }
    plan_hash = _hash("virtual_cell_perturbation_plan", params)
    return {
        "plan_hash": plan_hash,
        "artifact_type": "skeleton",
        "runnable": False,
        "experimental_design": [
            "Split by perturbation target and donor/sample; never let replicate cells define the held-out unit.",
            "Hold out at least one perturbation class for out-of-distribution evaluation.",
            "Include non-targeting, vehicle/sham and positive-control perturbations.",
            "Validate top predicted responders experimentally before mechanism language.",
        ],
        "model_plan": {
            "family": model_family,
            "input": assay,
            "context": cell_context,
            "endpoint": endpoint,
            "spatial_context": use_spatial_context,
        },
        "metrics": _metrics_for_task("perturbation_prediction", endpoint),
        "baselines": [
            "mean-response / nearest-neighbor baseline",
            "linear model with perturbation and cell-state covariates",
            "scVI/scGen-style latent baseline when available",
            "foundation-model fine-tune only if the above baselines are reported",
        ],
        "handoffs": [
            "bio-singlecell.sc_preprocess_recipe",
            "bio-scfm.scfm_finetune_plan or scfm_benchmark_plan",
        ] + (["bio-spatial.spatial_scfm_plan and spatial_communication_recipe"] if use_spatial_context else []),
        "script": _render_virtual_cell_script(perturbation_type, model_family, assay, endpoint, seed),
        "provenance_skeleton": {
            "schema": "bio-ml/virtual-cell-perturbation-provenance/1",
            "plan_hash": plan_hash,
            "perturbation_manifest_sha256": "<FILL>",
            "anndata_sha256": "<FILL>",
            "split": {"heldout_perturbations_hash": "<FILL>", "donor_split_hash": "<FILL>"},
            "model": {"family": model_family, "version": "<FILL>", "checkpoint": "<FILL>"},
            "metrics": {"heldout_response": "<FILL>", "top_gene_recovery": "<FILL>"},
        },
        "warnings": [
            "A virtual-cell prediction is a hypothesis until validated by held-out perturbation or wet-lab follow-up.",
            "Do not tune on the same perturbations used for headline OOD claims.",
        ],
    }


def _render_virtual_cell_script(perturbation_type: str, model_family: str, assay: str, endpoint: str, seed: int) -> str:
    return _skeleton_header("Virtual-cell / perturbation-response plan") + f'''
import json
import numpy as np

np.random.seed({seed})
plan = {{
    "perturbation_type": "{perturbation_type}",
    "model_family": "{model_family}",
    "assay": "{assay}",
    "endpoint": "{endpoint}",
    "controls": ["non_targeting", "vehicle_or_sham", "positive_control", "heldout_perturbation_class"],
}}
# TODO: build perturbation_manifest with target, dose, time, donor, batch and assay hashes.
# TODO: freeze held-out perturbations before model selection.
# TODO: evaluate responder genes and direction-of-effect on held-out perturbations.
json.dump(plan, open("virtual_cell_perturbation_plan.json", "w"), indent=2)
'''


@server.tool(
    "ai_drug_discovery_ml_plan",
    "Generate a staged AI drug discovery ML plan for target prioritization, repurposing, molecule generation, "
    "protein/binder design or clinical translation, with go/no-go gates and validation requirements.",
    {
        "type": "object",
        "properties": {
            "discovery_goal": {"type": "string", "enum": ["target_prioritization", "repurposing", "small_molecule_generation", "protein_binder_design", "clinical_translation"], "default": "target_prioritization"},
            "disease": {"type": "string"},
            "target": {"type": "string"},
            "evidence_modalities": {"type": "array", "items": {"type": "string"}},
            "structure_available": {"type": "boolean", "default": False},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def ai_drug_discovery_ml_plan(
    discovery_goal: str = "target_prioritization",
    disease: Optional[str] = None,
    target: Optional[str] = None,
    evidence_modalities: Optional[List[str]] = None,
    structure_available: bool = False,
    seed: int = 0,
):
    modalities = evidence_modalities or ["literature", "omics", "drug_database"]
    params = {
        "discovery_goal": discovery_goal,
        "disease": disease,
        "target": target,
        "evidence_modalities": modalities,
        "structure_available": structure_available,
        "seed": seed,
    }
    plan_hash = _hash("ai_drug_discovery_ml_plan", params)
    return {
        "plan_hash": plan_hash,
        "params": params,
        "stage_gates": _drug_stage_gates(discovery_goal, structure_available),
        "model_stack": _drug_model_stack(discovery_goal, structure_available),
        "validation_contract": [
            "Separate target evidence from molecule evidence; do not let generated molecules rescue a weak target rationale.",
            "Require at least one orthogonal assay or external dataset before translational language.",
            "Report negative and inactive controls, selectivity panel, ADMET/liability triage and uncertainty.",
            "For clinical translation, connect mechanism to endpoint and patient population with evidence_graph.",
        ],
        "handoffs": [
            "bio-drug Open Targets / ChEMBL / RxNorm / openFDA tools",
            "bio-gene for target normalization and variant context",
            "bio-audit evidence_graph and scientific-critique before claims",
        ],
        "script": _render_drug_discovery_script(discovery_goal, disease, target, modalities, seed),
        "provenance_skeleton": {
            "schema": "bio-ml/ai-drug-discovery-provenance/1",
            "plan_hash": plan_hash,
            "target": {"symbol": target or "<FILL>", "normalization_hash": "<FILL>"},
            "disease": {"name": disease or "<FILL>", "ontology_id": "<FILL>"},
            "evidence": {"modalities": modalities, "evidence_graph_hash": "<FILL>"},
            "model": {"family": "<FILL>", "version": "<FILL>", "seed": seed},
            "assays": {"primary": "<FILL>", "orthogonal": "<FILL>", "admet": "<FILL>"},
        },
        "warnings": [
            "Docking score, generated affinity or literature association alone is not a therapeutic hypothesis.",
            "Clinical translation requires disease-stage, population and endpoint boundaries.",
        ],
    }


def _drug_stage_gates(goal: str, structure_available: bool) -> List[str]:
    gates = ["entity normalization", "evidence graph with counter-evidence", "baseline or prior-art comparison"]
    if goal in {"target_prioritization", "repurposing"}:
        gates += ["genetic/omics support", "disease relevance", "tractability and safety liability"]
    if goal in {"small_molecule_generation", "protein_binder_design"}:
        gates += ["property constraints declared before generation", "novelty/diversity audit", "in silico selectivity and ADMET triage"]
    if structure_available:
        gates += ["structure confidence or experimental structure provenance", "pose/interaction sanity check"]
    else:
        gates += ["structure-unavailable fallback documented"]
    if goal == "clinical_translation":
        gates += ["patient-selection hypothesis", "endpoint and comparator", "clinical evidence readiness gate"]
    return gates


def _drug_model_stack(goal: str, structure_available: bool) -> List[str]:
    stack = {
        "target_prioritization": ["network propagation / graph ML", "omics feature model", "literature-grounded evidence ranker"],
        "repurposing": ["drug-target graph model", "signature reversal baseline", "safety/label filter"],
        "small_molecule_generation": ["molecular graph/diffusion generator", "property predictor", "retrosynthesis feasibility screen"],
        "protein_binder_design": ["structure or sequence-conditioned binder generator", "interface scorer", "immunogenicity/developability screen"],
        "clinical_translation": ["patient stratification model", "endpoint risk model", "trial feasibility model"],
    }.get(goal, ["evidence ranker"])
    if structure_available:
        stack.append("structure-aware docking or complex prediction baseline")
    return stack


def _render_drug_discovery_script(goal: str, disease: Optional[str], target: Optional[str], modalities: List[str], seed: int) -> str:
    return _skeleton_header("AI drug discovery ML plan") + f'''
import json
import numpy as np

np.random.seed({seed})
plan = {{
    "discovery_goal": "{goal}",
    "disease": {disease!r},
    "target": {target!r},
    "evidence_modalities": {modalities!r},
    "stage_gates": ["evidence_graph", "baseline", "orthogonal_validation", "admet_or_safety"],
}}
# TODO: normalize disease/target/drug entities before model scoring.
# TODO: freeze property constraints and validation assays before candidate generation.
# TODO: write go/no-go decisions with negative evidence, not only top candidates.
json.dump(plan, open("ai_drug_discovery_plan.json", "w"), indent=2)
'''


@server.tool(
    "biomedical_ml_validation_gate",
    "Gate whether an ML result is ready for exploratory, discovery, translational, clinical decision-support or "
    "diagnostic-device language. Use before writing claims based on ML outputs.",
    {
        "type": "object",
        "properties": {
            "claim_scope": {"type": "string", "enum": _CLAIM_SCOPES, "default": "discovery"},
            "n_sites": {"type": "integer", "default": 1},
            "has_locked_provenance": {"type": "boolean", "default": False},
            "has_leakage_audit": {"type": "boolean", "default": False},
            "has_baseline_model": {"type": "boolean", "default": False},
            "has_external_validation": {"type": "boolean", "default": False},
            "has_calibration": {"type": "boolean", "default": False},
            "has_subgroup_bias_audit": {"type": "boolean", "default": False},
            "has_interpretability_or_rationale": {"type": "boolean", "default": False},
            "has_prospective_or_silent_evaluation": {"type": "boolean", "default": False},
            "has_drift_monitoring": {"type": "boolean", "default": False},
            "has_locked_test_set_and_prespecified_endpoint": {"type": "boolean", "default": False},
        },
    },
)
def biomedical_ml_validation_gate(
    claim_scope: str = "discovery",
    n_sites: int = 1,
    has_locked_provenance: bool = False,
    has_leakage_audit: bool = False,
    has_baseline_model: bool = False,
    has_external_validation: bool = False,
    has_calibration: bool = False,
    has_subgroup_bias_audit: bool = False,
    has_interpretability_or_rationale: bool = False,
    has_prospective_or_silent_evaluation: bool = False,
    has_drift_monitoring: bool = False,
    has_locked_test_set_and_prespecified_endpoint: bool = False,
):
    checks = {
        "locked_provenance": has_locked_provenance,
        "leakage_audit": has_leakage_audit,
        "baseline_model": has_baseline_model,
        "external_validation": has_external_validation,
        "multi_site_external_validation": has_external_validation and n_sites >= 2,
        "calibration": has_calibration,
        "subgroup_bias_audit": has_subgroup_bias_audit,
        "interpretability_or_rationale": has_interpretability_or_rationale,
        "prospective_or_silent_evaluation": has_prospective_or_silent_evaluation,
        "drift_monitoring": has_drift_monitoring,
        "locked_test_set_and_prespecified_endpoint": has_locked_test_set_and_prespecified_endpoint,
        "at_least_two_sites_or_documented_external_cohort": n_sites >= 2 or has_external_validation,
    }
    required = _scope_requirements(claim_scope, n_sites)
    missing = [r for r in required if not checks.get(r, False)]
    verdict = "ready_for_claim_scope" if not missing else "not_ready_for_claim_scope"
    return {
        "verdict": verdict,
        "claim_scope": claim_scope,
        "n_sites": n_sites,
        "checks": checks,
        "required": required,
        "missing": missing,
        "allowed_language": _allowed_language(verdict, claim_scope),
        "minimum_next_steps": _minimum_next_steps(missing),
    }


def _minimum_next_steps(missing: List[str]) -> List[str]:
    guidance = {
        "locked_provenance": "Attach dataset, split, preprocessing, model-version and metric hashes.",
        "leakage_audit": "Audit patient/donor/site leakage and preprocessing-fit leakage.",
        "baseline_model": "Run a simple baseline on the identical locked split.",
        "external_validation": "Evaluate on an external site/cohort untouched during development.",
        "multi_site_external_validation": "Add multi-site external validation or reduce claim scope.",
        "calibration": "Report calibration slope/intercept, Brier score or reliability curve.",
        "subgroup_bias_audit": "Report subgroup/site/platform performance and failure cases.",
        "interpretability_or_rationale": "Provide interpretable features, saliency audit, guideline grounding or mechanistic rationale.",
        "prospective_or_silent_evaluation": "Run silent/prospective evaluation in intended workflow before clinical use.",
        "drift_monitoring": "Define post-deployment drift and performance monitoring.",
        "locked_test_set_and_prespecified_endpoint": "Lock endpoint, threshold and test set before final evaluation.",
        "at_least_two_sites_or_documented_external_cohort": "Add another site/cohort or document why external validation is impossible.",
    }
    return [guidance.get(m, f"Address {m}.") for m in missing] or ["No blocking next step for the requested scope."]


@server.tool(
    "self_driving_lab_plan",
    "Generate a human-in-the-loop self-driving laboratory plan with ML proposal, experiment execution, assay QC, "
    "stopping rules, evidence ledger and safety boundaries.",
    {
        "type": "object",
        "properties": {
            "loop_goal": {"type": "string", "default": "optimize_biological_response"},
            "assay_type": {"type": "string", "default": "cell_based_assay"},
            "autonomy_mode": {"type": "string", "enum": ["ai_advisor", "human_approved_closed_loop", "bounded_autonomous_screen"], "default": "human_approved_closed_loop"},
            "max_iterations": {"type": "integer", "default": 5},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def self_driving_lab_plan(
    loop_goal: str = "optimize_biological_response",
    assay_type: str = "cell_based_assay",
    autonomy_mode: str = "human_approved_closed_loop",
    max_iterations: int = 5,
    seed: int = 0,
):
    params = {
        "loop_goal": loop_goal,
        "assay_type": assay_type,
        "autonomy_mode": autonomy_mode,
        "max_iterations": max_iterations,
        "seed": seed,
    }
    plan_hash = _hash("self_driving_lab_plan", params)
    return {
        "plan_hash": plan_hash,
        "params": params,
        "loop_contract": [
            "Define objective, constraints and negative controls before the first model suggestion.",
            "Require human approval for every protocol-changing action unless the action is within a preapproved bounded screen.",
            "After each iteration, update the evidence ledger with successes, failures and assay QC.",
            "Stop on safety boundary, assay drift, budget limit, no improvement, or invalid controls.",
        ],
        "model_loop": {
            "propose": "Bayesian optimization / active learning / constrained generator",
            "execute": "human-approved wet-lab or robotics run with protocol hash",
            "measure": f"{assay_type} readout with plate/batch QC",
            "learn": "update surrogate model only with validated measurements",
        },
        "safety_and_qc": [
            "No autonomous hazardous protocol generation.",
            "Plate/batch/randomization controls required for every iteration.",
            "Prespecify allowed reagent/construct/design space.",
            "Record failed and null experiments; they are part of the model evidence.",
        ],
        "script": _render_self_driving_lab_script(loop_goal, assay_type, autonomy_mode, max_iterations, seed),
        "provenance_skeleton": {
            "schema": "bio-ml/self-driving-lab-provenance/1",
            "plan_hash": plan_hash,
            "design_space_hash": "<FILL>",
            "iterations": [{"iteration": i + 1, "proposal_hash": "<FILL>", "protocol_hash": "<FILL>", "result_hash": "<FILL>"} for i in range(max(1, max_iterations))],
            "stopping_rule": "<FILL>",
            "human_approvals": "<FILL>",
        },
        "warnings": [
            "Fully autonomous open-ended biological discovery is not the default safe operating mode.",
            "Use this as a closed-loop study plan, not as permission to execute wet-lab actions without review.",
        ],
    }


def _render_self_driving_lab_script(goal: str, assay: str, mode: str, max_iterations: int, seed: int) -> str:
    return _skeleton_header("Self-driving laboratory loop plan") + f'''
import json
import numpy as np

np.random.seed({seed})
loop = {{
    "goal": "{goal}",
    "assay_type": "{assay}",
    "autonomy_mode": "{mode}",
    "max_iterations": {max_iterations},
    "required_controls": ["negative_control", "positive_control", "randomization", "plate_batch_qc"],
}}
# TODO: define bounded design space and human approval policy.
# TODO: choose active-learning optimizer and assay QC checks.
# TODO: append every result, including failed/null experiments, to the evidence ledger.
json.dump(loop, open("self_driving_lab_loop_plan.json", "w"), indent=2)
'''


if __name__ == "__main__":
    server.run()
