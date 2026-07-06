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
    "anndata_fingerprint": {
        "name": "anndata_fingerprint",
        "description": "Fingerprint an AnnData descriptor and return a true content hash snippet",
        "input_schema": {
            "type": "object",
            "properties": {"descriptor": {"type": "object"}, "hash_layer": {"type": "string"}},
            "required": ["descriptor"],
        },
    },
    "sc_qc_thresholds": {
        "name": "sc_qc_thresholds",
        "description": "Suggest MAD-based single-cell QC thresholds",
        "input_schema": {
            "type": "object",
            "properties": {"stats": {"type": "object"}, "n_mads": {"type": "number"}},
            "required": ["stats"],
        },
    },
    "sc_preprocess_recipe": {
        "name": "sc_preprocess_recipe",
        "description": "Generate a deterministic scanpy preprocessing recipe",
        "input_schema": {
            "type": "object",
            "properties": {"target_model": {"type": "string"}, "overrides": {"type": "object"}, "seed": {"type": "integer"}},
        },
    },
    "sc_doublet_recipe": {
        "name": "sc_doublet_recipe",
        "description": "Generate Scrublet/scDblFinder doublet detection recipe",
        "input_schema": {
            "type": "object",
            "properties": {"n_obs": {"type": "integer"}, "expected_doublet_rate": {"type": "number"}, "method": {"type": "string"}},
            "required": ["n_obs"],
        },
    },
    "sc_batch_recipe": {
        "name": "sc_batch_recipe",
        "description": "Generate batch integration recipe and method guidance",
        "input_schema": {
            "type": "object",
            "properties": {"n_batches": {"type": "integer"}, "batch_key": {"type": "string"}, "method": {"type": "string"}},
        },
    },
    "sc_geneid_convert": {
        "name": "sc_geneid_convert",
        "description": "Generate gene ID conversion guide/script",
        "input_schema": {
            "type": "object",
            "properties": {"source_id_type": {"type": "string"}, "target_id_type": {"type": "string"}, "organism": {"type": "string"}},
            "required": ["source_id_type", "target_id_type"],
        },
    },
    "sc_celltype_recipe": {
        "name": "sc_celltype_recipe",
        "description": "Generate CellTypist/SingleR/marker-based cell type annotation recipe",
        "input_schema": {
            "type": "object",
            "properties": {"method": {"type": "string"}, "organism": {"type": "string"}, "tissue": {"type": "string"}},
        },
    },
    "sc_multimodal_recipe": {
        "name": "sc_multimodal_recipe",
        "description": "Generate CITE-seq/multiome preprocessing recipe",
        "input_schema": {
            "type": "object",
            "properties": {"modality": {"type": "string"}, "method": {"type": "string"}, "batch_key": {"type": "string"}},
        },
    },
    "sc_spatial_recipe": {
        "name": "sc_spatial_recipe",
        "description": "Generate spatial transcriptomics preprocessing recipe",
        "input_schema": {
            "type": "object",
            "properties": {"platform": {"type": "string"}, "organism": {"type": "string"}},
        },
    },
    "scfm_embed_plan": {
        "name": "scfm_embed_plan",
        "description": "Generate a not-runnable single-cell foundation model embedding skeleton",
        "input_schema": {
            "type": "object",
            "properties": {"model": {"type": "string"}, "anndata_sha256": {"type": "string"}, "preprocessing_hash": {"type": "string"}},
            "required": ["model"],
        },
    },
    "scfm_finetune_plan": {
        "name": "scfm_finetune_plan",
        "description": "Generate a not-runnable Geneformer/scGPT fine-tuning skeleton",
        "input_schema": {
            "type": "object",
            "properties": {"model": {"type": "string"}, "task_type": {"type": "string"}, "label_key": {"type": "string"}},
            "required": ["model"],
        },
    },
    "scfm_embed_quality": {
        "name": "scfm_embed_quality",
        "description": "Generate embedding quality metric recipe",
        "input_schema": {
            "type": "object",
            "properties": {"scenario": {"type": "string"}, "embedding_key": {"type": "string"}, "batch_key": {"type": "string"}, "celltype_key": {"type": "string"}},
        },
    },
    "scfm_preprocess_recipe_ext": {
        "name": "scfm_preprocess_recipe_ext",
        "description": "Generate CellFM/UCE-specific preprocessing recipe",
        "input_schema": {
            "type": "object",
            "properties": {"model": {"type": "string"}, "organism": {"type": "string"}, "input_id_type": {"type": "string"}},
            "required": ["model"],
        },
    },
    "sc_deg_recipe": {
        "name": "sc_deg_recipe",
        "description": "Generate scRNA-seq DEG recipe",
        "input_schema": {
            "type": "object",
            "properties": {"method": {"type": "string"}, "replicates_per_condition": {"type": "integer"}, "condition_key": {"type": "string"}},
        },
    },
    "sc_trajectory_recipe": {
        "name": "sc_trajectory_recipe",
        "description": "Generate trajectory/RNA velocity recipe",
        "input_schema": {
            "type": "object",
            "properties": {"method": {"type": "string"}, "has_spliced_unspliced": {"type": "boolean"}, "cluster_key": {"type": "string"}},
        },
    },
    "sc_communication_recipe": {
        "name": "sc_communication_recipe",
        "description": "Generate cell-cell communication recipe",
        "input_schema": {
            "type": "object",
            "properties": {"method": {"type": "string"}, "celltype_key": {"type": "string"}, "organism": {"type": "string"}},
        },
    },
    "sc_marker_recipe": {
        "name": "sc_marker_recipe",
        "description": "Generate marker gene analysis recipe",
        "input_schema": {
            "type": "object",
            "properties": {"cluster_key": {"type": "string"}, "known_marker_file": {"type": "string"}},
        },
    },
    "sc_enrichment_recipe": {
        "name": "sc_enrichment_recipe",
        "description": "Generate single-cell enrichment recipe",
        "input_schema": {
            "type": "object",
            "properties": {"method": {"type": "string"}, "cluster_key": {"type": "string"}, "gene_set_source": {"type": "string"}},
        },
    },
    "cellxgene_search": {
        "name": "cellxgene_search",
        "description": "Build a CELLxGENE dataset search plan",
        "input_schema": {
            "type": "object",
            "properties": {"tissue": {"type": "string"}, "organism": {"type": "string"}, "disease": {"type": "string"}, "cell_type": {"type": "string"}},
        },
    },
    "cellxgene_dataset_info": {
        "name": "cellxgene_dataset_info",
        "description": "Build CELLxGENE dataset metadata checklist",
        "input_schema": {
            "type": "object",
            "properties": {"dataset_id": {"type": "string"}, "collection_id": {"type": "string"}},
            "required": ["dataset_id"],
        },
    },
    "cellxgene_download_recipe": {
        "name": "cellxgene_download_recipe",
        "description": "Generate cellxgene-census download skeleton",
        "input_schema": {
            "type": "object",
            "properties": {"organism": {"type": "string"}, "dataset_id": {"type": "string"}, "obs_value_filter": {"type": "string"}},
        },
    },
}


def resolve(names: List[str]) -> List[Dict[str, Any]]:
    """把短名列表解析成 schema 对象列表（tools=[...] 用）。未知名跳过。"""
    return [SCHEMAS[n] for n in names if n in SCHEMAS]
