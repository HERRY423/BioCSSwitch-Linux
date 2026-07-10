"""Cross-modal biomedical orchestration primitives.

This module connects the existing BioCSSwitch packs without making them depend
on one another at import time.  It is deliberately stdlib-only and contains no
network code.  A host can:

1. build a dependency-aware plan with :func:`plan_unmet_need`;
2. execute it with its own MCP callback via :func:`orchestrate`;
3. incrementally reduce tool results into one serializable evidence context;
4. cross-validate claims and rank candidate targets.

The evidence model makes an important distinction between an *observation* and
an *analysis recipe*.  The single-cell and spatial packs currently generate
reproducible workflows; creating one of those workflows is not biological
support for a target.  Recipe records are therefore retained for provenance but
are excluded from support scores until measured results are ingested.

No state is persisted by this module.  Callers that choose to persist a context
should apply their normal local privacy and retention policy.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


CONTEXT_SCHEMA = "bio-crossmodal/evidence-context/1"
PLAN_SCHEMA = "bio-crossmodal/orchestration-plan/1"
VALIDATION_SCHEMA = "bio-crossmodal/cross-validation/1"
RANKING_SCHEMA = "bio-crossmodal/target-ranking/1"

MODALITIES: Tuple[str, ...] = (
    "literature",
    "gene",
    "drug",
    "trials",
    "single_cell",
    "spatial",
)

PACK_MODALITY: Dict[str, str] = {
    "bio-lit": "literature",
    "bio-gene": "gene",
    "bio-drug": "drug",
    "bio-trials": "trials",
    "bio-singlecell": "single_cell",
    "bio-spatial": "spatial",
}

DEFAULT_WEIGHTS: Dict[str, float] = {
    "biological_basis": 0.30,
    "druggability": 0.20,
    "translational_specificity": 0.15,
    "clinical_novelty": 0.15,
    "evidence_diversity": 0.10,
    "evidence_quality": 0.10,
}

_EFFECTS = {"supports", "contradicts", "neutral"}
_NON_EVIDENTIARY_CLAIMS = {"validation_recipe", "analysis_recipe", "data_inventory"}
_CLAIM_FAMILIES = {
    "disease_association": "target_disease_association",
    "disease_literature_support": "target_disease_association",
    "target_disease_association": "target_disease_association",
}
_MAX_RECORDS = 10_000
_MAX_CANDIDATES = 500
_MAX_ARTIFACTS = 10_000
_MAX_TARGETS_PER_RUN = 100
_MISSING = object()


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    if not math.isfinite(number):
        number = low
    return max(low, min(high, number))


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _content_hash(value: Any, prefix: str = "sha256") -> str:
    digest = hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _short_id(prefix: str, value: Any, length: int = 16) -> str:
    return f"{prefix}_{_content_hash(value).split(':', 1)[1][:length]}"


def _canonical_target(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip())
    if not text:
        return ""
    # HGNC symbols are case-insensitive in this orchestration layer.  Stable
    # external identifiers (ENSG/CHEMBL/etc.) are also conventionally upper-case.
    return text.upper()[:80]


def _canonical_disease(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()[:500]


def _claim_family(value: Any) -> str:
    claim = str(value or "observation").strip().lower()[:100] or "observation"
    return _CLAIM_FAMILIES.get(claim, claim)


def _canonical_source_id(value: Any) -> str:
    """Normalize globally meaningful evidence identifiers across tool surfaces."""
    raw = str(value or "").strip().strip(".,; ")
    if not raw:
        return ""
    low = raw.lower()
    if "doi.org/" in low:
        raw = raw[low.index("doi.org/") + len("doi.org/") :]
        low = raw.lower()
    doi = re.search(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", raw, re.I)
    if doi:
        return "DOI:" + doi.group(0).rstrip(".,;)").lower()
    pmid = re.fullmatch(r"(?:pmid\s*[:#]?\s*)?(\d{4,10})", raw, re.I)
    if pmid and re.match(r"(?i)^pmid", raw):
        return "PMID:" + pmid.group(1)
    nct = re.search(r"\bNCT\d{8}\b", raw, re.I)
    if nct:
        return "NCT:" + nct.group(0).upper()
    pmc = re.search(r"\bPMC\d+\b", raw, re.I)
    if pmc:
        return "PMC:" + pmc.group(0).upper()
    ensembl = re.search(r"\bENS[A-Z]*G\d+(?:\.\d+)?\b", raw, re.I)
    if ensembl:
        return "ENSEMBL:" + ensembl.group(0).split(".", 1)[0].upper()
    chembl = re.search(r"\bCHEMBL\d+\b", raw, re.I)
    if chembl:
        return "CHEMBL:" + chembl.group(0).upper()
    prefixed = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]{1,30})\s*:\s*(.+)", raw)
    if prefixed:
        prefix, identifier = prefixed.groups()
        prefix = prefix.upper()
        if prefix == "PMID" and identifier.isdigit():
            return f"PMID:{identifier}"
        return f"{prefix}:{identifier.strip()}"[:500]
    return raw[:500]


def _canonical_source_ids(value: Any, limit: int = 200) -> List[str]:
    out: List[str] = []
    for item in _as_string_list(value, limit):
        identifier = _canonical_source_id(item)
        if identifier and identifier not in out:
            out.append(identifier)
    return sorted(out)


def _target_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError("max_targets must be an integer") from None
    if parsed < 1:
        raise ValueError("max_targets must be at least 1")
    return min(parsed, _MAX_TARGETS_PER_RUN)


def _as_string_list(value: Any, limit: int = 100) -> List[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    out: List[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text[:500])
        if len(out) >= limit:
            break
    return out


def _safe_count(value: Any, fallback: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, int(fallback))


def _count_strength(count: int, half_saturation: float = 8.0) -> float:
    """Convert a hit count to a bounded, deliberately conservative signal."""
    count = max(0, int(count))
    if count == 0:
        return 0.0
    return round(count / (count + max(1.0, half_saturation)), 4)


@dataclass(frozen=True)
class UnmetNeed:
    disease: str
    unmet_need: str
    population: str = ""
    tissue: str = ""
    organism: str = "human"
    current_therapies: Tuple[str, ...] = ()
    seed_targets: Tuple[str, ...] = ()
    constraints: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any) -> "UnmetNeed":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("unmet need must be a mapping or UnmetNeed")
        disease = str(value.get("disease") or "").strip()
        unmet_need = str(value.get("unmet_need") or value.get("need") or "").strip()
        if not disease:
            raise ValueError("disease is required")
        if not unmet_need:
            raise ValueError("unmet_need is required")
        organism = str(value.get("organism") or "human").strip().lower()
        if organism not in {"human", "mouse"}:
            organism = "human"
        therapies = tuple(_as_string_list(value.get("current_therapies"), 50))
        targets = tuple(
            t for t in (_canonical_target(x) for x in _as_string_list(value.get("seed_targets"), 100)) if t
        )
        constraints = value.get("constraints") if isinstance(value.get("constraints"), Mapping) else {}
        return cls(
            disease=disease[:500],
            unmet_need=unmet_need[:1000],
            population=str(value.get("population") or "").strip()[:500],
            tissue=str(value.get("tissue") or "").strip()[:300],
            organism=organism,
            current_therapies=therapies,
            seed_targets=targets,
            constraints=dict(constraints),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "disease": self.disease,
            "unmet_need": self.unmet_need,
            "population": self.population,
            "tissue": self.tissue,
            "organism": self.organism,
            "current_therapies": list(self.current_therapies),
            "seed_targets": list(self.seed_targets),
            "constraints": dict(self.constraints),
        }

    @property
    def receipt(self) -> str:
        return _short_id("need", self.to_dict(), length=24)


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    stage: int
    pack: str
    server: str
    tool: str
    purpose: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    depends_on: Tuple[str, ...] = ()
    produces: Tuple[str, ...] = ()
    optional: bool = False
    foreach_target: bool = False
    evidence_role: str = "observation"
    kind: str = "tool"
    plan_id: str = ""
    need_receipt: str = ""
    step_receipt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "stage": self.stage,
            "kind": self.kind,
            "pack": self.pack,
            "server": self.server,
            "tool": self.tool,
            "purpose": self.purpose,
            "arguments": dict(self.arguments),
            "depends_on": list(self.depends_on),
            "produces": list(self.produces),
            "optional": self.optional,
            "foreach_target": self.foreach_target,
            "evidence_role": self.evidence_role,
            "plan_id": self.plan_id or None,
            "need_receipt": self.need_receipt or None,
            "step_receipt": self.step_receipt or None,
        }


@dataclass
class EvidenceRecord:
    modality: str
    source_pack: str
    source_tool: str
    claim_type: str
    target: str = ""
    disease: str = ""
    effect: str = "neutral"
    strength: float = 0.0
    quality: float = 0.5
    source_ids: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    payload_hash: str = ""
    evidence_id: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceRecord":
        modality = str(value.get("modality") or "").strip()
        if modality not in MODALITIES:
            raise ValueError(f"unsupported modality: {modality!r}")
        effect = str(value.get("effect") or "neutral").strip().lower()
        if effect not in _EFFECTS:
            raise ValueError(f"unsupported effect: {effect!r}")
        claim_type = str(value.get("claim_type") or "observation").strip()[:100]
        source_pack = str(value.get("source_pack") or "").strip()[:100]
        source_tool = str(value.get("source_tool") or "").strip()[:100]
        context = dict(value.get("context") or {}) if isinstance(value.get("context"), Mapping) else {}
        provenance = (
            dict(value.get("provenance") or {}) if isinstance(value.get("provenance"), Mapping) else {}
        )
        payload_hash = str(value.get("payload_hash") or "").strip()
        if not payload_hash and "payload" in value:
            payload_hash = _content_hash(value.get("payload"))
        raw_source_ids = _as_string_list(value.get("source_ids"), 200)
        if modality == "literature":
            raw_source_ids = [f"PMID:{item}" if item.isdigit() else item for item in raw_source_ids]
        source_ids = _canonical_source_ids(raw_source_ids, 200)
        record = cls(
            modality=modality,
            source_pack=source_pack,
            source_tool=source_tool,
            claim_type=claim_type or "observation",
            target=_canonical_target(value.get("target")),
            disease=str(value.get("disease") or "").strip()[:500],
            effect=effect,
            strength=_clamp(value.get("strength", value.get("confidence", 0.0))),
            quality=_clamp(value.get("quality", 0.5)),
            source_ids=source_ids,
            context=context,
            provenance=provenance,
            payload_hash=payload_hash,
            # Evidence IDs are always derived locally.  Accepting a caller's ID
            # would allow unrelated evidence to overwrite an existing record.
            evidence_id="",
        )
        record.evidence_id = _short_id("ev", record.identity_material())
        return record

    @property
    def confidence(self) -> float:
        return round(_clamp(self.strength) * _clamp(self.quality), 4)

    @property
    def is_evidentiary(self) -> bool:
        return self.claim_type not in _NON_EVIDENTIARY_CLAIMS

    @property
    def claim_family(self) -> str:
        return _claim_family(self.claim_type)

    def semantic_material(self) -> Dict[str, Any]:
        return {
            "claim_family": self.claim_family,
            "target": self.target,
            "disease": _canonical_disease(self.disease),
            "effect": self.effect,
            "context_key": {
                key: self.context.get(key)
                for key in ("population", "tissue", "cell_type", "model", "direction")
                if self.context.get(key) not in (None, "")
            },
        }

    def identity_material(self) -> Dict[str, Any]:
        material = self.semantic_material()
        if self.source_ids:
            # A PMID/DOI/NCT is global.  Do not make its identity depend on the
            # pack/tool through which it happened to be observed.
            material["source_ids"] = sorted(self.source_ids)
        else:
            material.update(
                {
                    "modality": self.modality,
                    "source_pack": self.source_pack,
                    "source_tool": self.source_tool,
                    "payload_hash": self.payload_hash,
                }
            )
        return material

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "modality": self.modality,
            "source_pack": self.source_pack,
            "source_tool": self.source_tool,
            "claim_type": self.claim_type,
            "claim_family": self.claim_family,
            "target": self.target or None,
            "disease": self.disease or None,
            "effect": self.effect,
            "strength": round(self.strength, 4),
            "quality": round(self.quality, 4),
            "confidence": self.confidence,
            "source_ids": list(self.source_ids),
            "context": dict(self.context),
            "provenance": dict(self.provenance),
            "payload_hash": self.payload_hash or None,
            "evidentiary": self.is_evidentiary,
        }


@dataclass
class EvidenceContext:
    need: UnmetNeed
    context_id: str = ""
    plan_id: str = ""
    records: Dict[str, EvidenceRecord] = field(default_factory=dict)
    candidates: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.context_id:
            self.context_id = _short_id("ctx", self.need.to_dict())
        for target in self.need.seed_targets:
            self.add_candidate(target, source="user_seed", seed_score=0.5)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceContext":
        if value.get("schema") not in (None, CONTEXT_SCHEMA):
            raise ValueError(f"unsupported context schema: {value.get('schema')!r}")
        need = UnmetNeed.from_value(value.get("need") or {})
        supplied_need_receipt = str(value.get("need_receipt") or "")
        if supplied_need_receipt and supplied_need_receipt != need.receipt:
            raise ValueError("context need_receipt does not match its unmet-need payload")
        expected_context_id = _short_id("ctx", need.to_dict())
        supplied_context_id = str(value.get("context_id") or "")
        if supplied_context_id and supplied_context_id != expected_context_id:
            raise ValueError("context_id does not match its unmet-need payload")
        supplied_plan_id = str(value.get("plan_id") or "")
        if supplied_plan_id and supplied_plan_id != plan_unmet_need(need)["plan_id"]:
            raise ValueError("context plan_id does not match its unmet-need plan")
        ctx = cls(
            need=need,
            context_id=expected_context_id,
            plan_id=supplied_plan_id[:100],
        )
        ctx.candidates = {}
        raw_candidates = value.get("candidates") or []
        raw_records = value.get("records") or []
        raw_artifacts = value.get("artifacts") or []
        if not isinstance(raw_candidates, list) or len(raw_candidates) > _MAX_CANDIDATES:
            raise ValueError(f"serialized candidate limit exceeded ({_MAX_CANDIDATES})")
        if not isinstance(raw_records, list) or len(raw_records) > _MAX_RECORDS:
            raise ValueError(f"serialized evidence limit exceeded ({_MAX_RECORDS})")
        if not isinstance(raw_artifacts, list) or len(raw_artifacts) > _MAX_ARTIFACTS:
            raise ValueError(f"serialized artifact limit exceeded ({_MAX_ARTIFACTS})")
        for candidate in raw_candidates:
            if not isinstance(candidate, Mapping):
                continue
            symbol = _canonical_target(candidate.get("symbol") or candidate.get("target"))
            if not symbol:
                continue
            identifiers = _as_string_list(candidate.get("identifiers"), 50)
            sources = _as_string_list(candidate.get("sources"), 50) or ["deserialized_context"]
            ctx.add_candidate(symbol, source=sources[0], seed_score=candidate.get("seed_score", 0.0))
            row = ctx.candidates[symbol]
            row["identifiers"] = identifiers
            row["sources"] = sources
        for target in need.seed_targets:
            ctx.add_candidate(target, source="user_seed", seed_score=0.5)
        for record in raw_records:
            if isinstance(record, Mapping):
                ctx.add_record(EvidenceRecord.from_mapping(record))
        for artifact in raw_artifacts:
            if isinstance(artifact, Mapping):
                ctx.artifacts.append(
                    {
                        "step_id": str(artifact.get("step_id") or "")[:100],
                        "pack": str(artifact.get("pack") or "")[:100],
                        "tool": str(artifact.get("tool") or "")[:100],
                        "target": _canonical_target(artifact.get("target")) or None,
                        "result_hash": str(artifact.get("result_hash") or "")[:200],
                        "status": str(artifact.get("status") or "ok")[:40],
                    }
                )
        return ctx

    def add_candidate(
        self,
        target: Any,
        source: str = "observation",
        identifier: str = "",
        seed_score: float = 0.0,
    ) -> None:
        symbol = _canonical_target(target)
        if not symbol:
            return
        if symbol not in self.candidates and len(self.candidates) >= _MAX_CANDIDATES:
            raise ValueError(f"candidate target limit exceeded ({_MAX_CANDIDATES})")
        row = self.candidates.setdefault(
            symbol,
            {"symbol": symbol, "identifiers": [], "sources": [], "seed_score": 0.0},
        )
        if identifier and identifier not in row["identifiers"]:
            row["identifiers"].append(str(identifier)[:200])
        if source and source not in row["sources"]:
            row["sources"].append(str(source)[:100])
        row["seed_score"] = max(float(row.get("seed_score") or 0.0), _clamp(seed_score))

    def add_record(self, record: EvidenceRecord) -> None:
        if record.target:
            self.add_candidate(record.target, source=record.source_pack or record.source_tool)
        existing = self.records.get(record.evidence_id)
        overlap_key = ""
        if existing is None and record.source_ids:
            incoming_ids = set(record.source_ids)
            for key, candidate in self.records.items():
                if (
                    candidate.semantic_material() == record.semantic_material()
                    and incoming_ids.intersection(candidate.source_ids)
                ):
                    existing = candidate
                    overlap_key = key
                    break
        if existing is None and len(self.records) >= _MAX_RECORDS:
            raise ValueError(f"evidence record limit exceeded ({_MAX_RECORDS})")
        if existing is None:
            self.records[record.evidence_id] = record
            return

        # Merge globally identified evidence observed through multiple packs or
        # aliases.  It remains one independent source while retaining all paths.
        primary = record if record.confidence > existing.confidence else existing
        observed_via: List[Dict[str, str]] = []
        for item in (existing, record):
            prior = item.provenance.get("observed_via")
            if isinstance(prior, list):
                for via in prior:
                    if isinstance(via, Mapping):
                        cleaned = {str(k): str(v) for k, v in via.items() if v not in (None, "")}
                        if cleaned and cleaned not in observed_via:
                            observed_via.append(cleaned)
            via = {"source_pack": item.source_pack, "source_tool": item.source_tool}
            if via not in observed_via:
                observed_via.append(via)
        merged_mapping = primary.to_dict()
        merged_mapping["source_ids"] = sorted(set(existing.source_ids) | set(record.source_ids))
        merged_mapping["provenance"] = {**primary.provenance, "observed_via": observed_via[:50]}
        merged = EvidenceRecord.from_mapping(merged_mapping)
        old_key = overlap_key or existing.evidence_id
        self.records.pop(old_key, None)
        self.records[merged.evidence_id] = merged

    def add_artifact(
        self,
        step_id: str,
        pack: str,
        tool: str,
        result: Any,
        target: str = "",
        status: str = "ok",
    ) -> None:
        if len(self.artifacts) >= _MAX_ARTIFACTS:
            raise ValueError(f"artifact limit exceeded ({_MAX_ARTIFACTS})")
        self.artifacts.append(
            {
                "step_id": str(step_id)[:100],
                "pack": str(pack)[:100],
                "tool": str(tool)[:100],
                "target": _canonical_target(target) or None,
                "result_hash": _content_hash(result),
                "status": str(status)[:40],
            }
        )

    def target_symbols(self, limit: int = _MAX_TARGETS_PER_RUN) -> List[str]:
        rows = sorted(
            self.candidates.values(),
            key=lambda row: (-float(row.get("seed_score") or 0.0), row["symbol"]),
        )
        return [row["symbol"] for row in rows[: _target_limit(limit)]]

    def to_dict(self) -> Dict[str, Any]:
        candidates = sorted(self.candidates.values(), key=lambda row: row["symbol"])
        records = sorted(self.records.values(), key=lambda row: row.evidence_id)
        return {
            "schema": CONTEXT_SCHEMA,
            "context_id": self.context_id,
            "plan_id": self.plan_id or None,
            "need_receipt": self.need.receipt,
            "need": self.need.to_dict(),
            "candidates": [dict(row) for row in candidates],
            "records": [row.to_dict() for row in records],
            "artifacts": list(self.artifacts),
            "coverage": evidence_coverage(self),
            "privacy": {
                "persistence": "none_by_default",
                "artifact_payloads_retained": False,
                "note": "Only result hashes and normalized evidence are retained by this module.",
            },
        }


def new_evidence_context(need: Any, plan_id: str = "") -> Dict[str, Any]:
    """Create an empty, serializable context packet for an unmet clinical need."""
    return EvidenceContext(UnmetNeed.from_value(need), plan_id=str(plan_id or "")[:100]).to_dict()


def _plan_steps(need: UnmetNeed) -> List[PlanStep]:
    organism_id = "9606" if need.organism == "human" else "10090"
    orgn = "human" if need.organism == "human" else "mouse"
    tissue = need.tissue or "disease-relevant tissue"
    platform = str(need.constraints.get("spatial_platform") or "visium").lower()
    if platform not in {
        "visium", "visium_hd", "xenium", "cosmx", "merfish", "slide_seq",
        "stereo_seq", "dbit_seq", "geomx",
    }:
        platform = "visium"

    return [
        PlanStep(
            "resolve_disease",
            1,
            "bio-drug",
            "bio-drug-opentargets",
            "ot_search",
            "Resolve the disease to a stable Open Targets identifier.",
            {"query": need.disease, "entity": "disease"},
            produces=("disease_identifier",),
        ),
        PlanStep(
            "literature_landscape",
            1,
            "bio-lit",
            "bio-lit-pubmed",
            "pubmed_search",
            "Map established therapies, resistance mechanisms, and unmet-need literature.",
            {
                "query": f'({need.disease}) AND (treatment OR therapy OR resistance OR "unmet need")',
                "retmax": 40,
                "sort": "pub_date",
            },
            produces=("literature_landscape",),
        ),
        PlanStep(
            "preprint_landscape",
            1,
            "bio-lit",
            "bio-lit-europepmc",
            "europepmc_search",
            "Capture recent preprints separately from peer-reviewed evidence.",
            {
                "query": f"({need.disease}) AND (treatment OR resistance OR mechanism) AND SRC:PPR",
                "pageSize": 20,
                "resultType": "core",
            },
            produces=("preprint_landscape",),
            optional=True,
        ),
        PlanStep(
            "trial_landscape",
            1,
            "bio-trials",
            "bio-trials-ctgov",
            "ctgov_search",
            "Measure the active clinical-development landscape for the disease.",
            {
                "condition": need.disease,
                "status": "RECRUITING|NOT_YET_RECRUITING|ACTIVE_NOT_RECRUITING",
                "pageSize": 50,
            },
            produces=("trial_landscape",),
        ),
        PlanStep(
            "disease_target_seeds",
            2,
            "bio-drug",
            "bio-drug-opentargets",
            "ot_disease_associated_targets",
            "Seed targets from target-disease association evidence.",
            {"efo_id": "$outputs.resolve_disease.hits[0].id", "size": 50},
            depends_on=("resolve_disease",),
            produces=("candidate_targets", "gene_disease_associations"),
        ),
        PlanStep(
            "single_cell_dataset_inventory",
            2,
            "bio-gene",
            "bio-gene-ncbi",
            "geo_search",
            "Find disease-relevant single-cell datasets that can test cell-state specificity.",
            {
                "query": f'({need.disease}) AND ("single cell" OR "single-cell" OR scRNA-seq)',
                "retmax": 20,
            },
            produces=("single_cell_data_assets",),
            evidence_role="data_inventory",
            optional=True,
        ),
        PlanStep(
            "target_gene_identity",
            3,
            "bio-gene",
            "bio-gene-ncbi",
            "gene_search",
            "Verify each candidate symbol and organism before joining databases.",
            {"query": f"{{target}}[gene] AND {orgn}[orgn]", "retmax": 3},
            depends_on=("disease_target_seeds",),
            produces=("gene_identity",),
            foreach_target=True,
        ),
        PlanStep(
            "target_protein_annotation",
            3,
            "bio-gene",
            "bio-gene-uniprot",
            "uniprot_search",
            "Check reviewed protein annotations and target identity.",
            {"query": f"gene:{{target}} AND organism_id:{organism_id}", "size": 3, "reviewed_only": True},
            depends_on=("disease_target_seeds",),
            produces=("protein_annotation",),
            foreach_target=True,
            optional=True,
        ),
        PlanStep(
            "target_literature",
            3,
            "bio-lit",
            "bio-lit-pubmed",
            "pubmed_search",
            "Cross-check target-specific disease literature independently of Open Targets.",
            {
                "query": f"({need.disease}) AND ({{target}}[Title/Abstract])",
                "retmax": 25,
                "sort": "relevance",
            },
            depends_on=("disease_target_seeds",),
            produces=("target_literature_support",),
            foreach_target=True,
        ),
        PlanStep(
            "target_druggability",
            3,
            "bio-drug",
            "bio-drug-chembl",
            "chembl_target_search",
            "Look for tractable target classes, known compounds, and target identifiers.",
            {"query": "{target}", "limit": 10},
            depends_on=("disease_target_seeds",),
            produces=("druggability",),
            foreach_target=True,
        ),
        PlanStep(
            "target_trial_saturation",
            3,
            "bio-trials",
            "bio-trials-ctgov",
            "ctgov_search",
            "Estimate whether each target is already crowded in active disease trials.",
            {"condition": need.disease, "term": "{target}", "pageSize": 30},
            depends_on=("disease_target_seeds",),
            produces=("target_trial_activity",),
            foreach_target=True,
        ),
        PlanStep(
            "single_cell_validation_recipe",
            4,
            "bio-singlecell",
            "bio-singlecell",
            "sc_celltype_recipe",
            "Prepare cell-type annotation needed before target expression is interpreted.",
            {"method": "celltypist", "organism": need.organism, "tissue": tissue},
            depends_on=("single_cell_dataset_inventory",),
            produces=("single_cell_validation_recipe",),
            evidence_role="validation_recipe",
            optional=True,
        ),
        PlanStep(
            "spatial_reference_mapping_recipe",
            4,
            "bio-spatial",
            "bio-spatial",
            "spatial_deconvolution_recipe",
            "Prepare spatial reference mapping from scRNA-seq to disease tissue.",
            {
                "method": "auto",
                "platform": platform,
                "reference_modality": "scRNA-seq",
                "rare_cell_expected": True,
            },
            depends_on=("single_cell_validation_recipe",),
            produces=("spatial_mapping_recipe",),
            evidence_role="validation_recipe",
            optional=True,
        ),
        PlanStep(
            "spatial_target_validation_recipe",
            4,
            "bio-spatial",
            "bio-spatial",
            "spatial_rare_cell_recipe",
            "Design orthogonal spatial validation for top target-positive cell states.",
            {
                "rare_population": f"{need.disease} target-positive cell state",
                "marker_genes": "$context.candidate_target_symbols",
                "platform": platform,
                "validation_mode": "orthogonal",
            },
            depends_on=("target_gene_identity", "single_cell_validation_recipe"),
            produces=("spatial_target_validation_recipe",),
            evidence_role="validation_recipe",
            optional=True,
        ),
        PlanStep(
            "cross_validate_and_rank",
            5,
            "bio-crossmodal",
            "",
            "internal:cross_validate_and_rank",
            "Identify corroboration, conflicts, modality gaps, and rank targets without treating missing data as negative evidence.",
            {},
            depends_on=(
                "target_gene_identity",
                "target_literature",
                "target_druggability",
                "target_trial_saturation",
                "single_cell_validation_recipe",
                "spatial_target_validation_recipe",
            ),
            produces=("cross_validation", "target_ranking", "evidence_gaps"),
            kind="internal",
        ),
    ]


def plan_unmet_need(need: Any) -> Dict[str, Any]:
    """Return a dependency-aware plan spanning all six requested modalities."""
    parsed = UnmetNeed.from_value(need)
    steps = _plan_steps(parsed)
    known: set[str] = set()
    for step in sorted(steps, key=lambda item: (item.stage, item.step_id)):
        missing = [dep for dep in step.depends_on if dep not in {item.step_id for item in steps}]
        if missing:
            raise ValueError(f"unknown dependencies for {step.step_id}: {missing}")
        known.add(step.step_id)
    raw_steps = [step.to_dict() for step in steps]
    plan_material = {
        "need": parsed.to_dict(),
        "steps": [
            {key: value for key, value in row.items() if key not in {"plan_id", "need_receipt", "step_receipt"}}
            for row in raw_steps
        ],
    }
    plan_id = _short_id("xplan", plan_material)
    bound_steps: List[Dict[str, Any]] = []
    for row in raw_steps:
        bound = dict(row)
        bound["plan_id"] = plan_id
        bound["need_receipt"] = parsed.receipt
        receipt_material = {
            key: value
            for key, value in bound.items()
            if key != "step_receipt"
        }
        bound["step_receipt"] = _short_id("xstep", receipt_material, length=24)
        bound_steps.append(bound)
    return {
        "schema": PLAN_SCHEMA,
        "plan_id": plan_id,
        "need_receipt": parsed.receipt,
        "need": parsed.to_dict(),
        "required_packs": list(PACK_MODALITY),
        "modalities": list(MODALITIES),
        "steps": bound_steps,
        "execution_contract": {
            "shared_context_schema": CONTEXT_SCHEMA,
            "reference_syntax": {
                "$outputs.<step>.<path>": "Use an earlier tool result.",
                "$context.candidate_target_symbols": "Use the current candidate list.",
                "{target}": "Fan out once per current candidate target.",
            },
            "partial_failure": "continue_and_report_modality_gap",
            "recipes_are_evidence": False,
            "missing_evidence_semantics": "unknown_not_negative",
        },
    }


def _ensure_context(context: Any, need: Any = None) -> EvidenceContext:
    if isinstance(context, EvidenceContext):
        return context
    if isinstance(context, Mapping):
        if context.get("schema") == CONTEXT_SCHEMA or "records" in context:
            return EvidenceContext.from_dict(context)
        if need is None and "disease" in context:
            return EvidenceContext(UnmetNeed.from_value(context))
    if context is None and need is not None:
        return EvidenceContext(UnmetNeed.from_value(need))
    raise TypeError("expected an EvidenceContext or serialized evidence context")


def integrate_observations(context: Any, observations: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Add normalized observations to a context and return a new JSON packet.

    Input observations use the same fields as :class:`EvidenceRecord`.  No
    absence is converted to a contradiction; a contradiction must be explicit.
    """
    ctx = _ensure_context(context)
    for observation in observations or []:
        if not isinstance(observation, Mapping):
            raise TypeError("each observation must be a mapping")
        ctx.add_record(EvidenceRecord.from_mapping(observation))
    return ctx.to_dict()


