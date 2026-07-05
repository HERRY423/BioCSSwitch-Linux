#!/usr/bin/env python3
"""clinical-trials MCP 本地替身。走 ClinicalTrials.gov v2 API。

工具名尽量对齐 Anthropic 远程 MCP：search_trials / get_trial_details / search_by_sponsor /
search_investigators / analyze_endpoints / search_by_eligibility。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://clinicaltrials.gov/api/v2"
server = MCPServer("clinical-trials-shim", "0.1.0")


def _flatten(s: dict) -> dict:
    prot = s.get("protocolSection") or {}
    ident = prot.get("identificationModule") or {}
    status = prot.get("statusModule") or {}
    design = prot.get("designModule") or {}
    conds = prot.get("conditionsModule") or {}
    interv = prot.get("armsInterventionsModule") or {}
    sponsor = prot.get("sponsorCollaboratorsModule") or {}
    contacts = prot.get("contactsLocationsModule") or {}
    outcomes = prot.get("outcomesModule") or {}
    elig = prot.get("eligibilityModule") or {}
    return {
        "nct_id": ident.get("nctId"),
        "title": ident.get("briefTitle"),
        "status": status.get("overallStatus"),
        "study_type": design.get("studyType"),
        "phase": design.get("phases"),
        "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
        "conditions": conds.get("conditions"),
        "interventions": [{"type": i.get("type"), "name": i.get("name")}
                          for i in (interv.get("interventions") or [])],
        "sponsor": (sponsor.get("leadSponsor") or {}).get("name"),
        "primary_outcomes": [o.get("measure") for o in (outcomes.get("primaryOutcomes") or [])],
        "locations": [{"facility": l.get("facility"), "city": l.get("city"),
                       "country": l.get("country"), "status": l.get("status")}
                      for l in (contacts.get("locations") or [])[:15]],
        "eligibility_criteria": elig.get("eligibilityCriteria"),
        "min_age": elig.get("minimumAge"),
        "max_age": elig.get("maximumAge"),
    }


def _build_search_params(**kw):
    p = {"format": "json"}
    if kw.get("condition"):
        p["query.cond"] = kw["condition"]
    if kw.get("intervention"):
        p["query.intr"] = kw["intervention"]
    if kw.get("term"):
        p["query.term"] = kw["term"]
    if kw.get("status"):
        p["filter.overallStatus"] = kw["status"]
    if kw.get("phase"):
        p["filter.phase"] = kw["phase"]
    if kw.get("sponsor"):
        p["query.spons"] = kw["sponsor"]
    if kw.get("location"):
        p["query.locn"] = kw["location"]
    p["pageSize"] = kw.get("page_size", 25)
    if kw.get("page_token"):
        p["pageToken"] = kw["page_token"]
    return p


@server.tool(
    "search_trials",
    "[Local shim of Anthropic-hosted clinical-trials] Search ClinicalTrials.gov v2 by condition / intervention / status / phase / location.",
    {
        "type": "object",
        "properties": {
            "condition": {"type": "string"},
            "intervention": {"type": "string"},
            "term": {"type": "string"},
            "status": {"type": "string"},
            "phase": {"type": "string"},
            "location": {"type": "string"},
            "page_size": {"type": "integer", "default": 25},
        },
    },
)
def search_trials(**kwargs):
    data = http.get_json(f"{_BASE}/studies", params=_build_search_params(**kwargs))
    return {
        "total": (data or {}).get("totalCount"),
        "next_page_token": (data or {}).get("nextPageToken"),
        "results": [_flatten(s) for s in (data or {}).get("studies", [])],
    }


@server.tool(
    "get_trial_details",
    "[Local shim] Full protocol for one NCT ID.",
    {
        "type": "object",
        "properties": {"nct_id": {"type": "string"}},
        "required": ["nct_id"],
    },
)
@memoize("ctgov_shim_detail", ttl_seconds=7 * 24 * 3600)
def get_trial_details(nct_id: str):
    nct_id = nct_id.strip().upper()
    try:
        data = http.get_json(f"{_BASE}/studies/{nct_id}", params={"format": "json"})
    except Exception as e:  # noqa: BLE001
        return {"nct_id": nct_id, "exists": False, "error": str(e)}
    if not data or "protocolSection" not in data:
        return {"nct_id": nct_id, "exists": False}
    return {"exists": True, **_flatten(data)}


@server.tool(
    "search_by_sponsor",
    "[Local shim] Search trials by lead sponsor.",
    {
        "type": "object",
        "properties": {
            "sponsor": {"type": "string"},
            "status": {"type": "string"},
            "phase": {"type": "string"},
            "page_size": {"type": "integer", "default": 50},
        },
        "required": ["sponsor"],
    },
)
def search_by_sponsor(sponsor: str, status: str | None = None,
                     phase: str | None = None, page_size: int = 50):
    data = http.get_json(f"{_BASE}/studies", params=_build_search_params(
        sponsor=sponsor, status=status, phase=phase, page_size=page_size))
    return {
        "total": (data or {}).get("totalCount"),
        "results": [_flatten(s) for s in (data or {}).get("studies", [])],
    }


@server.tool(
    "search_investigators",
    "[Local shim] Find principal investigators for trials matching a condition.",
    {
        "type": "object",
        "properties": {
            "condition": {"type": "string"},
            "location": {"type": "string"},
            "page_size": {"type": "integer", "default": 50},
        },
        "required": ["condition"],
    },
)
def search_investigators(condition: str, location: str | None = None, page_size: int = 50):
    # v2 API 没直接的 PI 端点，用 search_trials 抽取
    data = http.get_json(f"{_BASE}/studies", params=_build_search_params(
        condition=condition, location=location, page_size=page_size))
    counter = Counter()
    detail = {}
    for s in (data or {}).get("studies", []):
        prot = s.get("protocolSection") or {}
        contacts = prot.get("contactsLocationsModule") or {}
        for l in contacts.get("locations") or []:
            for ct in l.get("contacts") or []:
                name = ct.get("name")
                if name:
                    counter[name] += 1
                    detail.setdefault(name, {
                        "affiliation": l.get("facility"),
                        "country": l.get("country"),
                    })
    ranked = [
        {"name": n, "trial_count": c, **detail[n]}
        for n, c in counter.most_common(50)
    ]
    return {"investigators": ranked}


@server.tool(
    "analyze_endpoints",
    "[Local shim] Aggregate primary / secondary outcome measures across trials for a condition.",
    {
        "type": "object",
        "properties": {
            "condition": {"type": "string"},
            "phase": {"type": "string"},
            "page_size": {"type": "integer", "default": 50},
        },
        "required": ["condition"],
    },
)
def analyze_endpoints(condition: str, phase: str | None = None, page_size: int = 50):
    data = http.get_json(f"{_BASE}/studies", params=_build_search_params(
        condition=condition, phase=phase, page_size=page_size))
    primary = Counter()
    secondary = Counter()
    for s in (data or {}).get("studies", []):
        prot = s.get("protocolSection") or {}
        outs = prot.get("outcomesModule") or {}
        for o in outs.get("primaryOutcomes") or []:
            if o.get("measure"):
                primary[o["measure"]] += 1
        for o in outs.get("secondaryOutcomes") or []:
            if o.get("measure"):
                secondary[o["measure"]] += 1
    return {
        "n_trials_scanned": len((data or {}).get("studies", [])),
        "primary": [{"endpoint": e, "count": c} for e, c in primary.most_common(30)],
        "secondary": [{"endpoint": e, "count": c} for e, c in secondary.most_common(30)],
    }


@server.tool(
    "search_by_eligibility",
    "[Local shim] Find trials matching demographic eligibility (age, sex, healthy volunteers).",
    {
        "type": "object",
        "properties": {
            "condition": {"type": "string"},
            "age": {"type": "integer"},
            "sex": {"type": "string", "enum": ["ALL", "MALE", "FEMALE"]},
            "healthy_volunteers": {"type": "boolean"},
            "page_size": {"type": "integer", "default": 25},
        },
        "required": ["condition"],
    },
)
def search_by_eligibility(condition: str, age: int | None = None,
                          sex: str | None = None, healthy_volunteers: bool | None = None,
                          page_size: int = 25):
    # v2 有 filter.eligibility_criteria；粗过滤后本地再筛
    params = _build_search_params(condition=condition, page_size=page_size * 2)
    data = http.get_json(f"{_BASE}/studies", params=params)
    matched = []
    for s in (data or {}).get("studies", []):
        flat = _flatten(s)
        elig = ((s.get("protocolSection") or {}).get("eligibilityModule") or {})
        if sex and (elig.get("sex") or "ALL").upper() != sex.upper():
            continue
        if healthy_volunteers is not None:
            hv = elig.get("healthyVolunteers")
            if bool(hv) != bool(healthy_volunteers):
                continue
        # age 过滤：粗看 min/max age 字段（"18 Years"）
        if age is not None:
            def _parse_age(a):
                if not a:
                    return None
                try:
                    return int(a.split()[0])
                except Exception:
                    return None
            min_a = _parse_age(flat.get("min_age"))
            max_a = _parse_age(flat.get("max_age"))
            if min_a is not None and age < min_a:
                continue
            if max_a is not None and age > max_a:
                continue
        matched.append(flat)
        if len(matched) >= page_size:
            break
    return {"matched": matched, "n_matched": len(matched)}


if __name__ == "__main__":
    server.run()
