"""Deterministic, contradiction-driven biomedical hypothesis generation.

This module sits between :mod:`causal_kg` conflict detection and the
``bio-experiment`` planning pack.  It deliberately does *not* infer that any
generated mechanism is true.  Instead it turns two incompatible KG edges into
an auditable set of rival, falsifiable explanations and experiments whose
outcomes would distinguish them.

The implementation is stdlib-only so it can run in the offline MCP packs.  A
language model can enrich the generated records later, but it must preserve the
observed/generated boundary and the source-edge provenance emitted here.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import causal_kg


ENGINE_VERSION = "1.0.0"

# These are study descriptors, not biological facts.  Preserve them when they
# are present on curated edges even though the minimal causal-KG schema does not
# require every field.
_DIMENSIONS: Tuple[Tuple[str, str], ...] = (
    ("context", "disease/tissue context"),
    ("model_system", "model system"),
    ("species", "species"),
    ("population", "population"),
    ("disease_stage", "disease stage"),
    ("tissue", "tissue"),
    ("cell_state", "cell state"),
    ("dose", "dose or exposure"),
    ("timepoint", "timepoint"),
    ("endpoint", "endpoint"),
    ("experiment_type", "method or assay"),
    ("study_design", "study design"),
)

# Exact keyword arguments accepted by bio-experiment.agentic_experiment_plan,
# excluding ``hypothesis`` (owned by the selected generated hypothesis) and
# ``constraints`` (where non-matching feasibility metadata is retained).
_EXPERIMENT_PLAN_TOP_LEVEL_ARGS = {
    "research_question",
    "disease_context",
    "model_system",
    "intervention",
    "primary_endpoint",
    "assay_family",
    "outcome_type",
    "effect_size",
    "baseline_rate",
    "treatment_rate",
    "hazard_ratio",
    "power",
    "alpha",
    "budget_usd",
    "timeline_weeks",
    "prior_evidence",
    "species",
}

_TEMPORAL_TERMS = re.compile(
    r"\b(?:minute|hour|day|week|month|acute|chronic|early|late|short[- ]term|long[- ]term|"
    r"min|hrs?|days?|weeks?|months?|h|d)\b",
    re.I,
)
_DOSE_TERMS = re.compile(
    r"\b(?:dose|dosage|concentration|exposure|low|high|mg|ug|ng|pg|mm|um|nm|pm|μm|µm)\b",
    re.I,
)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _stable_id(prefix: str, value: Any, length: int = 16) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return prefix + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _fingerprint_payload(value: Any) -> Any:
    """Remove non-content normalization metadata before hashing.

    A missing source timestamp is represented by a stable
    ``timestamp_origin=generated_at_normalization`` marker.  The wall-clock
    timestamp itself is an ingestion convenience, not evidence content, and
    must not make otherwise identical contradiction plans hash differently.
    """

    if isinstance(value, dict):
        synthetic_timestamp = value.get("timestamp_origin") == "generated_at_normalization"
        return {
            key: _fingerprint_payload(item)
            for key, item in value.items()
            if not (key == "timestamp" and synthetic_timestamp)
        }
    if isinstance(value, (list, tuple)):
        return [_fingerprint_payload(item) for item in value]
    return value


def _content_fingerprint(value: Any) -> str:
    return _stable_id("sha256:", _fingerprint_payload(value), 64)


def _as_list(value: Any) -> List[str]:
    if value is None or value == "":
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _display(value: Any) -> str:
    values = _as_list(value)
    return ", ".join(values) if values else "not reported"


def _name(edge: Dict[str, Any], side: str) -> str:
    value = edge.get(side)
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def _edge_text(edge: Dict[str, Any]) -> str:
    fields = [
        edge.get("claim_text"),
        edge.get("context"),
        edge.get("model_system"),
        edge.get("dose"),
        edge.get("timepoint"),
        edge.get("endpoint"),
        edge.get("study_design"),
        edge.get("experiment_type"),
    ]
    return " ".join(_display(value) for value in fields if value not in (None, "", []))


def _normalize_edge(edge: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(edge, dict):
        return None
    recorded_source = edge.get("source")
    norm = causal_kg.normalize_triple(edge, source=str(recorded_source or ""))
    if not norm:
        return None
    # ``source`` describes evidence provenance.  Do not replace a missing
    # source with an internal left/right processing label.
    norm["source"] = recorded_source or None

    # Keep curated study descriptors and provenance extras.  Core KG
    # normalization intentionally stays small; the hypothesis layer needs the
    # richer metadata to propose effect modifiers without inventing them.
    for field, _label in _DIMENSIONS:
        if field in edge:
            norm[field] = edge[field]
    for field in ("provenance", "evidence_snippet", "sample_size", "effect_size", "uncertainty"):
        if field in edge:
            norm[field] = edge[field]
    return norm


def _pair_from_record(record: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    pairs = (
        ("candidate", "conflicting_edge"),
        ("edge_a", "edge_b"),
        ("positive_edge", "negative_edge"),
        ("claim_a", "claim_b"),
    )
    for left, right in pairs:
        if isinstance(record.get(left), dict) and isinstance(record.get(right), dict):
            return record[left], record[right]
    return None, None


def canonicalize_conflicts(conflicts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate, orient, and de-duplicate conflict-scan records.

    ``causal_kg.find_conflicts`` compares every edge with every other edge and
    therefore emits A-vs-B and B-vs-A when no candidate is supplied.  This
    function collapses that symmetry and always emits the positive edge first.
    """

    unique: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for raw in conflicts or []:
        if not isinstance(raw, dict):
            continue
        left_raw, right_raw = _pair_from_record(raw)
        if left_raw is None or right_raw is None:
            continue
        left = _normalize_edge(left_raw)
        right = _normalize_edge(right_raw)
        if not left or not right:
            continue
        if _name(left, "subject") != _name(right, "subject"):
            continue
        if _name(left, "object") != _name(right, "object"):
            continue
        if not causal_kg.opposite_direction(left.get("relation", ""), right.get("relation", "")):
            continue

        if causal_kg.relation_direction(left.get("relation", "")) == "negative":
            left, right = right, left
        key = tuple(sorted((str(left["id"]), str(right["id"]))))
        left_context = str(left.get("context") or "").strip()
        right_context = str(right.get("context") or "").strip()
        context_known = bool(left_context and right_context)
        similarity = raw.get("context_similarity") if context_known else None
        if similarity is None and context_known:
            similarity = causal_kg.context_similarity(left_context, right_context)
        unique[key] = {
            "positive_edge": left,
            "negative_edge": right,
            "context_similarity": round(_clamp(similarity, 0.0), 3) if context_known else None,
            "context_overlap_status": "measured" if context_known else "unknown_missing_context",
            "reason": str(raw.get("reason") or "same directed entity pair has opposite causal direction"),
        }
    return sorted(unique.values(), key=lambda item: (_name(item["positive_edge"], "subject"), _name(item["positive_edge"], "object"), item["positive_edge"]["id"], item["negative_edge"]["id"]))