def _step_value(step: Any, name: str, default: Any = "") -> Any:
    if isinstance(step, PlanStep):
        return getattr(step, name, default)
    if isinstance(step, Mapping):
        return step.get(name, default)
    return default


def _result_rows(result: Mapping[str, Any], *keys: str) -> List[Mapping[str, Any]]:
    for key in keys:
        value = result.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _tool_failure_message(result: Mapping[str, Any]) -> str:
    """Return a failure description without interpreting it as zero evidence."""

    status = str(result.get("status") or "").strip().lower()
    failure_statuses = {"error", "failed", "failure", "timeout", "timed_out", "cancelled"}
    failed = (
        result.get("error") not in (None, "", False)
        or status in failure_statuses
        or result.get("ok") is False
        or result.get("success") is False
    )
    if not failed:
        return ""
    detail = result.get("error") or result.get("message") or status or "tool reported failure"
    return str(detail)[:500]


def _validate_step_binding(ctx: EvidenceContext, step: Any) -> None:
    """Prevent a result from another plan/disease being reduced into this context."""

    if not ctx.plan_id:
        return
    plan_id = str(_step_value(step, "plan_id") or "")
    need_receipt = str(_step_value(step, "need_receipt") or "")
    step_receipt = str(_step_value(step, "step_receipt") or "")
    if plan_id != ctx.plan_id:
        raise ValueError("step plan_id does not match the evidence context")
    if need_receipt != ctx.need.receipt:
        raise ValueError("step need_receipt does not match the evidence context")
    if not step_receipt:
        raise ValueError("bound plan step is missing step_receipt")
    serialized = step.to_dict() if isinstance(step, PlanStep) else dict(step)
    serialized.pop("step_receipt", None)
    expected = _short_id("xstep", serialized, length=24)
    if step_receipt != expected:
        raise ValueError("step_receipt does not match the supplied step")


