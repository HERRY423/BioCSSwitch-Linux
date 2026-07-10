#!/usr/bin/env python3
"""MCP façade for BioCSSwitch cross-modal evidence orchestration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Pack servers are executed as standalone files by the current MCP runner, so
# Python does not automatically expose the shared ``packs/_lib`` directory.
# Keep this bootstrap identical across new servers; remove it when the runner
# launches pack servers as installed/importable Python modules.
_PACKS_ROOT = str(Path(__file__).resolve().parents[1])
if _PACKS_ROOT not in sys.path:
    sys.path.insert(0, _PACKS_ROOT)

from _lib import crossmodal  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-crossmodal", "0.1.0")


_NEED_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "disease": {"type": "string"},
        "unmet_need": {"type": "string"},
        "population": {"type": "string"},
        "tissue": {"type": "string"},
        "organism": {"type": "string", "enum": ["human", "mouse"], "default": "human"},
        "current_therapies": {"type": "array", "items": {"type": "string"}},
        "seed_targets": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "object"},
    },
    "required": ["disease", "unmet_need"],
}


@server.tool(
    "crossmodal_plan_unmet_need",
    "Build a dependency-aware plan across bio-lit, bio-gene, bio-drug, bio-trials, "
    "bio-singlecell, and bio-spatial for an unmet clinical need. Returns an empty shared "
    "EvidenceContext. The plan does not make network calls by itself.",
    {
        "type": "object",
        "properties": {"need": _NEED_SCHEMA},
        "required": ["need"],
    },
)
def crossmodal_plan_unmet_need(need: Dict[str, Any]):
    plan = crossmodal.plan_unmet_need(need)
    return {
        "schema": "bio-crossmodal/planning-bundle/1",
        "plan": plan,
        "context": crossmodal.new_evidence_context(need, plan_id=plan["plan_id"]),
    }


@server.tool(
    "crossmodal_reduce_evidence",
    "Normalize one actual pack tool result into the shared EvidenceContext while preserving "
    "source hashes and evidence semantics. Analysis recipes are retained only as provenance.",
    {
        "type": "object",
        "properties": {
            "context": {"type": "object"},
            "step": {"type": "object", "description": "The matching step from crossmodal_plan_unmet_need."},
            "result": {"type": "object", "description": "The real result returned by that pack tool."},
            "target": {"type": "string", "description": "Target symbol for a fan-out step."},
        },
        "required": ["context", "step", "result"],
    },
)
def crossmodal_reduce_evidence(
    context: Dict[str, Any],
    step: Dict[str, Any],
    result: Dict[str, Any],
    target: str = "",
):
    return crossmodal.reduce_tool_result(context, step, result, target=target)


@server.tool(
    "crossmodal_integrate_observations",
    "Add claim-level observations supplied by a pack or curator to the shared context. Each "
    "observation must explicitly say supports, contradicts, or neutral; absence is never converted "
    "to contradiction.",
    {
        "type": "object",
        "properties": {
            "context": {"type": "object"},
            "observations": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["context", "observations"],
    },
)
def crossmodal_integrate_observations(
    context: Dict[str, Any], observations: List[Dict[str, Any]]
):
    return crossmodal.integrate_observations(context, observations)


@server.tool(
    "crossmodal_cross_validate",
    "Cross-check target claims across modalities and independent sources. Returns corroboration, "
    "explicit conflicts, missing modalities, and recipe records excluded from evidence.",
    {
        "type": "object",
        "properties": {"context": {"type": "object"}},
        "required": ["context"],
    },
)
def crossmodal_cross_validate(context: Dict[str, Any]):
    return crossmodal.cross_validate(context)


@server.tool(
    "crossmodal_rank_targets",
    "Rank candidate targets for investigation using biological basis, druggability, translational "
    "specificity, observed trial saturation, evidence diversity, quality, and contradiction penalties. "
    "Scores are research priorities, not clinical recommendations.",
    {
        "type": "object",
        "properties": {
            "context": {"type": "object"},
            "weights": {"type": "object", "description": "Optional dimension weights in [0,1]."},
        },
        "required": ["context"],
    },
)
def crossmodal_rank_targets(
    context: Dict[str, Any], weights: Optional[Dict[str, Any]] = None
):
    return crossmodal.rank_targets(context, weights=weights)


@server.tool(
    "crossmodal_synthesize",
    "Produce coverage, cross-validation, and target ranking from one shared EvidenceContext.",
    {
        "type": "object",
        "properties": {
            "context": {"type": "object"},
            "weights": {"type": "object"},
        },
        "required": ["context"],
    },
)
def crossmodal_synthesize(
    context: Dict[str, Any], weights: Optional[Dict[str, Any]] = None
):
    return {
        "schema": "bio-crossmodal/synthesis/1",
        "coverage": crossmodal.evidence_coverage(context),
        "cross_validation": crossmodal.cross_validate(context),
        "ranking": crossmodal.rank_targets(context, weights=weights),
        "epistemic_status": "hypothesis_generating_research_prioritization",
    }


if __name__ == "__main__":
    server.run()
