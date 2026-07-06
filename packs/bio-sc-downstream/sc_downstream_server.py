#!/usr/bin/env python3
"""单细胞下游分析配方 MCP（bio-sc-downstream）。

定位：embedding / clustering / annotation 之后的 scRNA-seq 下游分析配方。
所有工具只生成可复现脚本、参数和 provenance 骨架，不在 MCP 子进程里跑重分析。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import provenance as prov  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-sc-downstream", "0.1.0")


def _recipe_hash(tool: str, params: Dict[str, Any]) -> str:
    return prov.content_hash({"tool": tool, "params": params})


def _prov(tool: str, recipe_hash: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": "bio-sc-downstream/recipe-provenance/1",
        "tool": tool,
        "recipe_hash": recipe_hash,
        "upstream_required": {
            "anndata_fingerprint": "<FILL from bio-singlecell>",
            "preprocessing_recipe_hash": "<FILL from sc_preprocess_recipe>",
            "celltype_annotation_recipe_hash": "<FILL if used>",
        },
        "params": params,
        "run": {"created_at": "<FILL ISO8601>", "executed_by_user": True},
    }


@server.tool(
    "sc_deg_recipe",
    "Generate a scRNA-seq differential expression recipe. Supports pseudobulk DESeq2, scanpy Wilcoxon, and MAST. "
    "Auto mode recommends pseudobulk when biological replicates are adequate.",
    {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["auto", "pseudobulk_deseq2", "wilcoxon", "mast"], "default": "auto"},
            "replicates_per_condition": {"type": "integer", "default": 0},
            "condition_key": {"type": "string", "default": "condition"},
            "sample_key": {"type": "string", "default": "sample_id"},
            "celltype_key": {"type": "string", "default": "cell_type"},
            "contrast": {"type": "array", "items": {"type": "string"}, "description": "[test, reference]"},
            "organism": {"type": "string", "enum": ["human", "mouse"], "default": "human"},
            "seed": {"type": "integer", "default": 0}
        }
    },
)
def sc_deg_recipe(
    method: str = "auto",
    replicates_per_condition: int = 0,
    condition_key: str = "condition",
    sample_key: str = "sample_id",
    celltype_key: str = "cell_type",
    contrast: Optional[List[str]] = None,
    organism: str = "human",
    seed: int = 0,
):
    chosen = "pseudobulk_deseq2" if method == "auto" and replicates_per_condition >= 3 else "wilcoxon" if method == "auto" else method
    params = {
        "method": chosen,
        "replicates_per_condition": replicates_per_condition,
        "condition_key": condition_key,
        "sample_key": sample_key,
        "celltype_key": celltype_key,
        "contrast": contrast or ["case", "control"],
        "organism": organism,
        "seed": seed,
    }
    recipe_hash = _recipe_hash("sc_deg_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "recommended_method": chosen,
        "method_guidance": [
            "pseudobulk_deseq2：推荐 ≥3 biological replicates/condition；按 sample×cell type 聚合 counts 后跑 DESeq2 + apeglm。",
            "wilcoxon：适合 cluster vs rest 或探索性 marker 排序；不能替代有重复样本的严肃 condition DEG。",
            "mast：适合 dropout-heavy 数据和协变量建模，但解释复杂，需记录公式。",
        ],
        "script_language": "r" if chosen in {"pseudobulk_deseq2", "mast"} else "python",
        "script": _render_deg_script(chosen, params),
        "visualizations": ["volcano plot", "dot plot", "heatmap"],
        "provenance_skeleton": _prov("sc_deg_recipe", recipe_hash, params),
        "warnings": _deg_warnings(chosen, replicates_per_condition),
    }


def _deg_warnings(method: str, reps: int) -> List[str]:
    out = []
    if method == "pseudobulk_deseq2" and reps < 3:
        out.append("pseudobulk DESeq2 通常需要每组 ≥3 biological replicates；当前重复数不足时只能作探索性结果。")
    if method == "wilcoxon":
        out.append("Wilcoxon cluster marker 不是 condition-level pseudobulk DEG；不要把细胞数当生物重复。")
    return out


def _render_deg_script(method: str, p: Dict[str, Any]) -> str:
    test, ref = p["contrast"]
    if method == "pseudobulk_deseq2":
        return f'''# sc pseudobulk DEG: sample x cell type aggregation -> DESeq2 -> apeglm
suppressPackageStartupMessages({{
  library(zellkonverter)
  library(SingleCellExperiment)
  library(scuttle)
  library(DESeq2)
  library(apeglm)
  library(ggplot2)
}})
set.seed({p["seed"]})
sce <- readH5AD("celltype_annotated.h5ad")
stopifnot(all(c("{p["sample_key"]}", "{p["condition_key"]}", "{p["celltype_key"]}") %in% colnames(colData(sce))))
stopifnot("counts" %in% assayNames(sce))
meta <- as.data.frame(colData(sce))
sample_condition <- unique(meta[, c("{p["sample_key"]}", "{p["condition_key"]}")])
stopifnot(!any(duplicated(sample_condition[[ "{p["sample_key"]}" ]])))

ids <- DataFrame(sample=meta[[ "{p["sample_key"]}" ]], celltype=meta[[ "{p["celltype_key"]}" ]])
pb <- aggregateAcrossCells(sce, ids=ids, use.assay.type="counts")
pb_meta <- as.data.frame(colData(pb))
dir.create("pseudobulk_deseq2_by_celltype", showWarnings=FALSE)

for (ct in sort(unique(pb_meta$celltype))) {{
  keep <- pb_meta$celltype == ct
  sample_meta <- pb_meta[keep, c("sample", "celltype"), drop=FALSE]
  sample_meta[[ "{p["condition_key"]}" ]] <- sample_condition[[ "{p["condition_key"]}" ]][match(sample_meta$sample, sample_condition[[ "{p["sample_key"]}" ]])]
  sample_meta[[ "{p["condition_key"]}" ]] <- relevel(factor(sample_meta[[ "{p["condition_key"]}" ]]), ref="{ref}")
  reps <- table(sample_meta[[ "{p["condition_key"]}" ]])
  if (!all(c("{test}", "{ref}") %in% names(reps)) || any(reps[c("{test}", "{ref}")] < 3)) {{
    warning(sprintf("Skipping %s: need >=3 biological replicates for both {test} and {ref}", ct))
    next
  }}

  counts_ct <- assay(pb[, keep], "counts")
  rownames(sample_meta) <- colnames(counts_ct)
  dds <- DESeqDataSetFromMatrix(countData=round(counts_ct), colData=sample_meta, design=~{p["condition_key"]})
  dds <- dds[rowSums(counts(dds)) >= 10, ]
  if (nrow(dds) < 10) {{
    warning(sprintf("Skipping %s: fewer than 10 genes after count filtering", ct))
    next
  }}
  dds <- DESeq(dds)
  res <- results(dds, contrast=c("{p["condition_key"]}", "{test}", "{ref}"))
  coef_name <- paste0("{p["condition_key"]}", "_", "{test}", "_vs_", "{ref}")
  if (coef_name %in% resultsNames(dds)) {{
    res <- lfcShrink(dds, coef=coef_name, type="apeglm")
  }} else {{
    warning(sprintf("No matching coefficient %s for apeglm shrinkage in %s; writing unshrunken results", coef_name, ct))
  }}
  safe_ct <- gsub("[^A-Za-z0-9_.-]+", "_", ct)
  write.csv(as.data.frame(res), file.path("pseudobulk_deseq2_by_celltype", paste0(safe_ct, "_{test}_vs_{ref}.csv")))
  write.csv(sample_meta, file.path("pseudobulk_deseq2_by_celltype", paste0(safe_ct, "_sample_meta.csv")))
}}
'''
    if method == "mast":
        return f'''# MAST single-cell DEG skeleton
suppressPackageStartupMessages({{
  library(zellkonverter)
  library(SingleCellExperiment)
  library(MAST)
}})
set.seed({p["seed"]})
sce <- readH5AD("celltype_annotated.h5ad")
sca <- SceToSingleCellAssay(sce)
zlm_fit <- zlm(~ {p["condition_key"]} + cngeneson, sca)
summary_cond <- summary(zlm_fit, doLRT="{p["condition_key"]}{test}")
write.csv(summary_cond$datatable, "mast_results.csv")
'''
    return f'''# scanpy Wilcoxon marker/DEG recipe
import numpy as np
import scanpy as sc
np.random.seed({p["seed"]})
adata = sc.read_h5ad("celltype_annotated.h5ad")
groupby = "{p["celltype_key"]}"
sc.tl.rank_genes_groups(adata, groupby=groupby, method="wilcoxon", pts=True)
sc.pl.rank_genes_groups(adata, n_genes=25, sharey=False, save="_wilcoxon.png")
sc.get.rank_genes_groups_df(adata, group=None).to_csv("wilcoxon_rank_genes_groups.tsv", sep="\\t", index=False)
adata.write_h5ad("deg_wilcoxon_annotated.h5ad")
'''


@server.tool(
    "sc_trajectory_recipe",
    "Generate a trajectory / RNA velocity recipe: scVelo, PAGA, DPT, or Monocle3. Checks spliced/unspliced requirements for scVelo.",
    {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["scvelo", "paga", "dpt", "monocle3"], "default": "scvelo"},
            "has_spliced_unspliced": {"type": "boolean", "default": False},
            "cluster_key": {"type": "string", "default": "cell_type"},
            "root_cell_type": {"type": "string"},
            "seed": {"type": "integer", "default": 0}
        }
    },
)
def sc_trajectory_recipe(
    method: str = "scvelo",
    has_spliced_unspliced: bool = False,
    cluster_key: str = "cell_type",
    root_cell_type: Optional[str] = None,
    seed: int = 0,
):
    params = {"method": method, "has_spliced_unspliced": has_spliced_unspliced, "cluster_key": cluster_key, "root_cell_type": root_cell_type, "seed": seed}
    recipe_hash = _recipe_hash("sc_trajectory_recipe", params)
    warnings = []
    if method == "scvelo" and not has_spliced_unspliced:
        warnings.append("scVelo 需要 spliced/unspliced layers；没有时先用 velocyto 或 STARsolo 重新定量。")
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script_language": "r" if method == "monocle3" else "python",
        "script": _render_trajectory_script(method, cluster_key, root_cell_type, seed),
        "visualizations": ["velocity stream plot", "PAGA graph", "pseudotime coloring"],
        "provenance_skeleton": _prov("sc_trajectory_recipe", recipe_hash, params),
        "warnings": warnings,
    }


def _render_trajectory_script(method: str, cluster_key: str, root_cell_type: Optional[str], seed: int) -> str:
    if method == "scvelo":
        return f'''# scVelo RNA velocity recipe
import numpy as np
import scvelo as scv
np.random.seed({seed})
adata = scv.read("celltype_annotated_with_splicing.h5ad")
assert "spliced" in adata.layers and "unspliced" in adata.layers, "scVelo requires spliced/unspliced layers"
scv.pp.filter_and_normalize(adata)
scv.pp.moments(adata)
scv.tl.velocity(adata, mode="stochastic")
scv.tl.velocity_graph(adata)
scv.tl.latent_time(adata)
scv.pl.velocity_embedding_stream(adata, basis="umap", color="{cluster_key}", save="velocity_stream.png")
adata.write_h5ad("scvelo_velocity.h5ad")
'''
    if method == "paga":
        return f'''# PAGA topology recipe
import numpy as np
import scanpy as sc
np.random.seed({seed})
adata = sc.read_h5ad("celltype_annotated.h5ad")
assert "{cluster_key}" in adata.obs, "missing cluster/cell type key for PAGA"
if "neighbors" not in adata.uns:
    if "X_pca" not in adata.obsm:
        sc.tl.pca(adata, svd_solver="arpack")
    sc.pp.neighbors(adata)
sc.tl.paga(adata, groups="{cluster_key}")
sc.pl.paga(adata, color="{cluster_key}", save="_paga.png")
sc.tl.umap(adata, init_pos="paga")
adata.write_h5ad("paga_trajectory.h5ad")
'''
    if method == "dpt":
        root_line = (
            f'matches = np.flatnonzero(adata.obs["{cluster_key}"].astype(str).to_numpy() == "{root_cell_type}")\n'
            f'assert len(matches) > 0, "root_cell_type {root_cell_type} not found in {cluster_key}"\n'
            'adata.uns["iroot"] = int(matches[0])'
        ) if root_cell_type else "# TODO: set adata.uns['iroot'] to a biologically justified root cell"
        return f'''# Diffusion pseudotime recipe
import numpy as np
import scanpy as sc
np.random.seed({seed})
adata = sc.read_h5ad("celltype_annotated.h5ad")
assert "{cluster_key}" in adata.obs, "missing cluster/cell type key for DPT"
if "neighbors" not in adata.uns:
    if "X_pca" not in adata.obsm:
        sc.tl.pca(adata, svd_solver="arpack")
    sc.pp.neighbors(adata)
sc.tl.diffmap(adata)
{root_line}
sc.tl.dpt(adata)
sc.pl.umap(adata, color=["dpt_pseudotime", "{cluster_key}"], save="_dpt.png")
adata.write_h5ad("dpt_pseudotime.h5ad")
'''
    return f'''# Monocle3 trajectory recipe
suppressPackageStartupMessages({{
  library(zellkonverter)
  library(monocle3)
}})
set.seed({seed})
sce <- readH5AD("celltype_annotated.h5ad")
cds <- as.cell_data_set(sce)
cds <- preprocess_cds(cds)
cds <- reduce_dimension(cds)
cds <- cluster_cells(cds)
cds <- learn_graph(cds)
# TODO: choose root cells based on biology{f" ({root_cell_type})" if root_cell_type else ""}
cds <- order_cells(cds)
saveRDS(cds, "monocle3_cds.rds")
'''


@server.tool(
    "sc_communication_recipe",
    "Generate a cell-cell communication recipe for CellChat, LIANA, or NicheNet. Produces scripts and visualization hooks.",
    {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["cellchat", "liana", "nichenet"], "default": "liana"},
            "celltype_key": {"type": "string", "default": "cell_type"},
            "condition_key": {"type": "string"},
            "organism": {"type": "string", "enum": ["human", "mouse"], "default": "human"},
            "seed": {"type": "integer", "default": 0}
        }
    },
)
def sc_communication_recipe(
    method: str = "liana",
    celltype_key: str = "cell_type",
    condition_key: Optional[str] = None,
    organism: str = "human",
    seed: int = 0,
):
    params = {"method": method, "celltype_key": celltype_key, "condition_key": condition_key, "organism": organism, "seed": seed}
    recipe_hash = _recipe_hash("sc_communication_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script_language": "r" if method in {"cellchat", "nichenet"} else "python",
        "script": _render_communication_script(method, celltype_key, condition_key, organism, seed),
        "visualizations": ["chord diagram", "bubble plot", "signaling pathway heatmap"],
        "provenance_skeleton": _prov("sc_communication_recipe", recipe_hash, params),
        "warnings": [
            "配体-受体通信是基于表达和数据库的推断，不等于实验证明。",
            "必须明确 cell type annotation 来源和过滤阈值；低表达 ligand/receptor 易产生噪音。",
        ],
    }


def _render_communication_script(method: str, celltype_key: str, condition_key: Optional[str], organism: str, seed: int) -> str:
    if method == "liana":
        return f'''# LIANA cell-cell communication recipe
import numpy as np
import scanpy as sc
import liana as li
np.random.seed({seed})
adata = sc.read_h5ad("celltype_annotated.h5ad")
li.mt.rank_aggregate(adata, groupby="{celltype_key}", resource_name="consensus", expr_prop=0.1, verbose=True)
adata.uns["liana_res"].to_csv("liana_rank_aggregate.tsv", sep="\\t", index=False)
# visualization examples: dotplot / tileplot / ligand-receptor bubble plot
'''
    if method == "nichenet":
        return f'''# NicheNet ligand-target recipe
suppressPackageStartupMessages({{
  library(zellkonverter)
  library(nichenetr)
}})
set.seed({seed})
sce <- readH5AD("celltype_annotated.h5ad")
# TODO: define sender/receiver cell types, target gene set, and background genes
# species: {organism}; condition key: {condition_key or "<optional>"}
# output: ligand activity table, ligand-target heatmap
'''
    db = "CellChatDB.human" if organism == "human" else "CellChatDB.mouse"
    return f'''# CellChat communication recipe
suppressPackageStartupMessages({{
  library(zellkonverter)
  library(CellChat)
  library(patchwork)
}})
set.seed({seed})
sce <- readH5AD("celltype_annotated.h5ad")
data.input <- as.matrix(logcounts(sce))
meta <- as.data.frame(colData(sce))
cellchat <- createCellChat(object=data.input, meta=meta, group.by="{celltype_key}")
cellchat@DB <- {db}
cellchat <- subsetData(cellchat)
cellchat <- identifyOverExpressedGenes(cellchat)
cellchat <- identifyOverExpressedInteractions(cellchat)
cellchat <- computeCommunProb(cellchat)
cellchat <- filterCommunication(cellchat, min.cells=10)
cellchat <- computeCommunProbPathway(cellchat)
cellchat <- aggregateNet(cellchat)
saveRDS(cellchat, "cellchat.rds")
'''


@server.tool(
    "sc_marker_recipe",
    "Generate a marker gene analysis recipe: known marker visualization plus new marker discovery via rank_genes_groups.",
    {
        "type": "object",
        "properties": {
            "cluster_key": {"type": "string", "default": "cell_type"},
            "known_marker_file": {"type": "string", "default": "marker_genes.json"},
            "logfc_threshold": {"type": "number", "default": 1.0},
            "padj_threshold": {"type": "number", "default": 0.05},
            "seed": {"type": "integer", "default": 0}
        }
    },
)
def sc_marker_recipe(
    cluster_key: str = "cell_type",
    known_marker_file: str = "marker_genes.json",
    logfc_threshold: float = 1.0,
    padj_threshold: float = 0.05,
    seed: int = 0,
):
    params = {"cluster_key": cluster_key, "known_marker_file": known_marker_file, "logfc_threshold": logfc_threshold, "padj_threshold": padj_threshold, "seed": seed}
    recipe_hash = _recipe_hash("sc_marker_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script": _render_marker_script(params),
        "marker_table_template": ["cluster", "gene", "log2fc", "pct_in", "pct_out", "padj", "hgnc_status", "evidence_note"],
        "bio_gene_handoff": "关键 marker 建议用 bio-gene / bio-norm 的 HGNC 工具核实 current symbol 与 alias。",
        "provenance_skeleton": _prov("sc_marker_recipe", recipe_hash, params),
    }


def _render_marker_script(p: Dict[str, Any]) -> str:
    return f'''# Marker gene visualization + discovery
import json
import numpy as np
import scanpy as sc
np.random.seed({p["seed"]})
adata = sc.read_h5ad("celltype_annotated.h5ad")
cluster_key = "{p["cluster_key"]}"
markers = json.load(open("{p["known_marker_file"]}", encoding="utf-8"))
flat = sorted({{g for genes in markers.values() for g in genes if g in adata.var_names}})
if flat:
    sc.pl.dotplot(adata, flat, groupby=cluster_key, save="_known_markers.png")
    sc.pl.matrixplot(adata, flat, groupby=cluster_key, save="_known_markers.png")
sc.tl.rank_genes_groups(adata, groupby=cluster_key, method="wilcoxon", pts=True)
df = sc.get.rank_genes_groups_df(adata, group=None)
df = df[(df["pvals_adj"] < {p["padj_threshold"]}) & (df["logfoldchanges"].abs() >= {p["logfc_threshold"]})]
df.to_csv("new_marker_candidates.tsv", sep="\\t", index=False)
'''


@server.tool(
    "sc_enrichment_recipe",
    "Generate a single-cell enrichment recipe: per-cluster ORA/GSEA, gene set scoring, AUCell/decoupler-style pathway activity.",
    {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["clusterprofiler", "decoupler", "gsea_scanpy"], "default": "decoupler"},
            "cluster_key": {"type": "string", "default": "cell_type"},
            "gene_set_source": {"type": "string", "default": "MSigDB Hallmark"},
            "organism": {"type": "string", "enum": ["human", "mouse"], "default": "human"},
            "seed": {"type": "integer", "default": 0}
        }
    },
)
def sc_enrichment_recipe(
    method: str = "decoupler",
    cluster_key: str = "cell_type",
    gene_set_source: str = "MSigDB Hallmark",
    organism: str = "human",
    seed: int = 0,
):
    params = {"method": method, "cluster_key": cluster_key, "gene_set_source": gene_set_source, "organism": organism, "seed": seed}
    recipe_hash = _recipe_hash("sc_enrichment_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script_language": "r" if method == "clusterprofiler" else "python",
        "script": _render_enrichment_script(method, cluster_key, gene_set_source, organism, seed),
        "single_cell_specifics": [
            "per-cluster ORA/GSEA 应基于 marker/DEG 列表，而不是所有单细胞当作独立样本。",
            "gene set scoring 可在每个细胞上算 activity，再按 cell type / condition 汇总。",
            "通路解释要记录 gene set 版本、大小阈值和背景基因集。",
        ],
        "provenance_skeleton": _prov("sc_enrichment_recipe", recipe_hash, params),
    }


def _render_enrichment_script(method: str, cluster_key: str, source: str, organism: str, seed: int) -> str:
    if method == "clusterprofiler":
        orgdb = "org.Hs.eg.db" if organism == "human" else "org.Mm.eg.db"
        return f'''# clusterProfiler per-cluster enrichment
suppressPackageStartupMessages({{
  library(clusterProfiler)
  library({orgdb})
}})
set.seed({seed})
markers <- read.table("new_marker_candidates.tsv", sep="\\t", header=TRUE)
# TODO: split markers by cluster, map SYMBOL -> ENTREZID, run enrichGO / GSEA
'''
    if method == "gsea_scanpy":
        return f'''# scanpy gene set scoring
import json
import numpy as np
import scanpy as sc
np.random.seed({seed})
adata = sc.read_h5ad("celltype_annotated.h5ad")
gene_sets = json.load(open("gene_sets.json", encoding="utf-8"))  # source: {source}
for name, genes in gene_sets.items():
    genes = [g for g in genes if g in adata.var_names]
    if genes:
        sc.tl.score_genes(adata, genes, score_name=f"GS_{{name}}")
adata.obs.groupby("{cluster_key}").mean(numeric_only=True).filter(like="GS_").to_csv("gene_set_scores_by_cluster.tsv", sep="\\t")
'''
    return f'''# decoupler pathway / TF activity recipe
import numpy as np
import scanpy as sc
import decoupler as dc
np.random.seed({seed})
adata = sc.read_h5ad("celltype_annotated.h5ad")
# Example resources: MSigDB Hallmark, PROGENy, DoRothEA. Source requested: {source}
net = dc.get_resource("MSigDB")
dc.run_mlm(mat=adata, net=net, source="geneset", target="genesymbol", weight=None, verbose=True)
adata.obsm["mlm_estimate"].to_csv("decoupler_activity.tsv", sep="\\t")
'''


if __name__ == "__main__":
    server.run()