def _record_from_tool(
    ctx: EvidenceContext,
    step: Any,
    *,
    modality: str = "",
    claim_type: str,
    target: str = "",
    effect: str = "neutral",
    strength: float = 0.0,
    quality: float = 0.5,
    source_ids: Optional[Sequence[str]] = None,
    context: Optional[Mapping[str, Any]] = None,
    payload: Any = None,
) -> None:
    pack = str(_step_value(step, "pack"))
    modality = modality or PACK_MODALITY.get(pack, "")
    if not modality:
        return
    record = EvidenceRecord.from_mapping(
        {
            "modality": modality,
            "source_pack": pack,
            "source_tool": str(_step_value(step, "tool")),
            "claim_type": claim_type,
            "target": target,
            "disease": ctx.need.disease,
            "effect": effect,
            "strength": strength,
            "quality": quality,
            "source_ids": list(source_ids or []),
            "context": dict(context or {}),
            "provenance": {
                "context_id": ctx.context_id,
                "step_id": str(_step_value(step, "step_id")),
            },
            "payload_hash": _content_hash(payload) if payload is not None else "",
        }
    )
    ctx.add_record(record)


def _reduce_open_targets(ctx: EvidenceContext, step: Any, result: Mapping[str, Any]) -> None:
    rows = _result_rows(result, "rows")
    for row in rows:
        target_obj = row.get("target") if isinstance(row.get("target"), Mapping) else {}
        symbol = _canonical_target(target_obj.get("approvedSymbol") or target_obj.get("symbol"))
        target_id = str(target_obj.get("id") or "")
        if not symbol:
            continue
        score = _clamp(row.get("score"))
        ctx.add_candidate(symbol, source="Open Targets", identifier=target_id, seed_score=score)
        _record_from_tool(
            ctx,
            step,
            modality="gene",
            claim_type="disease_association",
            target=symbol,
            effect="supports",
            strength=score,
            quality=0.85,
            source_ids=[target_id] if target_id else [],
            context={"association_source": "Open Targets"},
            payload=row,
        )


