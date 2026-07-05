#!/usr/bin/env python3
"""ClinicalTrials.gov v2 API MCP server。

工具：
  ctgov_search   — 多条件试验检索（condition / intervention / status / phase / location）
  ctgov_detail   — NCT ID → 完整方案（含入排标准 / 终点 / 地点）
  ctgov_by_sponsor — 按赞助方查试验（管线情报）

API 文档：https://clinicaltrials.gov/data-api/api
不需要 API key，返回体较大，默认 pageSize=25。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_BASE = "https://clinicaltrials.gov/api/v2"
server = MCPServer("bio-trials-ctgov", "0.1.0")


def _flatten_study(s: dict) -> dict:
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
        "official_title": ident.get("officialTitle"),
        "status": status.get("overallStatus"),
        "start": (status.get("startDateStruct") or {}).get("date"),
        "completion": (status.get("completionDateStruct") or {}).get("date"),
        "study_type": design.get("studyType"),
        "phase": design.get("phases"),
        "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
        "allocation": (design.get("designInfo") or {}).get("allocation"),
        "primary_purpose": (design.get("designInfo") or {}).get("primaryPurpose"),
        "conditions": conds.get("conditions"),
        "interventions": [
            {"type": i.get("type"), "name": i.get("name"), "description": i.get("description")}
            for i in (interv.get("interventions") or [])
        ],
        "sponsor": (sponsor.get("leadSponsor") or {}).get("name"),
        "collaborators": [c.get("name") for c in (sponsor.get("collaborators") or [])],
        "locations": [
            {"facility": l.get("facility"), "city": l.get("city"),
             "state": l.get("state"), "country": l.get("country"),
             "status": l.get("status")}
            for l in (contacts.get("locations") or [])[:20]
        ],
        "primary_outcomes": [o.get("measure") for o in (outcomes.get("primaryOutcomes") or [])],
        "secondary_outcomes": [o.get("measure") for o in (outcomes.get("secondaryOutcomes") or [])],
        "eligibility": {
            "criteria": elig.get("eligibilityCriteria"),
            "sex": elig.get("sex"),
            "min_age": elig.get("minimumAge"),
            "max_age": elig.get("maximumAge"),
            "healthy_volunteers": elig.get("healthyVolunteers"),
        },
    }


def _search_params(**kw):
    """v2 API 用 query.* 前缀，按字段名区分。参见 /api/v2/studies?format=fields"""
    params = {"format": "json"}
    if kw.get("condition"):
        params["query.cond"] = kw["condition"]
    if kw.get("intervention"):
        params["query.intr"] = kw["intervention"]
    if kw.get("term"):
        params["query.term"] = kw["term"]
    if kw.get("status"):
        params["filter.overallStatus"] = kw["status"]
    if kw.get("phase"):
        params["filter.phase"] = kw["phase"]
    if kw.get("location"):
        params["query.locn"] = kw["location"]
    if kw.get("sponsor"):
        params["query.spons"] = kw["sponsor"]
    if kw.get("study_type"):
        params["filter.studyType"] = kw["study_type"]
    params["pageSize"] = kw.get("pageSize", 25)
    if kw.get("pageToken"):
        params["pageToken"] = kw["pageToken"]
    return params


@server.tool(
    "ctgov_search",
    "Search ClinicalTrials.gov by condition / intervention / free text / status / phase / location. "
    "Filters accept ClinicalTrials.gov canonical vocabularies; e.g. status='RECRUITING|ACTIVE_NOT_RECRUITING', phase='PHASE3'.",
    {
        "type": "object",
        "properties": {
            "condition": {"type": "string", "description": "Disease / condition, e.g. 'non-small cell lung cancer'"},
            "intervention": {"type": "string", "description": "Drug / therapy name"},
            "term": {"type": "string", "description": "Free-text term (title, keyword, etc.)"},
            "status": {"type": "string", "description": "Trial status filter, pipe-separated"},
            "phase": {"type": "string", "description": "e.g. 'PHASE2', 'PHASE3'"},
            "study_type": {"type": "string", "enum": ["INTERVENTIONAL", "OBSERVATIONAL", "EXPANDED_ACCESS"]},
            "location": {"type": "string", "description": "City / country"},
            "pageSize": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
            "pageToken": {"type": "string"},
        },
    },
)
def ctgov_search(**kwargs):
    data = http.get_json(f"{_BASE}/studies", params=_search_params(**kwargs))
    studies = (data or {}).get("studies") or []
    return {
        "total": (data or {}).get("totalCount"),
        "next_page_token": (data or {}).get("nextPageToken"),
        "results": [_flatten_study(s) for s in studies],
    }


@server.tool(
    "ctgov_detail",
    "Fetch full protocol for a given NCT ID.",
    {
        "type": "object",
        "properties": {"nct_id": {"type": "string"}},
        "required": ["nct_id"],
    },
)
@memoize("ctgov_detail", ttl_seconds=7 * 24 * 3600)
def ctgov_detail(nct_id: str):
    nct_id = nct_id.strip().upper()
    try:
        data = http.get_json(f"{_BASE}/studies/{nct_id}", params={"format": "json"})
    except Exception as e:  # noqa: BLE001
        return {"nct_id": nct_id, "exists": False, "error": str(e)}
    if not data or "protocolSection" not in data:
        return {"nct_id": nct_id, "exists": False}
    return {"nct_id": nct_id, "exists": True, **_flatten_study(data)}


@server.tool(
    "ctgov_by_sponsor",
    "List trials for a given sponsor (competitive intelligence). Optional filter by status/phase.",
    {
        "type": "object",
        "properties": {
            "sponsor": {"type": "string"},
            "status": {"type": "string"},
            "phase": {"type": "string"},
            "pageSize": {"type": "integer", "default": 50, "minimum": 1, "maximum": 100},
        },
        "required": ["sponsor"],
    },
)
def ctgov_by_sponsor(sponsor: str, status: str | None = None,
                     phase: str | None = None, pageSize: int = 50):
    params = _search_params(sponsor=sponsor, status=status, phase=phase, pageSize=pageSize)
    data = http.get_json(f"{_BASE}/studies", params=params)
    studies = (data or {}).get("studies") or []
    return {
        "total": (data or {}).get("totalCount"),
        "results": [_flatten_study(s) for s in studies],
    }


if __name__ == "__main__":
    server.run()