def conflicts_from_triples(
    triples: Sequence[Dict[str, Any]],
    min_context_similarity: float = 0.2,
) -> List[Dict[str, Any]]:
    """Find and canonicalize conflicts from causal-KG triples."""

    rows = causal_kg.load_triples(triples=list(triples or []))
    found = causal_kg.find_conflicts(
        rows,
        min_context_similarity=_clamp(min_context_similarity, 0.2),
    )
    return canonicalize_conflicts(found)


def _provenance_completeness(edge: Dict[str, Any]) -> float:
    score = 0.0
    score += 0.30 if _as_list(edge.get("evidence")) else 0.0
    score += 0.15 if edge.get("source") else 0.0
    score += 0.15 if edge.get("claim_text") or edge.get("evidence_snippet") else 0.0
    score += 0.10 if edge.get("timestamp") and edge.get("timestamp_origin") != "generated_at_normalization" else 0.0
    score += 0.10 if edge.get("model_system") else 0.0
    score += 0.10 if _as_list(edge.get("experiment_type")) else 0.0
    score += 0.10 if edge.get("context") else 0.0
    return round(score, 3)


def _edge_provenance(edge: Dict[str, Any], role: str) -> Dict[str, Any]:
    timestamp_origin = edge.get("timestamp_origin") or "legacy_or_unspecified"
    timestamp = edge.get("timestamp")
    return {
        "edge_id": edge.get("id"),
        "role_in_observed_conflict": role,
        "subject": _name(edge, "subject"),
        "relation": edge.get("relation"),
        "object": _name(edge, "object"),
        "claim_text": edge.get("claim_text") or edge.get("evidence_snippet") or "not provided",
        "evidence_ids": _as_list(edge.get("evidence")),
        "source": edge.get("source") or "not provided",
        "timestamp": "not provided" if timestamp_origin == "generated_at_normalization" else (timestamp or "not provided"),
        "timestamp_origin": timestamp_origin,
        "kg_ingested_at": timestamp if timestamp_origin == "generated_at_normalization" else None,
        "confidence": round(_clamp(edge.get("confidence"), 0.5), 3),
        "context": edge.get("context") or "not reported",
        "model_system": edge.get("model_system") or "not reported",
        "experiment_type": _as_list(edge.get("experiment_type")),
        "provenance_completeness": _provenance_completeness(edge),
    }