def _reduce_search_result(ctx: EvidenceContext, step: Any, result: Mapping[str, Any], target: str) -> None:
    tool = str(_step_value(step, "tool"))
    rows = _result_rows(result, "results", "hits", "activities", "mechanisms")
    count = _safe_count(
        result.get("total", result.get("count", result.get("hit_count"))),
        fallback=len(rows),
    )
    effect = "supports" if count > 0 else "neutral"
    ids: List[str] = []
    ids.extend(_as_string_list(result.get("ids"), 50))
    for row in rows[:50]:
        for key in ("pmid", "doi", "id", "accession", "target_chembl_id", "nct_id"):
            if row.get(key):
                ids.append(str(row[key]))
                break

    if tool in {"pubmed_search", "europepmc_search"}:
        if target:
            _record_from_tool(
                ctx,
                step,
                claim_type="disease_literature_support",
                target=target,
                effect=effect,
                strength=_count_strength(count, 10),
                quality=0.60 if tool == "pubmed_search" else 0.45,
                source_ids=ids,
                context={"searched": True, "hit_count": count, "preprint": tool == "europepmc_search"},
                payload=result,
            )
        return

    if tool in {"gene_search", "uniprot_search"}:
        if target:
            _record_from_tool(
                ctx,
                step,
                claim_type="target_identity" if tool == "gene_search" else "protein_annotation",
                target=target,
                effect=effect,
                strength=0.75 if count > 0 else 0.0,
                quality=0.80 if tool == "gene_search" else 0.85,
                source_ids=ids,
                context={"searched": True, "hit_count": count},
                payload=result,
            )
        return

    if tool in {"chembl_target_search", "chembl_bioactivity", "chembl_mechanism", "ot_drug_details"}:
        if target:
            _record_from_tool(
                ctx,
                step,
                claim_type="druggability",
                target=target,
                effect=effect,
                strength=_count_strength(count, 3),
                quality=0.75,
                source_ids=ids,
                context={"searched": True, "hit_count": count},
                payload=result,
            )
        return

    if tool in {"ctgov_search", "ctgov_detail", "ctgov_by_sponsor"}:
        if target:
            _record_from_tool(
                ctx,
                step,
                claim_type="clinical_activity",
                target=target,
                effect=effect,
                strength=_count_strength(count, 4),
                quality=0.80,
                source_ids=ids,
                context={"searched": True, "trial_count": count},
                payload=result,
            )


