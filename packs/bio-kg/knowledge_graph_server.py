#!/usr/bin/env python3
"""Living biomedical causal knowledge graph MCP server."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import causal_kg, contradiction_hypotheses  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-kg", "0.1.0")


def _path(graph_path: Optional[str] = None) -> str:
    return graph_path or causal_kg.default_graph_path(os.environ)


@server.tool(
    "kg_extract_triples",
    "Extract biomedical causal triples from text into the BioCSSwitch local KG schema. "
    "This is a deterministic regex/heuristic extractor for offline use; for production curation, "
    "feed these candidate triples back through a model constrained by JSON Schema and evidence snippets.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "context": {"type": "string", "description": "Disease, tissue, model, or experimental context."},
            "source": {"type": "string", "default": "manual"},
            "persist": {"type": "boolean", "default": False},
            "graph_path": {"type": "string"},
        },
        "required": ["text"],
    },
)
def kg_extract_triples(
    text: str,
    context: str = "",
    source: str = "manual",
    persist: bool = False,
    graph_path: Optional[str] = None,
):
    triples = causal_kg.extract_triples(text=text, context=context, source=source)
    write = {"written": 0, "path": _path(graph_path)}
    if persist and triples:
        write = causal_kg.append_triples(_path(graph_path), triples)
    return {
        "schema": "bio-kg/causal-triples/1",
        "triples": triples,
        "count": len(triples),
        "persisted": write,
        "extractor_note": "Candidate extraction only; absence of a triple is not evidence of absence.",
    }


@server.tool(
    "kg_add_triples",
    "Persist curated causal triples to the local BioCSSwitch knowledge graph JSONL store.",
    {
        "type": "object",
        "properties": {
            "triples": {"type": "array", "items": {"type": "object"}},
            "graph_path": {"type": "string"},
            "source": {"type": "string", "default": "manual-curation"},
        },
        "required": ["triples"],
    },
)
def kg_add_triples(
    triples: List[Dict[str, Any]],
    graph_path: Optional[str] = None,
    source: str = "manual-curation",
):
    normalized = []
    for triple in triples or []:
        t = dict(triple)
        t.setdefault("source", source)
        norm = causal_kg.normalize_triple(t, source=source)
        if norm:
            normalized.append(norm)
    write = causal_kg.append_triples(_path(graph_path), normalized)
    return {
        "schema": "bio-kg/write-result/1",
        "path": write["path"],
        "written": write["written"],
        "triples": normalized,
    }


@server.tool(
    "kg_query",
    "Query the local causal KG by subject, object, relation, and/or context.",
    {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "object": {"type": "string"},
            "relation": {"type": "string"},
            "context": {"type": "string"},
            "graph_path": {"type": "string"},
            "triples": {"type": "array", "items": {"type": "object"}},
            "limit": {"type": "integer", "default": 50},
        },
    },
)
def kg_query(
    subject: str = "",
    object: str = "",
    relation: str = "",
    context: str = "",
    graph_path: Optional[str] = None,
    triples: Optional[List[Dict[str, Any]]] = None,
    limit: int = 50,
):
    rows = causal_kg.load_triples(graph_path, triples)
    matches = causal_kg.query_triples(rows, subject=subject, obj=object, relation=relation, context=context)
    limit = max(1, min(int(limit), 500))
    return {
        "schema": "bio-kg/query-result/1",
        "summary": causal_kg.summarize_graph(rows),
        "matches": matches[:limit],
        "truncated": len(matches) > limit,
    }


@server.tool(
    "kg_conflict_scan",
    "Detect causal-direction conflicts in the local KG, such as MYC upregulates CCND1 vs MYC downregulates CCND1 in a similar context.",
    {
        "type": "object",
        "properties": {
            "triple": {"type": "object", "description": "Optional candidate triple to compare against stored triples."},
            "graph_path": {"type": "string"},
            "triples": {"type": "array", "items": {"type": "object"}},
            "min_context_similarity": {"type": "number", "default": 0.2},
        },
    },
)
def kg_conflict_scan(
    triple: Optional[Dict[str, Any]] = None,
    graph_path: Optional[str] = None,
    triples: Optional[List[Dict[str, Any]]] = None,
    min_context_similarity: float = 0.2,
):
    rows = causal_kg.load_triples(graph_path, triples)
    conflicts = causal_kg.find_conflicts(
        rows,
        candidate=triple,
        min_context_similarity=max(0.0, min(float(min_context_similarity), 1.0)),
    )
    return {
        "schema": "bio-kg/conflict-scan/1",
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "review_required": bool(conflicts),
    }


@server.tool(
    "kg_generate_hypotheses",
    "Turn opposite-direction causal KG edges into auditable rival hypotheses, falsifiable predictions, "
    "discriminating experiments, critical data needs, evidence provenance, and explicit uncertainty. "
    "Accepts either kg_conflict_scan output or triples/a local graph. Generated mechanisms are always "
    "marked untested and are never persisted as evidence.",
    {
        "type": "object",
        "properties": {
            "conflicts": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Optional conflicts array returned by kg_conflict_scan. When supplied, triples/graph_path are not scanned.",
            },
            "triples": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Optional curated causal triples to scan when conflicts is omitted.",
            },
            "graph_path": {"type": "string", "description": "Optional local KG JSON/JSONL path to scan when conflicts is omitted."},
            "focus_entity": {"type": "string", "description": "Limit scanned triples to conflicts touching this entity."},
            "context": {"type": "string", "description": "Limit scanned triples to records containing this context string."},
            "min_context_similarity": {"type": "number", "default": 0.2},
            "research_context": {
                "type": "object",
                "description": "User-supplied disease, tissue, population, or decision context. Preserved as context, not treated as evidence.",
            },
            "experiment_constraints": {
                "type": "object",
                "description": "Budget, timeline, available models/assays, ethics, or feasibility constraints passed to bio-experiment handoffs.",
            },
            "max_conflicts": {"type": "integer", "default": 10},
            "max_hypotheses_per_conflict": {"type": "integer", "minimum": 2, "maximum": 5, "default": 5},
        },
    },
)
def kg_generate_hypotheses(
    conflicts: Optional[List[Dict[str, Any]]] = None,
    triples: Optional[List[Dict[str, Any]]] = None,
    graph_path: Optional[str] = None,
    focus_entity: str = "",
    context: str = "",
    min_context_similarity: float = 0.2,
    research_context: Optional[Dict[str, Any]] = None,
    experiment_constraints: Optional[Dict[str, Any]] = None,
    max_conflicts: int = 10,
    max_hypotheses_per_conflict: int = 5,
):
    """Bridge KG conflicts to hypothesis and experiment planning records."""

    rows: List[Dict[str, Any]] = []
    if conflicts is None:
        rows = causal_kg.load_triples(graph_path, triples)
        if focus_entity:
            focus = causal_kg.query_triples(rows, subject=focus_entity) + causal_kg.query_triples(rows, obj=focus_entity)
            rows = list({row["id"]: row for row in focus}.values())
        if context:
            token = context.strip().lower()
            rows = [row for row in rows if token in str(row.get("context") or "").lower()]
        source_conflicts = causal_kg.find_conflicts(
            rows,
            min_context_similarity=max(0.0, min(float(min_context_similarity), 1.0)),
        )
        input_mode = "kg_or_triples_scan"
    else:
        source_conflicts = conflicts
        input_mode = "supplied_conflict_records"

    result = contradiction_hypotheses.generate_hypotheses(
        source_conflicts,
        research_context=research_context,
        experiment_constraints=experiment_constraints,
        max_hypotheses_per_conflict=max_hypotheses_per_conflict,
        max_conflicts=max_conflicts,
    )
    result["input"] = {
        "mode": input_mode,
        "scanned_graph_summary": causal_kg.summarize_graph(rows) if conflicts is None else None,
        "focus_entity": focus_entity,
        "context_filter": context,
        "min_context_similarity": max(0.0, min(float(min_context_similarity), 1.0)),
        "persistence": "none; generated hypotheses are not KG evidence",
    }
    return result


@server.tool(
    "kg_causal_paths",
    "Find multi-step causal paths between two entities in the local KG.",
    {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "target": {"type": "string"},
            "max_depth": {"type": "integer", "default": 4},
            "graph_path": {"type": "string"},
            "triples": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["source", "target"],
    },
)
def kg_causal_paths(
    source: str,
    target: str,
    max_depth: int = 4,
    graph_path: Optional[str] = None,
    triples: Optional[List[Dict[str, Any]]] = None,
):
    rows = causal_kg.load_triples(graph_path, triples)
    paths = causal_kg.causal_paths(rows, source=source, target=target, max_depth=max_depth)
    return {
        "schema": "bio-kg/causal-paths/1",
        "paths": paths,
        "path_count": len(paths),
        "interpretation_warning": "Paths are hypotheses over stored edges; they do not prove transitive biological causality.",
    }


@server.tool(
    "kg_gap_analysis",
    "Identify knowledge gaps in stored causal edges: missing direct-binding evidence, missing perturbation causality, missing citations, or low extraction confidence.",
    {
        "type": "object",
        "properties": {
            "focus_entity": {"type": "string"},
            "context": {"type": "string"},
            "graph_path": {"type": "string"},
            "triples": {"type": "array", "items": {"type": "object"}},
        },
    },
)
def kg_gap_analysis(
    focus_entity: str = "",
    context: str = "",
    graph_path: Optional[str] = None,
    triples: Optional[List[Dict[str, Any]]] = None,
):
    rows = causal_kg.load_triples(graph_path, triples)
    gaps = causal_kg.gap_analysis(rows, focus_entity=focus_entity, context=context)
    return {
        "schema": "bio-kg/gap-analysis/1",
        "summary": causal_kg.summarize_graph(rows),
        "gaps": gaps,
        "next_hypotheses": [
            {
                "from_gap": g["gap"],
                "edge_id": g["edge_id"],
                "hypothesis_prompt": "Design the minimal experiment that would close this evidence gap.",
            }
            for g in gaps[:10]
        ],
    }


if __name__ == "__main__":
    server.run()
