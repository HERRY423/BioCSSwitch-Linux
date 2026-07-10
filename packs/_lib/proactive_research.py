"""Local proactive recommendation and refresh planning for BioCSSwitch.

The module consumes :mod:`packs._lib.research_interest` aggregates and
structured update candidates.  It is an offline planner: it neither performs
network requests nor invokes packs.  Its output names the existing bio-lit and
bio-trials tools so the proxy/MCP layer can dispatch only after applying user
consent, sensitive-mode, rate-limit, and notification policies.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

from .research_interest import (
    InterestModel,
    LocalInterestStore,
    PrivacySettings,
    _normalize_topics,
)


UPDATE_SCHEMA = "biocsswitch/research-update/1"
RECOMMENDATION_SCHEMA = "biocsswitch/research-recommendations/1"
REFRESH_PLAN_SCHEMA = "biocsswitch/proactive-refresh-plan/1"


class UpdateKind(str, Enum):
    PAPER = "paper"
    PREPRINT = "preprint"
    CLINICAL_TRIAL = "clinical_trial"


@dataclass(frozen=True)
class UpdateCandidate:
    """Ephemeral public update metadata used for local ranking.

    Candidate content is never written by this module.  ``candidate_id``
    should be a PMID, DOI, or NCT identifier; ``topics`` should be normalized
    genes, diseases, pathways, drugs, or cell types rather than an abstract.
    """

    candidate_id: str
    kind: UpdateKind | str
    title: str
    topics: Sequence[str] = field(default_factory=tuple)
    source: str = ""
    published_at: date | datetime | str | None = None
    url: str = ""
    evidence_score: float = 0.0

    def validated(self) -> "UpdateCandidate":
        identifier = str(self.candidate_id or "").strip()
        if not identifier or len(identifier) > 160:
            raise ValueError("candidate_id is required and must be <= 160 characters")
        try:
            kind = self.kind if isinstance(self.kind, UpdateKind) else UpdateKind(str(self.kind))
        except ValueError as exc:
            raise ValueError(f"unsupported update kind: {self.kind!r}") from exc
        title = " ".join(str(self.title or "").split())
        if not title or len(title) > 500:
            raise ValueError("candidate title is required and must be <= 500 characters")
        topics = tuple(_normalize_topics(self.topics))
        if not topics:
            raise ValueError("candidate requires at least one structured topic")
        source = " ".join(str(self.source or "").split())
        if len(source) > 80:
            raise ValueError("candidate source must be <= 80 characters")
        published = _parse_date(self.published_at)
        url = str(self.url or "").strip()
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("candidate url must be http(s)")
        evidence = float(self.evidence_score or 0.0)
        if not math.isfinite(evidence) or evidence < 0 or evidence > 1:
            raise ValueError("evidence_score must be between 0 and 1")
        return UpdateCandidate(
            candidate_id=identifier,
            kind=kind,
            title=title,
            topics=topics,
            source=source,
            published_at=published,
            url=url,
            evidence_score=evidence,
        )

    def item_key(self) -> str:
        # PMID/DOI/NCT identifiers are globally namespaced.  Using only that
        # identifier lets a paper saved from one source suppress the same work
        # when another source returns it later.
        return self.candidate_id


def _parse_date(value: date | datetime | str | None) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(raw)
            except ValueError as exc:
                raise ValueError("published_at must be ISO-8601") from exc
    raise TypeError("published_at must be a date, datetime, ISO string, or None")


def candidate_from_mapping(raw: Mapping[str, Any]) -> UpdateCandidate:
    """Parse and strictly validate the JSON candidate schema."""

    if not isinstance(raw, Mapping):
        raise TypeError("candidate must be an object")
    allowed = {
        "schema",
        "candidate_id",
        "kind",
        "title",
        "topics",
        "source",
        "published_at",
        "url",
        "evidence_score",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError("candidate contains unsupported fields: " + ", ".join(sorted(unknown)))
    schema = raw.get("schema")
    if schema not in (None, "", UPDATE_SCHEMA):
        raise ValueError(f"unsupported candidate schema: {schema!r}")
    return UpdateCandidate(
        candidate_id=str(raw.get("candidate_id") or ""),
        kind=str(raw.get("kind") or ""),
        title=str(raw.get("title") or ""),
        topics=raw.get("topics") or (),
        source=str(raw.get("source") or ""),
        published_at=raw.get("published_at"),
        url=str(raw.get("url") or ""),
        evidence_score=float(raw.get("evidence_score") or 0.0),
    ).validated()


class ProactivePlanner:
    """Rank updates and create consent-gated pack invocation plans."""

    def __init__(self, model: InterestModel):
        self.model = model

    def rank_updates(
        self,
        candidates: Iterable[UpdateCandidate],
        *,
        at: Optional[datetime] = None,
        limit: int = 10,
        cooldown_days: int = 14,
        include_seen: bool = False,
    ) -> Dict[str, Any]:
        now = _as_local_datetime(at)
        validated: List[UpdateCandidate] = []
        duplicate_count = 0
        seen_ids = set()
        for value in candidates:
            candidate = value.validated()
            identity = candidate.item_key().casefold()
            if identity in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(identity)
            validated.append(candidate)

        scored: List[Dict[str, Any]] = []
        suppressed_seen = 0
        suppressed_irrelevant = 0
        for candidate in validated:
            already_seen = self.model.was_seen(
                candidate.item_key(), at=now, cooldown_days=cooldown_days
            ) or self.model.was_seen(
                candidate.candidate_id, at=now, cooldown_days=cooldown_days
            )
            if not include_seen and already_seen:
                suppressed_seen += 1
                continue
            topic_rows = [
                (topic, self.model.topic_score(topic, now)) for topic in candidate.topics
            ]
            matched = [(topic, score) for topic, score in topic_rows if score > 0]
            raw_interest = sum(score for _topic, score in topic_rows)
            if not matched or raw_interest <= 0:
                suppressed_irrelevant += 1
                continue

            # sqrt normalization rewards multi-concept convergence without
            # allowing candidates with long keyword lists to dominate.
            interest_score = raw_interest / math.sqrt(len(topic_rows))
            recency_score = _recency_score(candidate.published_at, now.date())
            evidence_bonus = 0.25 * candidate.evidence_score
            base_score = interest_score + 0.6 * recency_score + evidence_bonus
            scored.append(
                {
                    "candidate": candidate,
                    "base_score": base_score,
                    "interest_score": interest_score,
                    "recency_score": recency_score,
                    "matched": sorted(matched, key=lambda item: (-item[1], item[0])),
                }
            )

        # Greedy re-ranking gives the feed modest source/kind diversity while
        # preserving the learned relevance ordering.
        selected: List[Dict[str, Any]] = []
        remaining = list(scored)
        kind_counts: Dict[str, int] = {}
        source_counts: Dict[str, int] = {}
        cap = max(0, min(int(limit), 100))
        while remaining and len(selected) < cap:
            def adjusted(row: Dict[str, Any]) -> float:
                candidate = row["candidate"]
                kind = candidate.kind.value
                source = candidate.source.casefold()
                return (
                    float(row["base_score"])
                    - 0.12 * kind_counts.get(kind, 0)
                    - 0.06 * source_counts.get(source, 0)
                )

            best = max(
                remaining,
                key=lambda row: (
                    adjusted(row),
                    str(row["candidate"].published_at or ""),
                    row["candidate"].candidate_id,
                ),
            )
            remaining.remove(best)
            candidate = best["candidate"]
            kind_counts[candidate.kind.value] = kind_counts.get(candidate.kind.value, 0) + 1
            source_key = candidate.source.casefold()
            source_counts[source_key] = source_counts.get(source_key, 0) + 1
            selected.append(
                {
                    "schema": UPDATE_SCHEMA,
                    "candidate_id": candidate.candidate_id,
                    "item_key": candidate.item_key(),
                    "kind": candidate.kind.value,
                    "title": candidate.title,
                    "topics": list(candidate.topics),
                    "source": candidate.source,
                    "published_at": (
                        candidate.published_at.isoformat() if candidate.published_at else None
                    ),
                    "url": candidate.url or None,
                    "score": round(adjusted(best), 6),
                    "reason": {
                        "matched_topics": [topic for topic, _score in best["matched"][:5]],
                        "interest_score": round(float(best["interest_score"]), 6),
                        "recency_score": round(float(best["recency_score"]), 6),
                        "evidence_score": candidate.evidence_score,
                    },
                }
            )

        return {
            "schema": RECOMMENDATION_SCHEMA,
            "recommendations": selected,
            "count": len(selected),
            "diagnostics": {
                "input_candidates": len(validated) + duplicate_count,
                "duplicates_removed": duplicate_count,
                "seen_suppressed": suppressed_seen,
                "irrelevant_suppressed": suppressed_irrelevant,
            },
            "privacy": {
                "ranking_location": "local",
                "candidate_content_persisted": False,
                "raw_events_used": False,
            },
        }

    def build_refresh_plan(
        self,
        topic_catalog: Iterable[str],
        *,
        at: Optional[datetime] = None,
        allow_remote_queries: bool = False,
        max_topics: int = 5,
    ) -> Dict[str, Any]:
        """Create watch queries for existing packs without executing them.

        Default HMAC profiles cannot be reversed.  ``topic_catalog`` therefore
        comes from local saved-paper/KG/project concepts, is matched locally,
        and yields the labels used in these watch queries.  Remote dispatch is
        marked ready only when the caller supplies an explicit policy decision
        via ``allow_remote_queries=True``.
        """

        now = _as_local_datetime(at)
        interests = self.model.top_interests(
            topic_catalog, at=now, limit=max(1, min(int(max_topics), 20))
        )
        workflow = self.model.predict_workflow(now, limit=3)
        predicted_task = workflow[0]["task_type"] if workflow else ""
        topics = [row["topic"] for row in interests]
        if not topics:
            return {
                "schema": REFRESH_PLAN_SCHEMA,
                "status": "insufficient_local_context",
                "actions": [],
                "interests": [],
                "workflow_prediction": workflow,
                "privacy": {
                    "reason": "HMAC interests need a matching local topic catalog",
                    "network_performed": False,
                },
            }

        query = " OR ".join(_quote_query_topic(topic) for topic in topics)
        recent_date = (now.date() - timedelta(days=90)).isoformat()
        dispatch_state = "ready" if allow_remote_queries else "requires_consent"
        actions = [
            {
                "id": "pubmed-recent",
                "pack": "bio-lit",
                "server": "bio-lit-pubmed",
                "tool": "pubmed_search",
                "arguments": {
                    "query": query,
                    "mindate": recent_date,
                    "sort": "pub_date",
                    "retmax": 50,
                },
                "update_kind": "paper",
            },
            {
                "id": "biorxiv-recent",
                "pack": "bio-lit",
                "server": "bio-lit-preprint",
                "tool": "preprint_search",
                "arguments": {
                    "source": "biorxiv",
                    "query": query,
                    "from_year": now.year - 1,
                    "until_year": now.year,
                    "pageSize": 50,
                },
                "update_kind": "preprint",
            },
            {
                "id": "medrxiv-recent",
                "pack": "bio-lit",
                "server": "bio-lit-preprint",
                "tool": "preprint_search",
                "arguments": {
                    "source": "medrxiv",
                    "query": query,
                    "from_year": now.year - 1,
                    "until_year": now.year,
                    "pageSize": 50,
                },
                "update_kind": "preprint",
            },
            {
                "id": "clinicaltrials-active",
                "pack": "bio-trials",
                "server": "bio-trials-ctgov",
                "tool": "ctgov_search",
                "arguments": {
                    "term": query,
                    "status": "RECRUITING|NOT_YET_RECRUITING|ACTIVE_NOT_RECRUITING",
                    "pageSize": 50,
                },
                "update_kind": "clinical_trial",
            },
        ]
        priorities = _action_priorities(predicted_task)
        for action in actions:
            action["dispatch"] = dispatch_state
            action["requires_network"] = True
            action["priority"] = priorities.get(action["update_kind"], 2)
        actions.sort(key=lambda action: (action["priority"], action["id"]))
        return {
            "schema": REFRESH_PLAN_SCHEMA,
            "status": "ready" if allow_remote_queries else "awaiting_network_consent",
            "actions": actions,
            "interests": interests,
            "workflow_prediction": workflow,
            "privacy": {
                "network_performed": False,
                "remote_queries_allowed_by_caller": bool(allow_remote_queries),
                "topic_resolution": "local_catalog_hmac_match",
                "sensitive_mode_must_still_be_enforced_by_proxy": True,
            },
        }


def _as_local_datetime(value: Optional[datetime]) -> datetime:
    value = value or datetime.now().astimezone()
    if value.tzinfo is None:
        return value.astimezone()
    return value.astimezone()


def _recency_score(published: Optional[date], today: date) -> float:
    if published is None:
        return 0.0
    age = max(0, (today - published).days)
    return math.pow(0.5, age / 30.0)


def _quote_query_topic(topic: str) -> str:
    # Topics are already bounded and control-character free. Escaping quotes
    # keeps the generated query valid for PubMed/Europe PMC/free-text tools.
    return '"' + topic.replace('"', '\\"') + '"'


def _action_priorities(task_type: str) -> Dict[str, int]:
    if task_type == "clinical-trials":
        return {"clinical_trial": 0, "paper": 1, "preprint": 2}
    if task_type == "lit-review":
        return {"paper": 0, "preprint": 1, "clinical_trial": 2}
    if task_type == "target-discovery":
        return {"paper": 0, "clinical_trial": 1, "preprint": 2}
    return {"paper": 0, "preprint": 1, "clinical_trial": 1}


def rank_research_updates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    profile_path: str | os.PathLike[str] | None = None,
    settings: Optional[PrivacySettings] = None,
    limit: int = 10,
    cooldown_days: int = 14,
    include_seen: bool = False,
) -> Dict[str, Any]:
    """JSON-friendly MCP integration function for local candidate ranking."""

    model = LocalInterestStore(profile_path, consent=False, settings=settings).model()
    return ProactivePlanner(model).rank_updates(
        [candidate_from_mapping(value) for value in candidates],
        limit=limit,
        cooldown_days=cooldown_days,
        include_seen=include_seen,
    )


def build_proactive_refresh_plan(
    topic_catalog: Iterable[str],
    *,
    profile_path: str | os.PathLike[str] | None = None,
    settings: Optional[PrivacySettings] = None,
    allow_remote_queries: bool = False,
    max_topics: int = 5,
) -> Dict[str, Any]:
    """JSON-friendly MCP integration function for consent-gated watch plans."""

    model = LocalInterestStore(profile_path, consent=False, settings=settings).model()
    return ProactivePlanner(model).build_refresh_plan(
        topic_catalog,
        allow_remote_queries=allow_remote_queries,
        max_topics=max_topics,
    )