def reduce_tool_result(
    context: Any,
    step: Any,
    result: Mapping[str, Any],
    target: str = "",
) -> Dict[str, Any]:
    """Reduce one pack result into the shared evidence context.

    A pack can return an ``observations`` list to bypass heuristic adapters and
    provide claim-level evidence directly.  Otherwise conservative adapters for
    current BioCSSwitch result shapes are used.
    """
    if not isinstance(result, Mapping):
        raise TypeError("tool result must be a mapping")
    ctx = _ensure_context(context)
    _validate_step_binding(ctx, step)
    step_id = str(_step_value(step, "step_id"))
    pack = str(_step_value(step, "pack"))
    tool = str(_step_value(step, "tool"))
    target = _canonical_target(target)
    failure = _tool_failure_message(result)
    if failure:
        raise RuntimeError(f"{tool or step_id or 'tool'} failed: {failure}")
    ctx.add_artifact(step_id, pack, tool, result, target=target)

    observations = result.get("observations")
    used_normalized_observations = isinstance(observations, list)
    if isinstance(observations, list):
        for observation in observations:
            if not isinstance(observation, Mapping):
                continue
            enriched = dict(observation)
            enriched.setdefault("source_pack", pack)
            enriched.setdefault("source_tool", tool)
            enriched.setdefault("modality", PACK_MODALITY.get(pack))
            enriched.setdefault("disease", ctx.need.disease)
            if target:
                enriched.setdefault("target", target)
            ctx.add_record(EvidenceRecord.from_mapping(enriched))

    if used_normalized_observations:
        pass
    elif tool == "ot_disease_associated_targets":
        _reduce_open_targets(ctx, step, result)
    elif tool in {
        "pubmed_search",
        "europepmc_search",
        "gene_search",
        "uniprot_search",
        "chembl_target_search",
        "chembl_bioactivity",
        "chembl_mechanism",
        "ot_drug_details",
        "ctgov_search",
        "ctgov_detail",
        "ctgov_by_sponsor",
    }:
        _reduce_search_result(ctx, step, result, target)

    evidence_role = str(_step_value(step, "evidence_role", "observation"))
    if evidence_role in {"validation_recipe", "analysis_recipe", "data_inventory"}:
        claim_type = evidence_role
        targets = [target] if target else []
        if not targets and tool == "spatial_rare_cell_recipe":
            params = result.get("params") if isinstance(result.get("params"), Mapping) else {}
            targets = [_canonical_target(x) for x in _as_string_list(params.get("marker_genes"), 100)]
            targets = [x for x in targets if x]
        if not targets:
            # A target-free recipe is still useful provenance but must not create
            # a candidate target or a support score.
            _record_from_tool(
                ctx,
                step,
                claim_type=claim_type,
                effect="neutral",
                strength=0.0,
                quality=1.0,
                context={"recipe_generated": True},
                payload=result,
            )
        else:
            for item in targets:
                _record_from_tool(
                    ctx,
                    step,
                    claim_type=claim_type,
                    target=item,
                    effect="neutral",
                    strength=0.0,
                    quality=1.0,
                    context={"recipe_generated": True},
                    payload=result,
                )
    return ctx.to_dict()


