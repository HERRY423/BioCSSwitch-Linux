#!/usr/bin/env python3
"""MCP façade for local research-interest learning and proactive briefings."""

from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import Any, Dict, List

# Pack servers are executed as standalone files by the current MCP runner, so
# Python does not automatically expose the shared ``packs/_lib`` directory.
# Keep this bootstrap identical across new servers; remove it when the runner
# launches pack servers as installed/importable Python modules.
_PACKS_ROOT = str(Path(__file__).resolve().parents[1])
if _PACKS_ROOT not in sys.path:
    sys.path.insert(0, _PACKS_ROOT)

from _lib import proactive_research, research_interest  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-research-partner", "0.1.0")


_SENSITIVE_TOPIC_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\bMRN\s*[:#-]?\s*\d{4,}\b",
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        r"(?:DOB|date of birth|出生日期)\s*[:：]?\s*\d{1,4}[-/]\d{1,2}[-/]\d{1,4}\b",
        r"(?:身份证|身份证号)\s*[:：]?\s*[0-9X]{15,18}\b",
        r"(?:phone|telephone|mobile|电话|手机号)\s*[:：]?\s*\+?[0-9 ()-]{7,}\b",
    )
)


def _require_public_topics(topics: List[str] | None) -> None:
    for topic in topics or []:
        text = str(topic or "")
        if any(pattern.search(text) for pattern in _SENSITIVE_TOPIC_PATTERNS):
            raise ValueError(
                "research topics must be public biomedical concepts; possible PHI/direct identifier detected"
            )


_EVENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "paper_saved",
                "entity_queried",
                "suggestion_accepted",
                "suggestion_rejected",
                "workflow_observed",
                "recommendation_shown",
            ],
        },
        "topics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Canonical public biomedical concepts only; never a raw query or patient identifier.",
        },
        "task_type": {"type": "string"},
        "item_id": {"type": "string", "description": "Stable public PMID/DOI/NCT or local suggestion ID."},
        "occurred_at": {"type": "string", "description": "Optional ISO-8601 time; stored only as coarse aggregates."},
    },
    "required": ["kind"],
}


_CANDIDATE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema": {"type": "string"},
        "candidate_id": {"type": "string"},
        "kind": {"type": "string", "enum": ["paper", "preprint", "clinical_trial"]},
        "title": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
        "source": {"type": "string"},
        "published_at": {"type": "string"},
        "url": {"type": "string"},
        "evidence_score": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["candidate_id", "kind", "title", "topics"],
}


@server.tool(
    "research_interest_observe",
    "Update the local HMAC-pseudonymized interest model from one structured event. Raw prompts, "
    "titles, abstracts, notes, arbitrary metadata, and patient identifiers are outside this contract. "
    "Set consent=true only after the user explicitly opts in.",
    {
        "type": "object",
        "properties": {
            "event": _EVENT_SCHEMA,
            "consent": {
                "type": "boolean",
                "default": False,
                "description": "Per-event proof that the user explicitly enabled local learning.",
            },
        },
        "required": ["event", "consent"],
    },
)
def research_interest_observe(event: Dict[str, Any], consent: bool = False):
    _require_public_topics(event.get("topics") if isinstance(event, dict) else None)
    return research_interest.record_research_event(event, consent=bool(consent))


@server.tool(
    "research_interest_inspect",
    "Inspect the local aggregate model without exposing stored HMAC tokens. In default HMAC mode, "
    "supply a local catalog of canonical project/KG concepts to recover readable matches.",
    {
        "type": "object",
        "properties": {
            "topic_catalog": {"type": "array", "items": {"type": "string"}},
        },
    },
)
def research_interest_inspect(topic_catalog: List[str] | None = None):
    _require_public_topics(topic_catalog)
    result = research_interest.inspect_research_profile(topic_catalog=topic_catalog)
    result["consent_scope"] = "per_event_fail_closed"
    return result


@server.tool(
    "research_interest_delete",
    "Delete the local aggregate interest profile and its separate HMAC key. This is irreversible "
    "and requires confirm=true.",
    {
        "type": "object",
        "properties": {"confirm": {"type": "boolean", "default": False}},
        "required": ["confirm"],
    },
)
def research_interest_delete(confirm: bool = False):
    return research_interest.delete_research_profile(confirm=bool(confirm))


@server.tool(
    "research_updates_rank",
    "Rank structured paper, preprint, and trial candidates locally using learned interests, "
    "recency, evidence score, source diversity, negative feedback, and a seen-item cooldown. "
    "Candidate content is not persisted.",
    {
        "type": "object",
        "properties": {
            "candidates": {"type": "array", "items": _CANDIDATE_SCHEMA},
            "limit": {"type": "integer", "default": 10, "minimum": 0, "maximum": 100},
            "cooldown_days": {"type": "integer", "default": 14, "minimum": 0},
            "include_seen": {"type": "boolean", "default": False},
        },
        "required": ["candidates"],
    },
)
def research_updates_rank(
    candidates: List[Dict[str, Any]],
    limit: int = 10,
    cooldown_days: int = 14,
    include_seen: bool = False,
):
    return proactive_research.rank_research_updates(
        candidates,
        limit=limit,
        cooldown_days=cooldown_days,
        include_seen=include_seen,
    )


@server.tool(
    "research_refresh_plan",
    "Create a personalized PubMed, bioRxiv, medRxiv, and ClinicalTrials.gov watch plan from "
    "locally matched concepts and workflow timing. It never performs network calls. Remote actions "
    "remain requires_consent unless allow_remote_queries=true is explicitly authorized.",
    {
        "type": "object",
        "properties": {
            "topic_catalog": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Canonical public concepts already available locally from saved items, a project, or the KG.",
            },
            "allow_remote_queries": {"type": "boolean", "default": False},
            "max_topics": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
        },
        "required": ["topic_catalog"],
    },
)
def research_refresh_plan(
    topic_catalog: List[str],
    allow_remote_queries: bool = False,
    max_topics: int = 5,
):
    _require_public_topics(topic_catalog)
    return proactive_research.build_proactive_refresh_plan(
        topic_catalog,
        allow_remote_queries=bool(allow_remote_queries),
        max_topics=max_topics,
    )


@server.tool(
    "research_session_brief",
    "Prepare a privacy-safe session-start briefing: learned interest summary, coarse workflow "
    "prediction, and consent-gated source refresh actions. No network call is made.",
    {
        "type": "object",
        "properties": {
            "topic_catalog": {"type": "array", "items": {"type": "string"}},
            "allow_remote_queries": {"type": "boolean", "default": False},
            "max_topics": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
        },
        "required": ["topic_catalog"],
    },
)
def research_session_brief(
    topic_catalog: List[str],
    allow_remote_queries: bool = False,
    max_topics: int = 5,
):
    _require_public_topics(topic_catalog)
    profile = research_interest.inspect_research_profile(topic_catalog=topic_catalog)
    if not profile.get("profile_exists"):
        return {
            "schema": "biocsswitch/research-session-brief/1",
            "status": "no_local_profile",
            "profile": profile,
            "refresh_plan": None,
            "network_performed": False,
        }
    plan = proactive_research.build_proactive_refresh_plan(
        topic_catalog,
        allow_remote_queries=bool(allow_remote_queries),
        max_topics=max_topics,
    )
    return {
        "schema": "biocsswitch/research-session-brief/1",
        "status": plan.get("status"),
        "profile": profile,
        "refresh_plan": plan,
        "network_performed": False,
        "next_step": "Execute only explicitly authorized refresh actions, then pass normalized candidates to research_updates_rank.",
    }


if __name__ == "__main__":
    server.run()