def _independent_evidence(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[float, List[str]]:
    reasons: List[str] = []
    score = 0.0
    a_ids, b_ids = set(_as_list(a.get("evidence"))), set(_as_list(b.get("evidence")))
    if a_ids and b_ids and a_ids.isdisjoint(b_ids):
        score += 0.65
        reasons.append("citation/evidence identifiers are disjoint")
    elif not a_ids or not b_ids:
        reasons.append("independence cannot be checked because at least one edge lacks evidence identifiers")
    else:
        reasons.append("the edges share at least one evidence identifier")
    a_source, b_source = str(a.get("source") or ""), str(b.get("source") or "")
    if a_source and b_source and a_source != b_source:
        score += 0.35
        reasons.append("recorded sources differ")
    elif a_source and b_source:
        reasons.append("recorded sources are the same; this does not establish study independence")
    return round(min(score, 1.0), 3), reasons


def _dimension_comparison(a: Dict[str, Any], b: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for field, label in _DIMENSIONS:
        av, bv = _as_list(a.get(field)), _as_list(b.get(field))
        if not av and not bv:
            status = "missing_both"
        elif not av or not bv:
            status = "missing_one"
        elif {x.lower() for x in av} == {x.lower() for x in bv}:
            status = "same_reported_value"
        else:
            status = "observed_difference"
        rows.append({
            "dimension": field,
            "label": label,
            "positive_edge_value": av or ["not reported"],
            "negative_edge_value": bv or ["not reported"],
            "status": status,
        })
    return rows


def _strength(
    positive: Dict[str, Any],
    negative: Dict[str, Any],
    context_similarity: Optional[float],
) -> Dict[str, Any]:
    pa, pb = _clamp(positive.get("confidence"), 0.5), _clamp(negative.get("confidence"), 0.5)
    support = (pa * pb) ** 0.5
    provenance = (_provenance_completeness(positive) + _provenance_completeness(negative)) / 2.0
    independence, independence_reasons = _independent_evidence(positive, negative)
    context_contribution = 0.0 if context_similarity is None else 0.25 * context_similarity
    score = 0.45 * support + context_contribution + 0.20 * provenance + 0.10 * independence
    score = round(_clamp(score), 3)
    label = "strong" if score >= 0.75 else "moderate" if score >= 0.50 else "weak"
    return {
        "score": score,
        "label": label,
        "meaning": "Credibility that two independently supported claims address sufficiently overlapping questions and truly disagree; not confidence in either causal direction.",
        "components": {
            "paired_edge_support": round(support, 3),
            "context_overlap": round(context_similarity, 3) if context_similarity is not None else None,
            "context_overlap_status": "measured" if context_similarity is not None else "unknown_missing_context",
            "context_overlap_weight_contribution": round(context_contribution, 3),
            "provenance_completeness": round(provenance, 3),
            "recorded_evidence_independence": independence,
        },
        "missing_evidence_components": ["context_overlap"] if context_similarity is None else [],
        "independence_notes": independence_reasons,
    }


def _score_label(score: float) -> str:
    if score >= 0.72:
        return "higher-priority candidate"
    if score >= 0.52:
        return "plausible candidate"
    return "lower-priority candidate"


def _hypothesis_record(
    conflict_id: str,
    rank: int,
    category: str,
    statement: str,
    rationale: str,
    score: float,
    drivers: List[str],
    predictions: List[Dict[str, str]],
    falsifiers: List[str],
    data_needed: List[str],
    source_edge_ids: List[str],
    assumptions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "hypothesis_id": f"{conflict_id}:H{rank}",
        "record_type": "generated_hypothesis",
        "validation_status": "not_tested",
        "category": category,
        "statement": statement,
        "rationale": rationale,
        "priority": {
            "score": round(_clamp(score), 3),
            "label": _score_label(score),
            "interpretation": "Heuristic prioritization for experiment selection, not a posterior probability or evidence grade.",
            "drivers": drivers,
        },
        "predictions": [
            {"record_type": "prediction", **prediction}
            for prediction in predictions
        ],
        "falsification_criteria": falsifiers,
        "data_needed": data_needed,
        "assumptions": assumptions or [],
        "derived_from_edge_ids": source_edge_ids,
        "epistemic_warning": "Generated explanation only; it is not an observed or validated mechanism.",
    }


def _candidate_hypotheses(
    conflict_id: str,
    positive: Dict[str, Any],
    negative: Dict[str, Any],
    comparisons: List[Dict[str, Any]],
    max_hypotheses: int,
) -> List[Dict[str, Any]]:
    subject, obj = _name(positive, "subject"), _name(positive, "object")
    source_edge_ids = [str(positive["id"]), str(negative["id"])]
    statuses = {row["dimension"]: row for row in comparisons}
    observed_differences = [row["dimension"] for row in comparisons if row["status"] == "observed_difference"]
    missing = [row["dimension"] for row in comparisons if row["status"].startswith("missing")]
    text = (_edge_text(positive) + " " + _edge_text(negative)).lower()

    model_dims = [d for d in ("context", "model_system", "species", "population", "disease_stage", "tissue", "cell_state") if d in observed_differences]
    context_score = 0.80 if model_dims else 0.54 if any(d in missing for d in ("model_system", "species", "population", "tissue")) else 0.42
    context_drivers = (["reported difference: " + ", ".join(model_dims)] if model_dims else ["key biological-context fields are incomplete; effect modification remains possible"])

    temporal_observed = [d for d in ("dose", "timepoint") if d in observed_differences]
    temporal_signal = bool(_TEMPORAL_TERMS.search(text) or _DOSE_TERMS.search(text))
    temporal_score = 0.76 if temporal_observed else 0.58 if temporal_signal else 0.42
    temporal_drivers = (["reported difference: " + ", ".join(temporal_observed)] if temporal_observed else ["dose/time metadata do not rule out a non-monotonic or phase-dependent effect"])

    method_dims = [d for d in ("endpoint", "experiment_type", "study_design") if d in observed_differences]
    method_score = 0.78 if method_dims else 0.54 if any(d in missing for d in ("endpoint", "experiment_type", "study_design")) else 0.44
    method_drivers = (["reported difference: " + ", ".join(method_dims)] if method_dims else ["method and endpoint equivalence is not fully documented"])

    confidence_gap = abs(_clamp(positive.get("confidence"), 0.5) - _clamp(negative.get("confidence"), 0.5))
    missing_citation = not _as_list(positive.get("evidence")) or not _as_list(negative.get("evidence"))
    artifact_score = min(0.82, 0.48 + 0.25 * confidence_gap + (0.14 if missing_citation else 0.0))
    artifact_drivers = ["edge-confidence imbalance is %.2f" % confidence_gap]
    if missing_citation:
        artifact_drivers.append("at least one edge lacks a citation/evidence identifier")

    feedback_score = 0.50 + (0.08 if temporal_signal else 0.0)

    candidates: List[Tuple[str, float, Dict[str, Any]]] = []
    candidates.append(("context_effect_modification", context_score, {
        "statement": f"The direction of {subject}'s effect on {obj} depends on biological context (model, species, population, tissue, disease stage, or cell state).",
        "rationale": "Opposite directions can coexist if the source studies sampled different effect-modifying contexts.",
        "drivers": context_drivers,
        "predictions": [
            {"condition": "harmonized perturbation is applied across the two source contexts", "expected_observation": "the sign tracks prespecified context strata", "distinguishes_from": "a context-invariant single direction"},
            {"condition": "the same context is reproduced independently", "expected_observation": "the direction is reproducible within that context", "distinguishes_from": "random technical variation"},
        ],
        "falsifiers": ["Both source directions fail to reproduce when perturbation, endpoint, dose, and time are harmonized.", "A single direction is consistent across adequately powered context strata with a narrow interaction confidence interval."],
        "data_needed": ["complete model/species/population/tissue/stage/cell-state metadata for both source studies", "stratum-specific effect sizes and uncertainty"],
        "assumptions": ["the compared contexts are experimentally accessible", "the endpoint represents the same construct in both contexts"],
    }))
    candidates.append(("dose_or_time_dependent_sign_switch", temporal_score, {
        "statement": f"The {subject}→{obj} effect changes sign across dose or time because the response is non-monotonic, transient, or adaptive.",
        "rationale": "A single-dose or single-timepoint comparison cannot distinguish a stable effect from a sign-changing response surface.",
        "drivers": temporal_drivers,
        "predictions": [
            {"condition": "dose and time are jointly sampled", "expected_observation": "positive and negative regions occur reproducibly on the response surface", "distinguishes_from": "measurement noise or a fixed direction"},
            {"condition": "proximal and delayed endpoints are measured", "expected_observation": "the proximal response precedes any delayed reversal", "distinguishes_from": "unrelated endpoint variation"},
        ],
        "falsifiers": ["The direction remains constant across a prespecified exposure range and time course with adequate precision.", "The apparent reversal disappears after matching effective perturbation strength."],
        "data_needed": ["exact dose, exposure duration, sampling time, perturbation efficiency, and viability for both edges", "raw time-course effect sizes with confidence intervals"],
        "assumptions": ["assays remain in their validated dynamic ranges"],
    }))
    candidates.append(("method_or_endpoint_artifact", method_score, {
        "statement": f"The apparent sign conflict reflects different assays, endpoint definitions, normalization, or study designs rather than opposite biology between {subject} and {obj}.",
        "rationale": "Methods can measure different layers of a causal chain or introduce direction-changing bias.",
        "drivers": method_drivers,
        "predictions": [
            {"condition": "orthogonal endpoints are measured on the same randomized samples", "expected_observation": "the sign separates by assay/endpoint rather than sample context", "distinguishes_from": "true biological context modification"},
            {"condition": "analysis is rerun from raw data with a shared pipeline", "expected_observation": "one sign may disappear or converge", "distinguishes_from": "a robust causal sign switch"},
        ],
        "falsifiers": ["Orthogonal assays and a locked shared analysis reproduce opposite directions within the same samples.", "Reanalysis with identical normalization preserves the conflict."],
        "data_needed": ["raw measurements, endpoint definitions, normalization code, batch structure, and assay validation", "within-sample orthogonal measurements"],
        "assumptions": ["raw or sufficiently granular source data can be obtained"],
    }))
    candidates.append(("adaptive_feedback_or_intermediate", feedback_score, {
        "statement": f"{subject} has an initial effect on {obj}, while an unmeasured intermediate or feedback process later produces the opposite net effect.",
        "rationale": "The two KG edges collapse a potentially multi-step, state-dependent causal path into a direct signed relation.",
        "drivers": ["the current KG edges encode net direction but do not establish path length or feedback timing"],
        "predictions": [
            {"condition": "dense temporal measurements include candidate intermediates", "expected_observation": "a reproducible ordered transition precedes reversal of the net endpoint", "distinguishes_from": "instantaneous assay artifact"},
            {"condition": "the candidate intermediate is blocked or rescued", "expected_observation": "the delayed opposite phase is selectively removed or restored", "distinguishes_from": "simple context-only modification"},
        ],
        "falsifiers": ["No temporally ordered intermediate is detected despite adequate measurement coverage.", "Blocking plausible intermediate paths does not alter the sign pattern."],
        "data_needed": ["time-resolved proximal and distal readouts", "candidate mediator measurements selected from independent evidence, not from this template"],
        "assumptions": ["the recorded edges may summarize indirect effects"],
    }))
    candidates.append(("one_claim_biased_or_noncausal", artifact_score, {
        "statement": f"At least one {subject}→{obj} edge is a biased, confounded, underpowered, or incorrectly extracted causal claim.",
        "rationale": "An observed conflict does not require two true biological effects; one edge may not survive direct replication or curation.",
        "drivers": artifact_drivers,
        "predictions": [
            {"condition": "both claims undergo blinded, preregistered replication with matched perturbations", "expected_observation": "one direction fails replication or its interval includes the null", "distinguishes_from": "a reproducible context-dependent sign switch"},
            {"condition": "source text and methods are manually curated", "expected_observation": "one edge may be downgraded to association or assigned a different context", "distinguishes_from": "a correctly extracted direct conflict"},
        ],
        "falsifiers": ["Both directions replicate with adequate precision in their source contexts and pass causal controls.", "Independent curation confirms both edge directions, scopes, and citations."],
        "data_needed": ["sample size, effect estimate, confidence interval, preregistration status, exclusions, and source passage for each edge", "independent edge curation and replication status"],
        "assumptions": ["KG extraction or primary-study bias remains possible until audited"],
    }))

    candidates.sort(key=lambda row: (-row[1], row[0]))
    records: List[Dict[str, Any]] = []
    for rank, (category, score, data) in enumerate(candidates[:max_hypotheses], 1):
        records.append(_hypothesis_record(
            conflict_id=conflict_id,
            rank=rank,
            category=category,
            statement=data["statement"],
            rationale=data["rationale"],
            score=score,
            drivers=data["drivers"],
            predictions=data["predictions"],
            falsifiers=data["falsifiers"],
            data_needed=data["data_needed"],
            source_edge_ids=source_edge_ids,
            assumptions=data["assumptions"],
        ))
    return records


def _handoff(
    question: str,
    hypothesis: str,
    positive: Dict[str, Any],
    negative: Dict[str, Any],
    endpoint: str,
    intervention: str,
    assay_family: str,
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    evidence = sorted(set(_as_list(positive.get("evidence")) + _as_list(negative.get("evidence"))))
    models = sorted(set(_as_list(positive.get("model_system")) + _as_list(negative.get("model_system"))))
    contexts = sorted(set(_as_list(positive.get("context")) + _as_list(negative.get("context"))))
    arguments: Dict[str, Any] = {
        "research_question": question,
        "hypothesis": hypothesis,
        "disease_context": "; ".join(contexts),
        "model_system": "; ".join(models) or "<FILL from source studies>",
        "intervention": intervention,
        "primary_endpoint": endpoint,
        "assay_family": assay_family,
        "outcome_type": "continuous",
        "prior_evidence": "; ".join(evidence) or "No evidence identifier supplied; curate before execution.",
    }
    retained_constraints: Dict[str, Any] = {}
    hoisted: List[str] = []
    for key, value in constraints.items():
        if key in _EXPERIMENT_PLAN_TOP_LEVEL_ARGS and value is not None:
            arguments[key] = value
            hoisted.append(key)
        elif key not in _EXPERIMENT_PLAN_TOP_LEVEL_ARGS:
            retained_constraints[key] = value
    arguments["constraints"] = retained_constraints
    return {
        "target_tool": "bio-experiment.agentic_experiment_plan",
        "arguments": arguments,
        "argument_mapping": {
            "hoisted_constraint_keys": sorted(hoisted),
            "retained_constraint_keys": sorted(retained_constraints),
            "rule": "Keys matching agentic_experiment_plan parameters are passed at top level; unknown feasibility metadata remains in constraints.",
        },
        "handoff_warning": "Planning scaffold only. Fill effect size, model-specific feasibility, safety, ethics, and exact reagents before execution.",
    }


def _experiments(
    conflict_id: str,
    positive: Dict[str, Any],
    negative: Dict[str, Any],
    hypotheses: List[Dict[str, Any]],
    constraints: Dict[str, Any],
) -> List[Dict[str, Any]]:
    subject, obj = _name(positive, "subject"), _name(positive, "object")
    ids_by_category = {item["category"]: item["hypothesis_id"] for item in hypotheses}
    all_ids = [item["hypothesis_id"] for item in hypotheses]
    contexts = [_display(positive.get("context")), _display(negative.get("context"))]
    models = [_display(positive.get("model_system")), _display(negative.get("model_system"))]

    experiments: List[Dict[str, Any]] = []

    def add(
        number: int,
        title: str,
        question: str,
        targets: List[str],
        design: Dict[str, Any],
        predictions: List[Dict[str, str]],
        decision_rule: str,
        hypothesis_text: str,
        endpoint: str,
        intervention: str,
        assay: str,
    ) -> None:
        experiments.append({
            "experiment_id": f"{conflict_id}:E{number}",
            "record_type": "discriminating_experiment",
            "status": "proposed_not_executed",
            "title": title,
            "question": question,
            "targets_hypothesis_ids": list(dict.fromkeys(item for item in targets if item)),
            "design": design,
            "predicted_outcomes": [{"record_type": "prediction", **item} for item in predictions],
            "decision_rule": decision_rule,
            "analysis_principles": [
                "prespecify the primary endpoint, interaction/contrast, exclusions, and smallest effect of interest",
                "randomize and blind sample labels where feasible; block by batch and source model",
                "report effect sizes and confidence intervals, not sign or p-value alone",
                "treat biological replicates—not cells, fields, or technical wells—as the unit of inference",
            ],
            "bio_experiment_handoff": _handoff(question, hypothesis_text, positive, negative, endpoint, intervention, assay, constraints),
            "epistemic_warning": "This design discriminates explanations; it does not presume that its targeted hypothesis is true.",
        })

    add(
        1,
        "Cross-context perturbation with a locked common endpoint",
        f"Does the sign of the {subject}→{obj} effect depend on source context or model?",
        [ids_by_category.get("context_effect_modification"), ids_by_category.get("one_claim_biased_or_noncausal")],
        {
            "factorial_structure": f"apply the same loss- and/or gain-of-function perturbation of {subject} in both source contexts/models",
            "context_strata": [{"context": contexts[0], "model_system": models[0]}, {"context": contexts[1], "model_system": models[1]}],
            "arms": ["non-targeting or mock control", f"{subject} perturbation", "orthogonal perturbation", "rescue where technically feasible"],
            "primary_endpoint": f"prespecified change in {obj} measured identically across strata",
            "key_controls": ["perturbation-efficiency measurement", "viability/cell-composition control", "positive and negative assay controls", "batch-balanced processing"],
        },
        [
            {"supports": ids_by_category.get("context_effect_modification", "context hypothesis"), "expected_observation": "a precise context-by-perturbation interaction with reproducible opposite signs"},
            {"supports": ids_by_category.get("one_claim_biased_or_noncausal", "one-claim artifact hypothesis"), "expected_observation": "only one source direction replicates under the harmonized design"},
            {"supports": "context-invariant direction", "expected_observation": "the same precise direction appears in both contexts"},
        ],
        "Resolve by the prespecified context-by-perturbation interaction and within-context confidence intervals; an underpowered null interaction is inconclusive.",
        f"The direction of {subject}'s effect on {obj} differs between the two source contexts.",
        f"change in {obj} with a common validated assay",
        f"matched perturbation of {subject} plus orthogonal validation/rescue",
        "perturbation",
    )

    add(
        2,
        "Dose-by-time response surface",
        f"Does the {subject}→{obj} relation reverse across exposure intensity or time?",
        [ids_by_category.get("dose_or_time_dependent_sign_switch"), ids_by_category.get("adaptive_feedback_or_intermediate"), ids_by_category.get("method_or_endpoint_artifact")],
        {
            "factorial_structure": "prespecified multi-level perturbation strength crossed with early, intermediate, and late sampling",
            "arms": ["matched control at every timepoint", "at least three validated perturbation levels", "orthogonal perturbation at key dose/time cells", "rescue at the predicted reversal region"],
            "primary_endpoint": f"continuous {obj} response surface with proximal perturbation-engagement readout",
            "key_controls": ["viability and total-cell control", "assay dynamic-range check", "matched vehicle/control time course", "batch-balanced plate layout"],
        },
        [
            {"supports": ids_by_category.get("dose_or_time_dependent_sign_switch", "dose/time hypothesis"), "expected_observation": "a reproducible sign boundary across dose or time"},
            {"supports": ids_by_category.get("adaptive_feedback_or_intermediate", "feedback hypothesis"), "expected_observation": "an early proximal direction followed by a delayed opposite net response"},
            {"supports": ids_by_category.get("method_or_endpoint_artifact", "method hypothesis"), "expected_observation": "reversal appears in one assay but not orthogonal measurements on the same samples"},
        ],
        "Use a prespecified response-surface model and simultaneous confidence intervals; declare a sign switch only when both regions exclude the smallest effect of interest in opposite directions.",
        f"The {subject}→{obj} effect changes sign over dose or time.",
        f"time-resolved {obj} level plus a proximal target-engagement endpoint",
        f"graded perturbation of {subject}",
        "perturbation",
    )

    add(
        3,
        "Same-sample orthogonal assay triangulation and blinded replication",
        f"Is the conflict caused by assay/analysis choice or by a reproducible biological difference?",
        [ids_by_category.get("method_or_endpoint_artifact"), ids_by_category.get("one_claim_biased_or_noncausal")] + all_ids[:1],
        {
            "structure": "independent replication with raw-data reanalysis and two orthogonal endpoint modalities on the same randomized samples",
            "arms": ["negative control", f"{subject} perturbation", "orthogonal perturbation", "rescue or positive control"],
            "primary_endpoint": f"agreement in direction and standardized effect for {obj} across assays",
            "key_controls": ["locked shared normalization pipeline", "blinded analyst labels", "technical spike-in or calibration control", "complete reporting of exclusions and missingness"],
        },
        [
            {"supports": ids_by_category.get("method_or_endpoint_artifact", "method hypothesis"), "expected_observation": "direction follows assay or normalization while biological samples are held fixed"},
            {"supports": ids_by_category.get("one_claim_biased_or_noncausal", "one-claim artifact hypothesis"), "expected_observation": "one source result fails independent replication across assays"},
            {"supports": "robust biological conflict", "expected_observation": "opposite directions reproduce in source-matched contexts across orthogonal assays"},
        ],
        "Classify outcomes using prespecified assay-agreement and replication criteria; discordance without a validated reference assay remains unresolved.",
        f"The reported {subject}→{obj} sign conflict is attributable to method or non-replication rather than a validated mechanism.",
        f"standardized {obj} effect across two orthogonal assays",
        f"matched perturbation of {subject}",
        "mechanism_validation",
    )
    return experiments


def _data_needs(
    conflict_id: str,
    positive: Dict[str, Any],
    negative: Dict[str, Any],
    comparisons: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    source_ids = [str(positive["id"]), str(negative["id"])]
    needs: List[Dict[str, Any]] = []
    incomplete = [row for row in comparisons if row["status"] in {"missing_both", "missing_one"}]
    differences = [row for row in comparisons if row["status"] == "observed_difference"]

    if incomplete:
        needs.append({
            "data_need_id": f"{conflict_id}:D1",
            "priority": "critical",
            "status": "missing_or_incomplete",
            "data_needed": [row["dimension"] for row in incomplete],
            "why": "Unreported effect modifiers prevent the claims from being aligned to the same causal question.",
            "collection_action": "curate the source methods/supplements or contact authors; record values separately for each edge",
            "source_edge_ids": source_ids,
        })
    if differences:
        needs.append({
            "data_need_id": f"{conflict_id}:D2",
            "priority": "high",
            "status": "reported_values_require_harmonization",
            "data_needed": [row["dimension"] for row in differences],
            "why": "Observed study differences are candidate effect modifiers, but do not establish which one explains the sign conflict.",
            "collection_action": "obtain stratum-level results or reproduce a crossed design that changes one dimension at a time",
            "source_edge_ids": source_ids,
        })
    needs.extend([
        {
            "data_need_id": f"{conflict_id}:D3",
            "priority": "critical",
            "status": "required_for_quantitative_resolution",
            "data_needed": ["signed effect estimate", "confidence interval or standard error", "biological replicate count", "unit of inference", "raw or sample-level data"],
            "why": "A direction label and extraction confidence cannot quantify compatibility, heterogeneity, or power.",
            "collection_action": "extract a common effect metric and its uncertainty from each primary study; do not substitute KG confidence for effect uncertainty",
            "source_edge_ids": source_ids,
        },
        {
            "data_need_id": f"{conflict_id}:D4",
            "priority": "high",
            "status": "required_for_provenance_audit",
            "data_needed": ["verbatim supporting passage", "primary citation identifier", "source independence", "causal-vs-associational design", "retraction/correction status"],
            "why": "The conflict may be duplicated, miscited, associational, corrected, or incorrectly extracted.",
            "collection_action": "audit each edge against its primary source before committing experimental resources",
            "source_edge_ids": source_ids,
        },
    ])
    return needs


def _uncertainty(
    positive: Dict[str, Any],
    negative: Dict[str, Any],
    strength: Dict[str, Any],
    comparisons: List[Dict[str, Any]],
) -> Dict[str, Any]:
    ca, cb = _clamp(positive.get("confidence"), 0.5), _clamp(negative.get("confidence"), 0.5)
    balance = 1.0 - abs(ca - cb)
    missing_fraction = sum(row["status"].startswith("missing") for row in comparisons) / max(len(comparisons), 1)
    score = _clamp(0.30 + 0.38 * strength["score"] + 0.20 * balance + 0.12 * missing_fraction)
    label = "high" if score >= 0.72 else "moderate" if score >= 0.48 else "low"
    observed_differences = [row["dimension"] for row in comparisons if row["status"] == "observed_difference"]
    missing_dimensions = [row["dimension"] for row in comparisons if row["status"].startswith("missing")]
    return {
        "causal_direction_uncertainty": round(score, 3),
        "label": label,
        "interpretation": "Heuristic uncertainty that the causal direction is presently resolvable from the stored records; not a calibrated posterior probability.",
        "resolution_status": "unresolved",
        "observed_candidate_effect_modifiers": observed_differences,
        "unmeasured_or_incomplete_dimensions": missing_dimensions,
        "confidence_balance": round(balance, 3),
        "limitations": [
            "KG edge confidence is extraction/curation confidence, not statistical uncertainty of an effect.",
            "Generated hypotheses are templates conditioned on recorded metadata and may omit the true explanation.",
            "No experiment result, causal identification check, or external evidence retrieval is performed by this engine.",
        ],
    }


def generate_hypotheses(
    conflicts: Iterable[Dict[str, Any]],
    research_context: Optional[Dict[str, Any]] = None,
    experiment_constraints: Optional[Dict[str, Any]] = None,
    max_hypotheses_per_conflict: int = 5,
    max_conflicts: int = 10,
) -> Dict[str, Any]:
    """Generate auditable rival hypotheses for canonical causal conflicts.

    Parameters are already structured so the function is safe to expose as an
    MCP tool.  It returns no free-standing mechanistic assertion: every
    generated record identifies its source edge IDs and ``validation_status``.
    """

    research_context = dict(research_context or {})
    experiment_constraints = dict(experiment_constraints or {})
    max_hypotheses_per_conflict = max(2, min(int(max_hypotheses_per_conflict), 5))
    max_conflicts = max(1, min(int(max_conflicts), 50))
    raw_conflicts = list(conflicts or [])
    all_canonical = canonicalize_conflicts(raw_conflicts)
    eligible_conflict_count = len(all_canonical)
    canonical = all_canonical[:max_conflicts]
    remaining_conflicts = max(0, eligible_conflict_count - len(canonical))
    reports: List[Dict[str, Any]] = []

    for item in canonical:
        positive, negative = item["positive_edge"], item["negative_edge"]
        context_similarity = item["context_similarity"]
        conflict_id = _stable_id("conflict_", {
            "positive_edge_id": positive["id"],
            "negative_edge_id": negative["id"],
        })
        comparisons = _dimension_comparison(positive, negative)
        strength = _strength(positive, negative, context_similarity)
        hypotheses = _candidate_hypotheses(
            conflict_id,
            positive,
            negative,
            comparisons,
            max_hypotheses_per_conflict,
        )
        evidence_provenance = {
            "source_edges": [
                _edge_provenance(positive, "supports_positive_direction"),
                _edge_provenance(negative, "supports_negative_direction"),
            ],
            "evidence_ids": sorted(set(_as_list(positive.get("evidence")) + _as_list(negative.get("evidence")))),
            "input_fingerprint": _content_fingerprint([positive, negative]),
            "provenance_rule": "All observed claims trace to source KG edge IDs; generated text is never added as evidence.",
        }
        reports.append({
            "conflict_id": conflict_id,
            "record_type": "contradiction_analysis",
            "observed_conflict": {
                "record_type": "observed_conflict",
                "validation_status": "recorded_not_adjudicated",
                "subject": _name(positive, "subject"),
                "object": _name(positive, "object"),
                "positive_relation": positive["relation"],
                "negative_relation": negative["relation"],
                "reason": item["reason"],
                "context_similarity": context_similarity,
                "context_overlap_status": item["context_overlap_status"],
                "study_dimension_comparison": comparisons,
                "contradiction_strength": strength,
                "important_distinction": "The opposite signed KG edges are observed records. No explanatory mechanism below is observed merely because it was generated.",
            },
            "evidence_provenance": evidence_provenance,
            "generated_hypotheses": hypotheses,
            "discriminating_experiments": _experiments(
                conflict_id,
                positive,
                negative,
                hypotheses,
                experiment_constraints,
            ),
            "key_data_needs": _data_needs(conflict_id, positive, negative, comparisons),
            "uncertainty": _uncertainty(positive, negative, strength, comparisons),
            "research_context": research_context,
        })

    input_fingerprint = _content_fingerprint(all_canonical)
    return {
        "schema": "bio-kg/contradiction-hypotheses/1",
        "engine": {
            "name": "contradiction_hypotheses",
            "version": ENGINE_VERSION,
            "mode": "deterministic_offline_templates",
            "input_fingerprint": input_fingerprint,
        },
        "status": "hypotheses_generated" if reports else "no_eligible_contradictions",
        "summary": {
            "input_conflict_records": len(raw_conflicts),
            "unique_eligible_conflicts": eligible_conflict_count,
            "reports_returned": len(reports),
            "max_conflicts": max_conflicts,
            "truncated": remaining_conflicts > 0,
            "remaining_eligible_conflicts": remaining_conflicts,
            "generated_hypotheses": sum(len(item["generated_hypotheses"]) for item in reports),
            "proposed_experiments": sum(len(item["discriminating_experiments"]) for item in reports),
        },
        "contradictions": reports,
        "global_epistemic_warning": "These are candidate explanations and predictions for prioritizing tests. They are not validated mechanisms, clinical recommendations, or evidence of efficacy.",
        "next_step": (
            "Audit source provenance, collect critical missing data, then pass a selected experiment handoff to bio-experiment.agentic_experiment_plan."
            if reports
            else "Add or supply two curated opposite-direction edges for the same subject/object pair in overlapping contexts."
        ),
    }
