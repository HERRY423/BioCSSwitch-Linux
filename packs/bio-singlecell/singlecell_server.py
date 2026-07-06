#!/usr/bin/env python3
"""单细胞数据处理与配方 MCP（bio-singlecell）。

定位：**给 scRNA-seq / scFM 下游分析准备可复现输入层**，不是替用户跑分析。
工具只产出确定性配方、脚本和 provenance 骨架，实际 scanpy / scvi-tools / R 计算在用户机器上跑。

工具：
  anndata_fingerprint   — AnnData 描述符指纹 + 真·内容哈希 snippet
  sc_qc_thresholds      — MAD-based QC 阈值建议
  sc_preprocess_recipe  — scanpy / Geneformer / scGPT 预处理配方
  sc_doublet_recipe     — Scrublet / scDblFinder doublet 检测配方
  sc_batch_recipe       — Harmony / scVI / BBKNN / Scanorama batch 整合配方
  sc_geneid_convert     — symbol / Ensembl / Entrez ID 转换指南与脚本
  sc_celltype_recipe    — CellTypist / SingleR / marker-based 细胞注释配方
  sc_multimodal_recipe  — CITE-seq / Multiome 预处理配方
  sc_spatial_recipe     — Visium / MERFISH / Slide-seq 空间转录组预处理配方
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import provenance as prov  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-singlecell", "0.2.0")


def _recipe_hash(tool: str, params: Dict[str, Any]) -> str:
    return prov.content_hash({"tool": tool, "params": params})


def _provenance_skeleton(tool: str, recipe_hash: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    skel = {
        "schema": "bio-singlecell/recipe-provenance/1",
        "tool": tool,
        "recipe_hash": recipe_hash,
        "input": {
            "anndata_fingerprint": "<FILL: anndata_fingerprint>",
            "anndata_sha256": "<FILL: true content hash>",
        },
        "run": {
            "created_at": "<FILL: ISO8601>",
            "seed": "<FILL>",
            "executed_by_user": True,
        },
    }
    if extra:
        skel.update(extra)
    return skel


@server.tool(
    "anndata_fingerprint",
    "Fingerprint an AnnData dataset for reproducibility. Takes a DESCRIPTOR (metadata only: n_obs, "
    "n_var, var_id_type, obs/var keys, layers, optional X_checksum) and returns a stable, auditable "
    "fingerprint hash — plus a Python snippet the user runs locally to compute the TRUE content hash.",
    {
        "type": "object",
        "properties": {
            "descriptor": {
                "type": "object",
                "description": "AnnData metadata: n_obs, n_var, var_id_type, obs_keys, var_keys, layers, X_dtype, X_checksum, assay, organism, raw_present.",
            },
            "hash_layer": {
                "type": "string",
                "description": "Which layer the true-hash snippet should hash (default: X).",
            },
        },
        "required": ["descriptor"],
    },
)
def anndata_fingerprint(descriptor: Dict[str, Any], hash_layer: Optional[str] = None):
    fp = prov.hash_descriptor(descriptor)
    warns: List[str] = []
    if not descriptor.get("var_id_type"):
        warns.append("未声明 var_id_type（ensembl / symbol / entrez）——scFM 与下游基因集分析都对基因 ID 类型敏感")
    if not descriptor.get("X_checksum"):
        warns.append("descriptor 未含 X_checksum：当前指纹只覆盖元数据。跑 true_content_hash_snippet 算真·内容哈希后再指纹一次")
    return {
        "fingerprint": fp,
        "descriptor_used": {
            k: descriptor.get(k)
            for k in ("n_obs", "n_var", "var_id_type", "layers", "assay", "organism", "raw_present")
        },
        "true_content_hash_snippet": prov.anndata_hash_snippet(hash_layer),
        "warnings": warns,
        "note": "fingerprint 是元数据级可核对代理；真·内容哈希请用 snippet 在本地算。两者都记进 provenance。",
    }


_DEFAULT_STEPS = [
    {"op": "filter_cells", "min_genes": 200},
    {"op": "filter_genes", "min_cells": 3},
    {"op": "normalize_total", "target_sum": 1e4},
    {"op": "log1p"},
    {"op": "highly_variable_genes", "n_top_genes": 2000, "flavor": "seurat_v3"},
]


@server.tool(
    "sc_preprocess_recipe",
    "Produce a deterministic scanpy preprocessing recipe (params + generated Python script + provenance hash). "
    "Pass target_model for model-appropriate defaults: Geneformer uses rank-value tokenization; scGPT uses HVG + binning.",
    {
        "type": "object",
        "properties": {
            "target_model": {"type": "string", "enum": ["geneformer", "scgpt", "generic"], "default": "generic"},
            "overrides": {"type": "object", "description": "Per-op param overrides."},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def sc_preprocess_recipe(target_model: str = "generic", overrides: Optional[Dict[str, Any]] = None, seed: int = 0):
    steps = [dict(s) for s in _DEFAULT_STEPS]
    notes: List[str] = []
    if target_model == "geneformer":
        steps = [
            {"op": "filter_cells", "min_genes": 200},
            {"op": "filter_genes", "min_cells": 3},
            {"op": "require_ensembl_ids"},
            {"op": "note", "text": "Geneformer 走 rank-value tokenization，不做 normalize/log/HVG；需 Ensembl ID。"},
        ]
        notes.append("Geneformer：跳过 log1p / HVG；基因必须是 Ensembl ID。")
    elif target_model == "scgpt":
        steps = [
            {"op": "filter_cells", "min_genes": 200},
            {"op": "filter_genes", "min_cells": 3},
            {"op": "normalize_total", "target_sum": 1e4},
            {"op": "log1p"},
            {"op": "highly_variable_genes", "n_top_genes": 1200, "flavor": "seurat_v3"},
            {"op": "value_binning", "n_bins": 51},
        ]
        notes.append("scGPT：HVG(~1200) + value binning(51)；基因用 symbol。")
    if overrides:
        for s in steps:
            if s.get("op") in overrides:
                s.update(overrides[s["op"]])
    params = {"target_model": target_model, "seed": seed, "steps": steps}
    recipe_hash = _recipe_hash("sc_preprocess_recipe", params)
    script = _render_scanpy_script(params, recipe_hash)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script": script,
        "provenance_skeleton": _provenance_skeleton("sc_preprocess_recipe", recipe_hash, {"preprocessing": params}),
        "notes": notes,
        "note": "把 recipe_hash 记进 scFM provenance.preprocessing_hash；脚本在用户机器上跑，产物落本地。",
    }


def _render_scanpy_script(params: Dict[str, Any], recipe_hash: str) -> str:
    needs_counts_layer = any(s.get("op") in {"normalize_total", "highly_variable_genes"} for s in params["steps"])
    lines = [
        "# 由 bio-singlecell.sc_preprocess_recipe 生成 —— 确定性预处理，请勿手改参数",
        f"# recipe params hash: {recipe_hash}",
        "import scanpy as sc, numpy as np",
        f"np.random.seed({params.get('seed', 0)})",
        'adata = sc.read_h5ad("YOUR_FILE.h5ad")',
    ]
    if needs_counts_layer:
        lines.extend([
            "# seurat_v3 HVG、Scrublet、scVI 等步骤需要 raw counts；若 X 已经是 log/normalized，请先提供 layers['counts']。",
            "if 'counts' not in adata.layers:",
            "    adata.layers['counts'] = adata.X.copy()",
        ])
    for s in params["steps"]:
        op = s.get("op")
        if op == "filter_cells":
            lines.append(f"sc.pp.filter_cells(adata, min_genes={s.get('min_genes', 200)})")
        elif op == "filter_genes":
            lines.append(f"sc.pp.filter_genes(adata, min_cells={s.get('min_cells', 3)})")
        elif op == "normalize_total":
            lines.append(f"sc.pp.normalize_total(adata, target_sum={s.get('target_sum', 1e4)})")
        elif op == "log1p":
            lines.append("sc.pp.log1p(adata)")
        elif op == "highly_variable_genes":
            flavor = s.get("flavor", "seurat_v3")
            layer_arg = ", layer='counts'" if flavor == "seurat_v3" else ""
            lines.append(f"sc.pp.highly_variable_genes(adata, n_top_genes={s.get('n_top_genes', 2000)}, flavor='{flavor}'{layer_arg})")
        elif op == "value_binning":
            lines.append(f"# scGPT value binning into {s.get('n_bins', 51)} bins（见 scGPT 预处理）")
        elif op == "require_ensembl_ids":
            lines.append("assert adata.var_names.str.startswith('ENSG').mean() > 0.9, 'Geneformer 需要 Ensembl 基因 ID'")
        elif op == "note":
            lines.append(f"# {s.get('text', '')}")
    lines.append('adata.write_h5ad("preprocessed.h5ad")')
    return "\n".join(lines)


@server.tool(
    "sc_qc_thresholds",
    "Suggest MAD-based QC thresholds from per-cell QC summary stats. Explainable: median ± n_mads*MAD.",
    {
        "type": "object",
        "properties": {
            "stats": {
                "type": "object",
                "description": "Per-metric summary: {'pct_counts_mt': {'median':5,'mad':2}}.",
            },
            "n_mads": {"type": "number", "default": 5},
        },
        "required": ["stats"],
    },
)
def sc_qc_thresholds(stats: Dict[str, Any], n_mads: float = 5):
    out: Dict[str, Any] = {}
    for metric, s in (stats or {}).items():
        med = s.get("median")
        mad = s.get("mad")
        if med is None or mad is None:
            out[metric] = {"error": "需要 median 与 mad"}
            continue
        lower = med - n_mads * mad
        upper = med + n_mads * mad
        out[metric] = {
            "lower": round(lower, 4),
            "upper": round(upper, 4),
            "rule": f"median({med}) ± {n_mads}×MAD({mad})",
            "note": "落在 [lower, upper] 之外视为离群，建议剔除；线粒体比例通常只设上界",
        }
    return {"thresholds": out, "n_mads": n_mads, "method": "MAD-based（对离群稳健，优于固定阈值 / 均值±SD）"}


@server.tool(
    "sc_doublet_recipe",
    "Generate a doublet-detection recipe. Default expected_doublet_rate follows the 10x heuristic (~0.8% per 1000 cells). "
    "Produces Scrublet Python or scDblFinder R code + recipe_hash + provenance skeleton.",
    {
        "type": "object",
        "properties": {
            "n_obs": {"type": "integer", "description": "Number of cells before doublet filtering."},
            "expected_doublet_rate": {"type": "number", "description": "Override expected doublet rate, e.g. 0.04."},
            "method": {"type": "string", "enum": ["scrublet", "scdblfinder"], "default": "scrublet"},
            "seed": {"type": "integer", "default": 0},
        },
        "required": ["n_obs"],
    },
)
def sc_doublet_recipe(n_obs: int, expected_doublet_rate: Optional[float] = None, method: str = "scrublet", seed: int = 0):
    inferred = round(min(0.25, max(0.005, 0.008 * (max(n_obs, 1) / 1000.0))), 4)
    rate = expected_doublet_rate if expected_doublet_rate is not None else inferred
    params = {"n_obs": n_obs, "expected_doublet_rate": rate, "method": method, "seed": seed}
    recipe_hash = _recipe_hash("sc_doublet_recipe", params)
    script = _render_scrublet_script(rate, seed) if method == "scrublet" else _render_scdblfinder_script(rate, seed)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "expected_doublet_rate_formula": "~0.8% per 1000 captured cells; clamped to 0.5%-25% unless user overrides",
        "script_language": "python" if method == "scrublet" else "r",
        "script": script,
        "provenance_skeleton": _provenance_skeleton("sc_doublet_recipe", recipe_hash, {"doublet": params}),
        "notes": [
            "默认 Scrublet：Python/scanpy 生态一致，适合 10x scRNA-seq。",
            "scDblFinder：R/Bioconductor 生态，适合 Seurat/SCE 用户；脚本保留阈值可视化。",
            "doublet 判定是过滤建议，不应在对话里假装已经得出 doublet 数量。",
        ],
    }


def _render_scrublet_script(rate: float, seed: int) -> str:
    return f'''# bio-singlecell.sc_doublet_recipe — Scrublet doublet 检测
import numpy as np
import scanpy as sc
import scrublet as scr
import matplotlib.pyplot as plt

np.random.seed({seed})
adata = sc.read_h5ad("preprocessed_or_raw_counts.h5ad")
counts = adata.layers["counts"] if "counts" in adata.layers else adata.X
scrub = scr.Scrublet(counts, expected_doublet_rate={rate})
doublet_scores, predicted_doublets = scrub.scrub_doublets()
adata.obs["doublet_score"] = doublet_scores
adata.obs["predicted_doublet"] = predicted_doublets

plt.hist(doublet_scores, bins=60)
plt.xlabel("Scrublet doublet score")
plt.ylabel("Cells")
plt.savefig("doublet_score_histogram.png", dpi=180, bbox_inches="tight")
adata.write_h5ad("doublet_annotated.h5ad")
'''


def _render_scdblfinder_script(rate: float, seed: int) -> str:
    return f'''# bio-singlecell.sc_doublet_recipe — scDblFinder doublet 检测
suppressPackageStartupMessages({{
  library(SingleCellExperiment)
  library(scDblFinder)
  library(zellkonverter)
  library(ggplot2)
}})
set.seed({seed})
sce <- readH5AD("preprocessed_or_raw_counts.h5ad")
sce <- scDblFinder(sce, dbr={rate})
png("doublet_score_histogram.png", width=900, height=650)
hist(sce$scDblFinder.score, breaks=60, main="scDblFinder doublet score", xlab="score")
dev.off()
writeH5AD(sce, "doublet_annotated.h5ad")
'''


@server.tool(
    "sc_batch_recipe",
    "Generate a batch-integration recipe and method guidance for Harmony, scVI, BBKNN, or Scanorama. "
    "Includes raw-count warnings for scVI and PCA-space warnings for Harmony.",
    {
        "type": "object",
        "properties": {
            "n_batches": {"type": "integer"},
            "batch_key": {"type": "string", "default": "batch"},
            "n_obs_per_batch": {"type": "array", "items": {"type": "integer"}},
            "method": {"type": "string", "enum": ["auto", "harmony", "scvi", "bbknn", "scanorama"], "default": "auto"},
            "target_model": {"type": "string", "description": "Optional downstream model to keep compatible with scFM."},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def sc_batch_recipe(
    n_batches: Optional[int] = None,
    batch_key: str = "batch",
    n_obs_per_batch: Optional[List[int]] = None,
    method: str = "auto",
    target_model: Optional[str] = None,
    seed: int = 0,
):
    inferred_batches = n_batches or (len(n_obs_per_batch or []) or 1)
    total_cells = sum(n_obs_per_batch or []) if n_obs_per_batch else None
    chosen = method if method != "auto" else _choose_batch_method(inferred_batches, total_cells, target_model)
    params = {
        "n_batches": inferred_batches,
        "batch_key": batch_key,
        "n_obs_per_batch": n_obs_per_batch or [],
        "method": chosen,
        "target_model": target_model,
        "seed": seed,
    }
    recipe_hash = _recipe_hash("sc_batch_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "recommended_method": chosen,
        "method_guidance": {
            "harmony": "≤3 个 batch、同 protocol、想快速在 PCA 空间校正时优先；注意 Harmony 操作的是 PCA embedding。",
            "scvi": ">3 batch、跨 protocol/实验室、需要更稳健整合时优先；必须保留 raw counts 层。",
            "bbknn": ">100k cells 或只想轻量调整邻居图时优先；不是表达矩阵校正。",
            "scanorama": "跨数据集 merge、缺少统一 raw counts 时可作为实用选择。",
        },
        "script": _render_batch_script(chosen, batch_key, seed),
        "provenance_skeleton": _provenance_skeleton("sc_batch_recipe", recipe_hash, {"batch_integration": params}),
        "warnings": _batch_warnings(chosen, target_model),
    }


def _choose_batch_method(n_batches: int, total_cells: Optional[int], target_model: Optional[str]) -> str:
    if total_cells and total_cells > 100_000:
        return "bbknn"
    if target_model in {"scvi", "totalvi", "multivi"}:
        return "scvi"
    if n_batches <= 3:
        return "harmony"
    return "scvi"


def _batch_warnings(method: str, target_model: Optional[str]) -> List[str]:
    out = []
    if method == "scvi":
        out.append("scVI 需要 raw counts 层；不要把 log-normalized 矩阵当 counts。")
    if method == "harmony":
        out.append("Harmony 在 PCA 空间操作，适合校正 embedding/邻居图，不会生成 corrected counts。")
    if target_model:
        out.append(f"若下游要跑 {target_model}，保留未整合的 raw/counts 层与整合后的 embedding，避免覆盖输入。")
    return out


def _render_batch_script(method: str, batch_key: str, seed: int) -> str:
    common = [
        "# bio-singlecell.sc_batch_recipe — batch integration",
        "import numpy as np",
        "import scanpy as sc",
        f"np.random.seed({seed})",
        'adata = sc.read_h5ad("doublet_annotated_or_preprocessed.h5ad")',
        f"batch_key = '{batch_key}'",
        "assert batch_key in adata.obs, f'missing batch_key: {batch_key}'",
    ]
    if method == "harmony":
        body = [
            "import scanpy.external as sce",
            "sc.tl.pca(adata, svd_solver='arpack')",
            "sce.pp.harmony_integrate(adata, key=batch_key)",
            "sc.pp.neighbors(adata, use_rep='X_pca_harmony')",
        ]
    elif method == "scvi":
        body = [
            "import scvi",
            "assert 'counts' in adata.layers, 'scVI integration requires raw counts in adata.layers[\"counts\"]; do not use log-normalized X as counts'",
            "scvi.model.SCVI.setup_anndata(adata, layer='counts', batch_key=batch_key)",
            "model = scvi.model.SCVI(adata, n_latent=30)",
            "model.train(max_epochs=400)",
            "adata.obsm['X_scVI'] = model.get_latent_representation()",
            "sc.pp.neighbors(adata, use_rep='X_scVI')",
        ]
    elif method == "bbknn":
        body = [
            "import bbknn",
            "sc.tl.pca(adata, svd_solver='arpack')",
            "bbknn.bbknn(adata, batch_key=batch_key)",
        ]
    else:
        body = [
            "import scanpy.external as sce",
            "sce.pp.scanorama_integrate(adata, key=batch_key)",
            "sc.pp.neighbors(adata, use_rep='X_scanorama')",
        ]
    tail = ["sc.tl.umap(adata)", f'adata.write_h5ad("batch_integrated_{method}.h5ad")']
    return "\n".join(common + body + tail)


@server.tool(
    "sc_geneid_convert",
    "Generate a gene ID conversion guide/script for symbol, Ensembl, and Entrez IDs. Includes multi-mapping warnings and bio-gene handoff.",
    {
        "type": "object",
        "properties": {
            "source_id_type": {"type": "string", "enum": ["symbol", "ensembl", "entrez"]},
            "target_id_type": {"type": "string", "enum": ["symbol", "ensembl", "entrez"]},
            "organism": {"type": "string", "enum": ["human", "mouse"], "default": "human"},
            "strategy": {"type": "string", "enum": ["mygene", "biomart", "hgnc_file"], "default": "mygene"},
        },
        "required": ["source_id_type", "target_id_type"],
    },
)
def sc_geneid_convert(source_id_type: str, target_id_type: str, organism: str = "human", strategy: str = "mygene"):
    params = {"source_id_type": source_id_type, "target_id_type": target_id_type, "organism": organism, "strategy": strategy}
    recipe_hash = _recipe_hash("sc_geneid_convert", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script": _render_geneid_script(source_id_type, target_id_type, organism, strategy),
        "pitfalls": [
            "一对多 / 多对一映射必须保留 audit 表，不要静默丢弃。",
            "Ensembl 版本后缀（如 ENSG... .12）应先剥离再映射，同时记录原始 ID。",
            "deprecated symbols / alias 可能导致错误合并；人类基因可用 HGNC current symbol 表核对。",
        ],
        "bio_gene_handoff": "个别关键基因可调用 bio-gene 的 ensembl_lookup_by_symbol / ensembl_lookup_by_id 核实。",
        "provenance_skeleton": _provenance_skeleton("sc_geneid_convert", recipe_hash, {"gene_id_mapping": params}),
    }


def _render_geneid_script(source: str, target: str, organism: str, strategy: str) -> str:
    species = "human" if organism == "human" else "mouse"
    if strategy == "hgnc_file":
        return f'''# HGNC 文件映射方案（无 API，适合可复现归档）
import pandas as pd
ids = pd.read_csv("gene_ids.tsv", sep="\\t")  # column: gene_id
hgnc = pd.read_csv("hgnc_complete_set.txt", sep="\\t", dtype=str)
hgnc["ensembl_gene_id"] = hgnc["ensembl_gene_id"].str.replace(r"\\.\\d+$", "", regex=True)
mapping = hgnc[["symbol", "ensembl_gene_id", "entrez_id", "prev_symbol", "alias_symbol"]].copy()
# TODO: map {source} -> {target}; 保留 unmatched 与 multi-mapping 审计表
'''
    if strategy == "biomart":
        return f'''# pybiomart 映射方案：{source} -> {target} ({species})
import pandas as pd
from pybiomart import Server
ids = pd.read_csv("gene_ids.tsv", sep="\\t")["gene_id"].astype(str)
server = Server(host="http://www.ensembl.org")
dataset = server.marts["ENSEMBL_MART_ENSEMBL"].datasets["{'hsapiens_gene_ensembl' if species == 'human' else 'mmusculus_gene_ensembl'}"]
attrs = ["ensembl_gene_id", "external_gene_name", "entrezgene_id"]
bm = dataset.query(attributes=attrs)
# TODO: normalize columns and merge; 输出 mapped.tsv / unmapped.tsv / multimapped.tsv
'''
    return f'''# mygene 映射方案：{source} -> {target} ({species})
import pandas as pd
import mygene
mg = mygene.MyGeneInfo()
ids = pd.read_csv("gene_ids.tsv", sep="\\t")["gene_id"].astype(str).str.replace(r"\\.\\d+$", "", regex=True)
scope = {{"symbol": "symbol", "ensembl": "ensembl.gene", "entrez": "entrezgene"}}["{source}"]
field = {{"symbol": "symbol", "ensembl": "ensembl.gene", "entrez": "entrezgene"}}["{target}"]
res = mg.querymany(ids.tolist(), scopes=scope, fields=field + ",symbol,entrezgene,ensembl.gene", species="{species}", as_dataframe=True)
res.to_csv("gene_id_mapping_audit.tsv", sep="\\t")
# 检查 duplicated query / notfound / 多对多映射后，再写回 adata.var
'''


@server.tool(
    "sc_celltype_recipe",
    "Generate a cell-type annotation recipe for CellTypist, SingleR, or marker-based scoring. Includes QC visualizations.",
    {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["celltypist", "singler", "marker_based"], "default": "celltypist"},
            "organism": {"type": "string", "enum": ["human", "mouse"], "default": "human"},
            "tissue": {"type": "string"},
            "reference_dataset": {"type": "string"},
            "embedding_key": {"type": "string", "default": "X_umap"},
        },
    },
)
def sc_celltype_recipe(
    method: str = "celltypist",
    organism: str = "human",
    tissue: Optional[str] = None,
    reference_dataset: Optional[str] = None,
    embedding_key: str = "X_umap",
):
    ref = reference_dataset or _default_celltype_reference(method, organism, tissue)
    params = {"method": method, "organism": organism, "tissue": tissue, "reference_dataset": ref, "embedding_key": embedding_key}
    recipe_hash = _recipe_hash("sc_celltype_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "recommended_reference": ref,
        "script": _render_celltype_script(method, organism, ref, embedding_key),
        "qc_outputs": ["confidence score distribution", "UMAP colored by predicted cell type", "confusion/cross-tab by cluster"],
        "cellxgene_hint": "可用 bio-sc-atlas 的 cellxgene_search 按 tissue/organism/disease 找参考数据集。",
        "provenance_skeleton": _provenance_skeleton("sc_celltype_recipe", recipe_hash, {"celltype_annotation": params}),
    }


def _default_celltype_reference(method: str, organism: str, tissue: Optional[str]) -> str:
    t = (tissue or "").lower()
    if method == "celltypist":
        if "blood" in t or "pbmc" in t or "immune" in t:
            return "Immune_All_Low.pkl"
        if "lung" in t:
            return "Healthy_Lung.pkl"
        return "Human_AdultAged_Hematopoietic.pkl" if organism == "human" else "Mouse_Whole_Brain.pkl"
    if method == "singler":
        return "HumanPrimaryCellAtlasData" if organism == "human" else "MouseRNAseqData"
    return "user_supplied_marker_gene_dict"


def _render_celltype_script(method: str, organism: str, ref: str, embedding_key: str) -> str:
    if method == "celltypist":
        return f'''# CellTypist annotation
import scanpy as sc
import celltypist
from celltypist import models
adata = sc.read_h5ad("batch_integrated_or_preprocessed.h5ad")
models.download_models(force_update=False)
pred = celltypist.annotate(adata, model="{ref}", majority_voting=True)
adata = pred.to_adata()
sc.pl.umap(adata, color=["majority_voting", "conf_score"], save="_celltypist.png")
adata.obs[["majority_voting", "conf_score"]].to_csv("celltypist_predictions.tsv", sep="\\t")
adata.write_h5ad("celltype_annotated.h5ad")
'''
    if method == "singler":
        return f'''# SingleR annotation ({organism})
suppressPackageStartupMessages({{
  library(SingleR)
  library(zellkonverter)
  library(SingleCellExperiment)
  library(celldex)
}})
sce <- readH5AD("batch_integrated_or_preprocessed.h5ad")
ref <- celldex::{ref}()
pred <- SingleR(test=sce, ref=ref, labels=ref$label.main)
sce$SingleR_label <- pred$labels
write.table(as.data.frame(pred), "singler_predictions.tsv", sep="\\t", quote=FALSE)
writeH5AD(sce, "celltype_annotated.h5ad")
'''
    return f'''# Marker-based annotation
import json
import scanpy as sc
adata = sc.read_h5ad("batch_integrated_or_preprocessed.h5ad")
markers = json.load(open("marker_genes.json", encoding="utf-8"))
for cell_type, genes in markers.items():
    genes = [g for g in genes if g in adata.var_names]
    if genes:
        sc.tl.score_genes(adata, genes, score_name=f"score_{{cell_type}}")
sc.pl.umap(adata, color=[c for c in adata.obs.columns if c.startswith("score_")], save="_marker_scores.png")
adata.write_h5ad("marker_scored.h5ad")
# embedding key expected: {embedding_key}
'''


@server.tool(
    "sc_multimodal_recipe",
    "Generate CITE-seq or multiome preprocessing recipes: CLR/DSB for ADT, WNN/totalVI, TF-IDF/LSI/MultiVI for ATAC.",
    {
        "type": "object",
        "properties": {
            "modality": {"type": "string", "enum": ["cite_seq", "multiome"], "default": "cite_seq"},
            "method": {"type": "string", "enum": ["auto", "wnn", "totalvi", "multivi", "signac"], "default": "auto"},
            "rna_layer": {"type": "string", "default": "counts"},
            "protein_obsm": {"type": "string", "default": "protein_expression"},
            "batch_key": {"type": "string"},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def sc_multimodal_recipe(
    modality: str = "cite_seq",
    method: str = "auto",
    rna_layer: str = "counts",
    protein_obsm: str = "protein_expression",
    batch_key: Optional[str] = None,
    seed: int = 0,
):
    chosen = "totalvi" if modality == "cite_seq" and method == "auto" else "multivi" if method == "auto" else method
    params = {"modality": modality, "method": chosen, "rna_layer": rna_layer, "protein_obsm": protein_obsm, "batch_key": batch_key, "seed": seed}
    recipe_hash = _recipe_hash("sc_multimodal_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script": _render_multimodal_script(modality, chosen, rna_layer, protein_obsm, batch_key, seed),
        "notes": [
            "CITE-seq ADT 推荐 CLR 或 DSB normalization，并保留 RNA raw counts。",
            "Multiome ATAC 侧需 TF-IDF + LSI / peak calling / gene activity；MultiVI 需要 modality 标注。",
            "totalVI/MultiVI 是每份数据自训 baseline，不是预训练 foundation model。",
        ],
        "provenance_skeleton": _provenance_skeleton("sc_multimodal_recipe", recipe_hash, {"multimodal_preprocessing": params}),
    }


def _render_multimodal_script(modality: str, method: str, rna_layer: str, protein_obsm: str, batch_key: Optional[str], seed: int) -> str:
    if modality == "cite_seq":
        return f'''# CITE-seq preprocessing: RNA + ADT
import numpy as np
import scanpy as sc
np.random.seed({seed})
adata = sc.read_h5ad("cite_seq.h5ad")
if "{rna_layer}" not in adata.layers:
    # Assumes X is raw RNA counts. If X is already normalized/log-transformed, create {rna_layer} from raw counts first.
    adata.layers["{rna_layer}"] = adata.X.copy()
# RNA: standard scanpy
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=3000, flavor="seurat_v3", layer="{rna_layer}")
# ADT: CLR normalization / optional DSB normalization
protein = adata.obsm["{protein_obsm}"]
# TODO: apply CLR normalization to ADT matrix; DSB requires empty-droplet/background controls
# totalVI joint model
import scvi
scvi.model.TOTALVI.setup_anndata(adata, layer="{rna_layer}", protein_expression_obsm_key="{protein_obsm}"{", batch_key='" + batch_key + "'" if batch_key else ""})
model = scvi.model.TOTALVI(adata)
model.train()
adata.obsm["X_totalVI"] = model.get_latent_representation()
adata.write_h5ad("cite_seq_totalvi.h5ad")
'''
    return f'''# Multiome preprocessing: RNA + ATAC
import numpy as np
import scanpy as sc
np.random.seed({seed})
adata = sc.read_h5ad("multiome_rna_atac.h5ad")
if "counts" not in adata.layers:
    # Assumes X is raw RNA counts. If X is already normalized/log-transformed, create counts from raw RNA first.
    adata.layers["counts"] = adata.X.copy()
# RNA: standard scanpy preprocessing
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=3000, flavor="seurat_v3", layer="counts")
# ATAC: TF-IDF + LSI / peak calling / gene activity should be run with muon, episcanpy, ArchR or Signac.
# MultiVI joint model skeleton
import scvi
scvi.model.MULTIVI.setup_anndata(adata, batch_key={repr(batch_key)} if {repr(batch_key)} else None)
model = scvi.model.MULTIVI(adata)
model.train()
adata.obsm["X_multiVI"] = model.get_latent_representation()
adata.write_h5ad("multiome_multivi.h5ad")
'''


@server.tool(
    "sc_spatial_recipe",
    "Generate spatial transcriptomics preprocessing recipes for Visium, MERFISH/seqFISH, or Slide-seq using squidpy-style workflows.",
    {
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": ["visium", "merfish", "seqfish", "slideseq"], "default": "visium"},
            "organism": {"type": "string", "enum": ["human", "mouse"], "default": "human"},
            "has_image": {"type": "boolean", "default": True},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def sc_spatial_recipe(platform: str = "visium", organism: str = "human", has_image: bool = True, seed: int = 0):
    params = {"platform": platform, "organism": organism, "has_image": has_image, "seed": seed}
    recipe_hash = _recipe_hash("sc_spatial_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script": _render_spatial_script(platform, has_image, seed),
        "notes": [
            "Visium：squidpy spatial neighbors、Moran's I、neighborhood enrichment 是轻量起点。",
            "MERFISH/seqFISH：先确认 cell segmentation 与 molecule assignment，不能只按 count matrix 下结论。",
            "Slide-seq：需要 bead/cell 坐标；空间邻域半径应按平台分辨率设置。",
        ],
        "provenance_skeleton": _provenance_skeleton("sc_spatial_recipe", recipe_hash, {"spatial_preprocessing": params}),
    }


def _render_spatial_script(platform: str, has_image: bool, seed: int) -> str:
    if platform == "visium":
        loader = 'adata = sq.read.visium("SPACERANGER_OUT_DIR")' if has_image else 'adata = sc.read_h5ad("visium_counts_with_spatial.h5ad")'
    else:
        loader = 'adata = sc.read_h5ad("spatial_counts_with_xy.h5ad")  # must include adata.obsm["spatial"]'
    return f'''# Spatial transcriptomics preprocessing ({platform})
import numpy as np
import scanpy as sc
import squidpy as sq
np.random.seed({seed})
{loader}
sc.pp.filter_genes(adata, min_cells=3)
if "counts" not in adata.layers:
    adata.layers["counts"] = adata.X.copy()
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=3000, flavor="seurat_v3", layer="counts")
sc.tl.pca(adata)
sc.pp.neighbors(adata)
sc.tl.leiden(adata, key_added="leiden")
sc.tl.umap(adata)
sq.gr.spatial_neighbors(adata)
sq.gr.spatial_autocorr(adata, mode="moran")
sq.gr.nhood_enrichment(adata, cluster_key="leiden")
sq.pl.spatial_scatter(adata, color=["leiden"], save="_spatial_clusters.png")
adata.write_h5ad("spatial_preprocessed.h5ad")
'''


if __name__ == "__main__":
    server.run()
