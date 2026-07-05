"""bio_eval 共享 MCP 工具 schema —— case 通过短名引用，避免每个 case 重复贴 schema。

这些 schema 塞进模型的 tools=[...]，让模型"看到"工具。tool_executor 真跑本地 handler
（fixture 激活时离线），所以工具名要和 packs / shim 里注册的名字对齐。
"""

from __future__ import annotations

from typing import Any, Dict, List


SCHEMAS: Dict[str, Dict[str, Any]] = {
    "search_articles": {
        "name": "search_articles",
        "description": "Search PubMed for medical / biological literature",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 20},
                "min_date": {"type": "string"}, "max_date": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "pubmed_fetch": {
        "name": "pubmed_fetch",
        "description": "Fetch PubMed article metadata + abstract by PMID(s)",
        "input_schema": {
            "type": "object",
            "properties": {"pmids": {"type": "array", "items": {"type": "string"}}},
            "required": ["pmids"],
        },
    },
    "europepmc_search": {
        "name": "europepmc_search",
        "description": "Search Europe PMC (includes preprints + PMC full text)",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "page_size": {"type": "integer"}},
            "required": ["query"],
        },
    },
    "search_trials": {
        "name": "search_trials",
        "description": "Search ClinicalTrials.gov",
        "input_schema": {
            "type": "object",
            "properties": {
                "condition": {"type": "string"}, "intervention": {"type": "string"},
                "status": {"type": "string"}, "phase": {"type": "string"},
            },
        },
    },
    "get_trial_details": {
        "name": "get_trial_details",
        "description": "Get full protocol for one NCT id",
        "input_schema": {
            "type": "object",
            "properties": {"nct_id": {"type": "string"}},
            "required": ["nct_id"],
        },
    },
    "analyze_endpoints": {
        "name": "analyze_endpoints",
        "description": "Compare outcome measures across trials",
        "input_schema": {
            "type": "object",
            "properties": {"condition": {"type": "string"}, "intervention": {"type": "string"}},
        },
    },
    "compound_search": {
        "name": "compound_search",
        "description": "Search ChEMBL compounds by name / SMILES / ChEMBL id",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
    },
    "get_bioactivity": {
        "name": "get_bioactivity",
        "description": "Get IC50/EC50/Ki for compound-target pair",
        "input_schema": {
            "type": "object",
            "properties": {
                "molecule_chembl_id": {"type": "string"},
                "target_chembl_id": {"type": "string"},
                "standard_type": {"type": "string"},
            },
        },
    },
    "get_mechanism": {
        "name": "get_mechanism",
        "description": "Get mechanism of action + target for a drug",
        "input_schema": {
            "type": "object",
            "properties": {"molecule_chembl_id": {"type": "string"}},
            "required": ["molecule_chembl_id"],
        },
    },
    "ot_disease_associated_targets": {
        "name": "ot_disease_associated_targets",
        "description": "Open Targets: targets associated with a disease (EFO/MONDO id)",
        "input_schema": {
            "type": "object",
            "properties": {"efo_id": {"type": "string"}, "size": {"type": "integer"}},
            "required": ["efo_id"],
        },
    },
    "ot_target_associated_diseases": {
        "name": "ot_target_associated_diseases",
        "description": "Open Targets: diseases associated with a target (Ensembl gene id)",
        "input_schema": {
            "type": "object",
            "properties": {"ensembl_id": {"type": "string"}, "size": {"type": "integer"}},
            "required": ["ensembl_id"],
        },
    },
    "search_preprints": {
        "name": "search_preprints",
        "description": "Search bioRxiv/medRxiv preprints",
        "input_schema": {
            "type": "object",
            "properties": {
                "server": {"type": "string"}, "query": {"type": "string"},
                "from_date": {"type": "string"}, "to_date": {"type": "string"},
            },
        },
    },
    "geo_search": {
        "name": "geo_search",
        "description": "Search GEO datasets by keyword",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "retmax": {"type": "integer"}},
            "required": ["query"],
        },
    },
    "geo_summary": {
        "name": "geo_summary",
        "description": "Get GEO dataset summary by GSE id",
        "input_schema": {
            "type": "object",
            "properties": {"gse_id": {"type": "string"}},
            "required": ["gse_id"],
        },
    },
    "evidence_verify": {
        "name": "evidence_verify",
        "description": "Verify PMID/DOI/NCT citations exist and get metadata + evidence type",
        "input_schema": {
            "type": "object",
            "properties": {
                "claims": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "refs": {"type": "array", "items": {
                            "type": "object",
                            "properties": {"id_type": {"type": "string"}, "id": {"type": "string"}},
                        }},
                    },
                }},
            },
            "required": ["claims"],
        },
    },
    "evidence_profile": {
        "name": "evidence_profile",
        "description": "Deep-profile one citation: species / population / sample size / experiment type / disease stage",
        "input_schema": {
            "type": "object",
            "properties": {"id_type": {"type": "string"}, "id": {"type": "string"}},
            "required": ["id_type", "id"],
        },
    },
    "evidence_graph": {
        "name": "evidence_graph",
        "description": "Claim-level evidence graph: bind evidence + species/n/stage, compute applicability boundary, conflicts, counter-evidence",
        "input_schema": {
            "type": "object",
            "properties": {
                "claims": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "asserted": {"type": "object"},
                        "refs": {"type": "array", "items": {
                            "type": "object",
                            "properties": {"id_type": {"type": "string"}, "id": {"type": "string"},
                                           "stance": {"type": "string"}},
                        }},
                    },
                }},
            },
            "required": ["claims"],
        },
    },
    "uncertainty_ledger": {
        "name": "uncertainty_ledger",
        "description": "Compile Known knowns / Known unknowns / Conflicts / Missing data / Next experiment from an evidence_graph result",
        "input_schema": {
            "type": "object",
            "properties": {
                "graph_claims": {"type": "array", "items": {"type": "object"}},
                "question": {"type": "string"},
                "extra": {"type": "object"},
            },
            "required": ["graph_claims"],
        },
    },
    "compile_research_question": {
        "name": "compile_research_question",
        "description": "Compile a vague biomedical question into a structured research task (object/disease/molecule/intervention/endpoints/databases/exclusions/evidence-bar/toolchain)",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    "phi_scan": {
        "name": "phi_scan",
        "description": "Scan text for PHI (HIPAA Safe Harbor identifiers). Returns findings with confidence. Local regex, no network.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    "phi_redact": {
        "name": "phi_redact",
        "description": "Redact PHI from text with consistent placeholders ([PATIENT_1]).",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
}


def resolve(names: List[str]) -> List[Dict[str, Any]]:
    """把短名列表解析成 schema 对象列表（tools=[...] 用）。未知名跳过。"""
    return [SCHEMAS[n] for n in names if n in SCHEMAS]
