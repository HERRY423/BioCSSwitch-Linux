#!/usr/bin/env python3
"""CELLxGENE atlas helper MCP（bio-sc-atlas）。

保持轻量：不把 cellxgene-census SDK 作为 pack 依赖。工具输出查询计划、元数据字段约束
和下载 skeleton；真正下载/切片在用户机器上执行。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import provenance as prov  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-sc-atlas", "0.1.0")


def _hash(tool: str, params: Dict[str, Any]) -> str:
    return prov.content_hash({"tool": tool, "params": params})


@server.tool(
    "cellxgene_search",
    "Build a lightweight CELLxGENE Census/Discover dataset search plan by tissue, organism, disease, and cell type. "
    "Returns filter terms, expected metadata fields, and a reproducible query hash; does not download data.",
    {
        "type": "object",
        "properties": {
            "tissue": {"type": "string"},
            "organism": {"type": "string", "default": "Homo sapiens"},
            "disease": {"type": "string"},
            "cell_type": {"type": "string"},
            "assay": {"type": "string"},
            "max_results": {"type": "integer", "default": 20},
        },
    },
)
def cellxgene_search(
    tissue: Optional[str] = None,
    organism: str = "Homo sapiens",
    disease: Optional[str] = None,
    cell_type: Optional[str] = None,
    assay: Optional[str] = None,
    max_results: int = 20,
):
    filters = {k: v for k, v in {
        "tissue": tissue,
        "organism": organism,
        "disease": disease,
        "cell_type": cell_type,
        "assay": assay,
    }.items() if v}
    qhash = _hash("cellxgene_search", {"filters": filters, "max_results": max_results})
    return {
        "query_hash": qhash,
        "filters": filters,
        "max_results": max_results,
        "expected_metadata_fields": [
            "dataset_id", "collection_id", "collection_name", "dataset_title",
            "organism", "tissue", "disease", "assay", "cell_type", "n_obs", "citation", "schema_version",
        ],
        "manual_search_url": "https://cellxgene.cziscience.com/datasets",
        "census_python_hint": "Use cellxgene_census.open_soma() and census['census_info']['datasets'].read(...) with value filters.",
        "note": "这是轻量检索计划，不下载表达矩阵。把 query_hash 记录到下游 provenance。",
    }


@server.tool(
    "cellxgene_dataset_info",
    "Return a metadata checklist/provenance skeleton for one CELLxGENE dataset ID. Use after selecting a dataset.",
    {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string"},
            "collection_id": {"type": "string"},
        },
        "required": ["dataset_id"],
    },
)
def cellxgene_dataset_info(dataset_id: str, collection_id: Optional[str] = None):
    params = {"dataset_id": dataset_id, "collection_id": collection_id}
    info_hash = _hash("cellxgene_dataset_info", params)
    return {
        "metadata_hash": info_hash,
        "dataset_id": dataset_id,
        "collection_id": collection_id,
        "fields_to_record": {
            "n_obs": "<FILL>",
            "organism": "<FILL>",
            "tissue": "<FILL>",
            "disease": "<FILL>",
            "assay": "<FILL>",
            "cell_types": "<FILL list>",
            "citation": "<FILL>",
            "license": "<FILL>",
            "schema_version": "<FILL>",
        },
        "provenance_skeleton": {
            "schema": "bio-sc-atlas/dataset-metadata/1",
            "metadata_hash": info_hash,
            "dataset_id": dataset_id,
            "collection_id": collection_id or "<FILL>",
            "retrieved_at": "<FILL ISO8601>",
        },
    }


@server.tool(
    "cellxgene_download_recipe",
    "Generate a NOT-RUNNABLE cellxgene-census SDK download skeleton for selected cells / genes. Heavy download runs on the user's machine.",
    {
        "type": "object",
        "properties": {
            "organism": {"type": "string", "default": "Homo sapiens"},
            "dataset_id": {"type": "string"},
            "obs_value_filter": {"type": "string", "description": "SOMA obs value_filter, e.g. tissue_general == 'lung'."},
            "var_value_filter": {"type": "string", "description": "Optional gene filter."},
            "output_h5ad": {"type": "string", "default": "cellxgene_subset.h5ad"},
        },
    },
)
def cellxgene_download_recipe(
    organism: str = "Homo sapiens",
    dataset_id: Optional[str] = None,
    obs_value_filter: Optional[str] = None,
    var_value_filter: Optional[str] = None,
    output_h5ad: str = "cellxgene_subset.h5ad",
):
    params = {
        "organism": organism,
        "dataset_id": dataset_id,
        "obs_value_filter": obs_value_filter,
        "var_value_filter": var_value_filter,
        "output_h5ad": output_h5ad,
    }
    recipe_hash = _hash("cellxgene_download_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "artifact_type": "skeleton",
        "runnable": False,
        "script": f'''# CELLxGENE Census download skeleton — verify SDK version before running
raise SystemExit("SKELETON: install/pin cellxgene-census, verify filters, then remove this guard")

import cellxgene_census

organism = {organism!r}
obs_value_filter = {obs_value_filter!r}
var_value_filter = {var_value_filter!r}
dataset_id = {dataset_id!r}

with cellxgene_census.open_soma() as census:
    # Optional: inspect census["census_info"]["datasets"] first and confirm dataset_id / citation.
    adata = cellxgene_census.get_anndata(
        census=census,
        organism=organism,
        obs_value_filter=obs_value_filter,
        var_value_filter=var_value_filter,
    )
    if dataset_id:
        adata = adata[adata.obs["dataset_id"] == dataset_id].copy()
    adata.write_h5ad({output_h5ad!r})
''',
        "provenance_skeleton": {
            "schema": "bio-sc-atlas/download-recipe/1",
            "recipe_hash": recipe_hash,
            "dataset_id": dataset_id or "<optional>",
            "filters": {"obs_value_filter": obs_value_filter, "var_value_filter": var_value_filter},
            "output_h5ad_sha256": "<FILL after user run>",
        },
        "warnings": [
            "这会下载真实表达矩阵，可能很大；必须在用户机器上运行。",
            "下载前先记录 dataset citation/license/schema_version。",
        ],
    }


if __name__ == "__main__":
    server.run()
