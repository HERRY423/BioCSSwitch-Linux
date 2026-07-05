#!/usr/bin/env python3
"""Open Targets Platform MCP server：靶点-疾病关联 / 药物-靶点。

API 是 GraphQL：https://api.platform.opentargets.org/api/v4/graphql
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import http  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


_GQL = "https://api.platform.opentargets.org/api/v4/graphql"
server = MCPServer("bio-drug-opentargets", "0.1.0")


def _gql(query: str, variables: dict):
    return http.post_json(_GQL, {"query": query, "variables": variables})


@server.tool(
    "ot_search",
    "Free-text search Open Targets for targets / diseases / drugs. Returns entity IDs to feed into detail tools.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "entity": {"type": "string", "enum": ["target", "disease", "drug"], "description": "Optional filter"},
        },
        "required": ["query"],
    },
)
def ot_search(query: str, entity: str | None = None):
    q = """
    query search($q: String!, $entityNames: [String!]) {
      search(queryString: $q, entityNames: $entityNames) {
        hits { id entity name description }
      }
    }
    """
    variables = {"q": query, "entityNames": [entity] if entity else None}
    data = _gql(q, variables)
    return {"hits": ((data or {}).get("data") or {}).get("search", {}).get("hits") or []}


@server.tool(
    "ot_target_associated_diseases",
    "For an Ensembl gene ID, list top associated diseases with Open Targets association scores.",
    {
        "type": "object",
        "properties": {
            "ensembl_id": {"type": "string", "description": "e.g. 'ENSG00000012048' for BRCA1"},
            "size": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
        },
        "required": ["ensembl_id"],
    },
)
@memoize("ot_target_diseases", ttl_seconds=7 * 24 * 3600)
def ot_target_associated_diseases(ensembl_id: str, size: int = 25):
    q = """
    query t($id: String!, $size: Int!) {
      target(ensemblId: $id) {
        id approvedSymbol approvedName
        associatedDiseases(page: {index: 0, size: $size}) {
          count
          rows { score disease { id name therapeuticAreas { id name } } }
        }
      }
    }
    """
    data = _gql(q, {"id": ensembl_id, "size": size})
    t = ((data or {}).get("data") or {}).get("target") or {}
    return {
        "target": {"id": t.get("id"), "symbol": t.get("approvedSymbol"), "name": t.get("approvedName")},
        "count": (t.get("associatedDiseases") or {}).get("count"),
        "rows": (t.get("associatedDiseases") or {}).get("rows") or [],
    }


@server.tool(
    "ot_disease_associated_targets",
    "For an EFO / MONDO disease ID, list top associated targets.",
    {
        "type": "object",
        "properties": {
            "efo_id": {"type": "string", "description": "e.g. 'EFO_0000305' for breast cancer"},
            "size": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
        },
        "required": ["efo_id"],
    },
)
def ot_disease_associated_targets(efo_id: str, size: int = 25):
    q = """
    query d($id: String!, $size: Int!) {
      disease(efoId: $id) {
        id name
        associatedTargets(page: {index: 0, size: $size}) {
          count
          rows { score target { id approvedSymbol approvedName } }
        }
      }
    }
    """
    data = _gql(q, {"id": efo_id, "size": size})
    d = ((data or {}).get("data") or {}).get("disease") or {}
    return {
        "disease": {"id": d.get("id"), "name": d.get("name")},
        "count": (d.get("associatedTargets") or {}).get("count"),
        "rows": (d.get("associatedTargets") or {}).get("rows") or [],
    }


@server.tool(
    "ot_drug_details",
    "Fetch drug / molecule details from Open Targets (mechanism of action, indications, approved status).",
    {
        "type": "object",
        "properties": {"chembl_id": {"type": "string", "description": "e.g. 'CHEMBL25' for aspirin"}},
        "required": ["chembl_id"],
    },
)
@memoize("ot_drug", ttl_seconds=30 * 24 * 3600)
def ot_drug_details(chembl_id: str):
    q = """
    query drug($id: String!) {
      drug(chemblId: $id) {
        id name synonyms tradeNames yearOfFirstApproval
        drugType isApproved blackBoxWarning hasBeenWithdrawn
        maximumClinicalTrialPhase description
        mechanismsOfAction {
          rows { mechanismOfAction actionType targetName targets { id approvedSymbol } }
        }
        indications {
          rows { maxPhaseForIndication disease { id name } }
        }
      }
    }
    """
    data = _gql(q, {"id": chembl_id})
    return ((data or {}).get("data") or {}).get("drug") or {"exists": False}


if __name__ == "__main__":
    server.run()