def _substantive_records(ctx: EvidenceContext, target: str = "") -> List[EvidenceRecord]:
    symbol = _canonical_target(target)
    return [
        record
        for record in ctx.records.values()
        if record.is_evidentiary and (not symbol or record.target == symbol)
    ]


def evidence_coverage(context: Any) -> Dict[str, Any]:
    ctx = _ensure_context(context)
    substantive = _substantive_records(ctx)
    observed = {record.modality for record in substantive}
    by_modality: Dict[str, Dict[str, int]] = {}
    for modality in MODALITIES:
        rows = [record for record in substantive if record.modality == modality]
        by_modality[modality] = {
            "records": len(rows),
            "supports": sum(record.effect == "supports" for record in rows),
            "contradicts": sum(record.effect == "contradicts" for record in rows),
            "neutral_or_no_signal": sum(record.effect == "neutral" for record in rows),
        }
    return {
        "modalities_observed": sorted(observed),
        "modalities_missing": [modality for modality in MODALITIES if modality not in observed],
        "by_modality": by_modality,
        "recipe_records_excluded": sum(not record.is_evidentiary for record in ctx.records.values()),
        "missing_means": "unknown_not_negative",
    }


def _independent_source_key(record: EvidenceRecord) -> Tuple[str, str, str]:
    if record.source_ids:
        # A PMID/DOI/NCT remains one source even when surfaced through two packs.
        return ("global_id", sorted(record.source_ids)[0], "")
    return (record.source_pack, record.source_tool, record.payload_hash)


def cross_validate(context: Any) -> Dict[str, Any]:
    """Find cross-source corroboration, explicit conflicts, and modality gaps."""
    ctx = _ensure_context(context)
    targets: List[Dict[str, Any]] = []
    for target in ctx.target_symbols(limit=_MAX_TARGETS_PER_RUN):
        records = _substantive_records(ctx, target)
        claim_types = sorted({record.claim_family for record in records})
        claims: List[Dict[str, Any]] = []
        target_conflicts: List[Dict[str, Any]] = []
        corroborated = 0
        for claim_type in claim_types:
            rows = [record for record in records if record.claim_family == claim_type]
            support = [record for record in rows if record.effect == "supports" and record.confidence > 0]
            contradict = [record for record in rows if record.effect == "contradicts" and record.confidence > 0]
            support_modalities = sorted({record.modality for record in support})
            contradict_modalities = sorted({record.modality for record in contradict})
            independent_sources = {_independent_source_key(record) for record in support + contradict}
            if support and contradict:
                status = "contested"
                target_conflicts.append(
                    {
                        "claim_type": claim_type,
                        "supporting_evidence_ids": [record.evidence_id for record in support],
                        "contradicting_evidence_ids": [record.evidence_id for record in contradict],
                        "requires_review": True,
                    }
                )
            elif len(support_modalities) >= 2 and len(independent_sources) >= 2:
                status = "cross_modally_corroborated"
                corroborated += 1
            elif support:
                status = "single_modality_support"
            elif contradict:
                status = "contradiction_only"
            else:
                status = "checked_no_signal"
            claims.append(
                {
                    "claim_type": claim_type,
                    "source_claim_types": sorted({record.claim_type for record in rows}),
                    "status": status,
                    "supporting_modalities": support_modalities,
                    "contradicting_modalities": contradict_modalities,
                    "independent_source_count": len(independent_sources),
                    "support_confidence": round(max((record.confidence for record in support), default=0.0), 4),
                    "contradiction_confidence": round(
                        max((record.confidence for record in contradict), default=0.0), 4
                    ),
                }
            )
        observed = {record.modality for record in records}
        if target_conflicts:
            overall = "contested"
        elif corroborated:
            overall = "corroborated"
        elif records:
            overall = "partial"
        else:
            overall = "unassessed"
        targets.append(
            {
                "target": target,
                "status": overall,
                "claim_results": claims,
                "conflicts": target_conflicts,
                "modalities_observed": sorted(observed),
                "modalities_missing": [modality for modality in MODALITIES if modality not in observed],
                "recipe_records_excluded": sum(
                    (not record.is_evidentiary) and record.target == target for record in ctx.records.values()
                ),
            }
        )
    return {
        "schema": VALIDATION_SCHEMA,
        "context_id": ctx.context_id,
        "targets": targets,
        "conflict_count": sum(len(item["conflicts"]) for item in targets),
        "coverage": evidence_coverage(ctx),
        "interpretation": {
            "missing_evidence": "unknown_not_contradictory",
            "neutral_search_result": "searched_but_no_supporting_hit; not proof of absence",
            "recipe_result": "provenance_only_until_measured_results_are_ingested",
        },
    }


def _combine_confidences(records: Sequence[EvidenceRecord], effect: str) -> float:
    """Combine independent sources with a damped noisy-OR.

    Only the strongest record per source/tool/source-id is used, which avoids
    treating repeated database rows as independent replication.
    """
    strongest: Dict[Tuple[str, str, str], float] = {}
    for record in records:
        if record.effect != effect or record.confidence <= 0:
            continue
        key = _independent_source_key(record)
        strongest[key] = max(strongest.get(key, 0.0), record.confidence)
    remaining = 1.0
    for confidence in sorted(strongest.values(), reverse=True):
        remaining *= 1.0 - (0.85 * confidence)
    return round(1.0 - remaining, 4)


def _modality_score(records: Sequence[EvidenceRecord], modality: str, claims: Sequence[str] = ()) -> float:
    rows = [
        record
        for record in records
        if record.modality == modality and (not claims or record.claim_type in claims)
    ]
    support = _combine_confidences(rows, "supports")
    contradiction = _combine_confidences(rows, "contradicts")
    return round(_clamp(support - contradiction), 4)


def _normalize_weights(weights: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    merged = dict(DEFAULT_WEIGHTS)
    for key, value in (weights or {}).items():
        if key in merged:
            merged[key] = _clamp(value)
    total = sum(merged.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {key: value / total for key, value in merged.items()}


def _reason_lines(dimensions: Mapping[str, float], missing: Sequence[str], contested: bool) -> List[str]:
    labels = {
        "biological_basis": "biological basis",
        "druggability": "druggability",
        "translational_specificity": "single-cell/spatial specificity",
        "clinical_novelty": "low observed trial saturation",
        "evidence_diversity": "cross-modal evidence diversity",
        "evidence_quality": "source quality",
    }
    strongest = sorted(dimensions.items(), key=lambda item: (-item[1], item[0]))[:2]
    reasons = [f"{labels[key]}={value:.2f}" for key, value in strongest if value > 0]
    if missing:
        reasons.append("missing modalities: " + ", ".join(missing))
    if contested:
        reasons.append("explicit conflicting evidence requires review")
    return reasons


def rank_targets(context: Any, weights: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Rank targets while preserving uncertainty and explicit contradictions.

    Missing trial evidence receives a neutral prior for clinical novelty; it is
    never treated as proof that a target is clinically untouched.  An explicit
    zero-hit search is distinguishable because the trials modality is present
    with a neutral record and ``searched=True`` context.
    """
    ctx = _ensure_context(context)
    normalized_weights = _normalize_weights(weights)
    validation = cross_validate(ctx)
    validation_by_target = {row["target"]: row for row in validation["targets"]}
    ranked: List[Dict[str, Any]] = []
    for target in ctx.target_symbols(limit=_MAX_TARGETS_PER_RUN):
        records = _substantive_records(ctx, target)
        literature = _modality_score(records, "literature")
        gene = _modality_score(
            records,
            "gene",
            ("disease_association", "genetic_support", "functional_validation", "target_expression"),
        )
        drug = _modality_score(records, "drug", ("druggability", "bioactivity", "mechanism"))
        single_cell = _modality_score(records, "single_cell")
        spatial = _modality_score(records, "spatial")
        trial_rows = [record for record in records if record.modality == "trials"]
        trial_saturation = _modality_score(trial_rows, "trials", ("clinical_activity",))
        if trial_rows:
            clinical_novelty = 1.0 - trial_saturation
            novelty_basis = "observed_trial_search"
        else:
            # Neutral uncertainty prior: missing trial evidence is neither novel
            # nor crowded.  This prevents absence from becoming a positive score.
            clinical_novelty = 0.5
            novelty_basis = "unknown_no_trial_evidence"

        dimensions = {
            "biological_basis": round((literature + gene + single_cell + spatial) / 4.0, 4),
            "druggability": drug,
            "translational_specificity": round((single_cell + spatial) / 2.0, 4),
            "clinical_novelty": round(_clamp(clinical_novelty), 4),
            "evidence_diversity": round(
                len({record.modality for record in records if record.effect != "neutral" and record.confidence > 0})
                / len(MODALITIES),
                4,
            ),
            "evidence_quality": round(
                sum(record.quality for record in records if record.effect != "neutral")
                / max(1, sum(record.effect != "neutral" for record in records)),
                4,
            ),
        }
        base = sum(dimensions[key] * normalized_weights[key] for key in normalized_weights)
        contradicting = [record for record in records if record.effect == "contradicts"]
        contradiction_penalty = 0.25 * _combine_confidences(contradicting, "contradicts")
        score = round(100.0 * _clamp(base - contradiction_penalty), 2)
        observed = {record.modality for record in records}
        missing = [modality for modality in MODALITIES if modality not in observed]
        target_validation = validation_by_target.get(target, {})
        contested = target_validation.get("status") == "contested"
        ranked.append(
            {
                "target": target,
                "score": score,
                "dimensions": dimensions,
                "modality_scores": {
                    "literature": literature,
                    "gene": gene,
                    "drug": drug,
                    "trials_saturation": trial_saturation,
                    "single_cell": single_cell,
                    "spatial": spatial,
                },
                "clinical_novelty_basis": novelty_basis,
                "contradiction_penalty": round(contradiction_penalty, 4),
                "validation_status": target_validation.get("status", "unassessed"),
                "modalities_missing": missing,
                "reasons": _reason_lines(dimensions, missing, contested),
                "evidence_ids": sorted(record.evidence_id for record in records),
            }
        )
    ranked.sort(key=lambda row: (-row["score"], row["target"]))
    for index, row in enumerate(ranked, 1):
        row["rank"] = index
    return {
        "schema": RANKING_SCHEMA,
        "context_id": ctx.context_id,
        "weights": {key: round(value, 6) for key, value in normalized_weights.items()},
        "targets": ranked,
        "guardrails": [
            "Missing evidence is uncertainty, not negative evidence.",
            "A missing trial search receives a neutral novelty prior; only an observed search can support low saturation.",
            "Analysis recipes do not contribute target support.",
            "Scores prioritize investigation; they are not clinical recommendations or efficacy estimates.",
        ],
    }


def _path_tokens(path: str) -> List[Any]:
    tokens: List[Any] = []
    for name, index in re.findall(r"(?:^|\.)([^.\[\]]+)|\[(\d+)\]", path):
        if name:
            tokens.append(name)
        elif index:
            tokens.append(int(index))
    return tokens


def _lookup_path(root: Any, path: str) -> Any:
    current = root
    for token in _path_tokens(path):
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                return _MISSING
            current = current[token]
        else:
            if not isinstance(current, Mapping) or token not in current:
                return _MISSING
            current = current[token]
    return current


def _resolve_argument(value: Any, ctx: EvidenceContext, outputs: Mapping[str, Any], target: str) -> Any:
    if isinstance(value, str):
        if value == "$context.candidate_target_symbols":
            return ctx.target_symbols(limit=25)
        if value.startswith("$outputs."):
            ref = value[len("$outputs.") :]
            first, _, remainder = ref.partition(".")
            root = outputs.get(first, _MISSING)
            return root if not remainder else _lookup_path(root, remainder)
        replacements = {
            "{target}": target,
            "{disease}": ctx.need.disease,
            "{organism}": ctx.need.organism,
            "{tissue}": ctx.need.tissue,
            "{population}": ctx.need.population,
            "{unmet_need}": ctx.need.unmet_need,
        }
        out = value
        for marker, replacement in replacements.items():
            out = out.replace(marker, replacement)
        return out
    if isinstance(value, list):
        return [_resolve_argument(item, ctx, outputs, target) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve_argument(item, ctx, outputs, target) for item in value)
    if isinstance(value, Mapping):
        return {key: _resolve_argument(item, ctx, outputs, target) for key, item in value.items()}
    return value


def _has_missing(value: Any) -> bool:
    if value is _MISSING:
        return True
    if isinstance(value, Mapping):
        return any(_has_missing(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_missing(item) for item in value)
    return False


def _step_from_dict(value: Mapping[str, Any]) -> PlanStep:
    return PlanStep(
        step_id=str(value.get("step_id")),
        stage=int(value.get("stage") or 0),
        pack=str(value.get("pack") or ""),
        server=str(value.get("server") or ""),
        tool=str(value.get("tool") or ""),
        purpose=str(value.get("purpose") or ""),
        arguments=dict(value.get("arguments") or {}),
        depends_on=tuple(_as_string_list(value.get("depends_on"), 100)),
        produces=tuple(_as_string_list(value.get("produces"), 100)),
        optional=bool(value.get("optional")),
        foreach_target=bool(value.get("foreach_target")),
        evidence_role=str(value.get("evidence_role") or "observation"),
        kind=str(value.get("kind") or "tool"),
        plan_id=str(value.get("plan_id") or ""),
        need_receipt=str(value.get("need_receipt") or ""),
        step_receipt=str(value.get("step_receipt") or ""),
    )


ToolExecutor = Callable[[str, str, Dict[str, Any]], Mapping[str, Any]]


def orchestrate(
    need: Any,
    executor: ToolExecutor,
    initial_context: Any = None,
    weights: Optional[Mapping[str, Any]] = None,
    max_targets: int = 25,
) -> Dict[str, Any]:
    """Execute the cross-modal plan through a caller-supplied MCP callback.

    ``executor`` receives ``(server_name, tool_name, arguments)`` and returns a
    mapping.  Failures are recorded per invocation and do not erase successful
    modalities.  The final answer always includes coverage and gaps.
    """
    parsed = UnmetNeed.from_value(need)
    plan = plan_unmet_need(parsed)
    if initial_context is not None:
        ctx = _ensure_context(initial_context, parsed)
        if ctx.need.receipt != parsed.receipt:
            raise ValueError("initial_context does not match the requested unmet need")
        if ctx.plan_id and ctx.plan_id != plan["plan_id"]:
            raise ValueError("initial_context belongs to a different orchestration plan")
        ctx.plan_id = plan["plan_id"]
    else:
        ctx = EvidenceContext(parsed, plan_id=plan["plan_id"])
    steps = [_step_from_dict(item) for item in plan["steps"]]
    outputs: Dict[str, Any] = {}
    execution_log: List[Dict[str, Any]] = []
    max_targets = _target_limit(max_targets)

    for step in sorted(steps, key=lambda item: (item.stage, item.step_id)):
        if step.kind == "internal":
            execution_log.append({"step_id": step.step_id, "status": "computed_locally"})
            continue
        targets = ctx.target_symbols(max_targets) if step.foreach_target else [""]
        if step.foreach_target and not targets:
            execution_log.append(
                {"step_id": step.step_id, "status": "skipped", "reason": "no_candidate_targets"}
            )
            continue
        step_outputs: List[Dict[str, Any]] = []
        for target in targets:
            arguments = _resolve_argument(step.arguments, ctx, outputs, target)
            if _has_missing(arguments):
                execution_log.append(
                    {
                        "step_id": step.step_id,
                        "target": target or None,
                        "status": "skipped",
                        "reason": "unresolved_upstream_reference",
                    }
                )
                continue
            try:
                result = executor(step.server, step.tool, dict(arguments))
                if not isinstance(result, Mapping):
                    raise TypeError("executor result must be a mapping")
                ctx = EvidenceContext.from_dict(reduce_tool_result(ctx, step, result, target=target))
                step_outputs.append({"target": target, "result": dict(result)})
                execution_log.append(
                    {
                        "step_id": step.step_id,
                        "pack": step.pack,
                        "tool": step.tool,
                        "target": target or None,
                        "status": "ok",
                        "result_hash": _content_hash(result),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - partial modality failure is part of the contract
                execution_log.append(
                    {
                        "step_id": step.step_id,
                        "pack": step.pack,
                        "tool": step.tool,
                        "target": target or None,
                        "status": "error",
                        "optional": step.optional,
                        "error": str(exc)[:500],
                    }
                )
        if step.foreach_target:
            outputs[step.step_id] = step_outputs
        elif step_outputs:
            outputs[step.step_id] = step_outputs[0]["result"]

    context_packet = ctx.to_dict()
    return {
        "schema": "bio-crossmodal/orchestration-result/1",
        "plan_id": plan["plan_id"],
        "context_id": context_packet["context_id"],
        "need_receipt": parsed.receipt,
        "plan": plan,
        "context": context_packet,
        "cross_validation": cross_validate(ctx),
        "ranking": rank_targets(ctx, weights=weights),
        "execution_log": execution_log,
        "errors": [row for row in execution_log if row.get("status") == "error"],
    }


__all__ = [
    "CONTEXT_SCHEMA",
    "PLAN_SCHEMA",
    "VALIDATION_SCHEMA",
    "RANKING_SCHEMA",
    "MODALITIES",
    "PACK_MODALITY",
    "DEFAULT_WEIGHTS",
    "UnmetNeed",
    "PlanStep",
    "EvidenceRecord",
    "EvidenceContext",
    "new_evidence_context",
    "plan_unmet_need",
    "integrate_observations",
    "reduce_tool_result",
    "evidence_coverage",
    "cross_validate",
    "rank_targets",
    "orchestrate",
]
