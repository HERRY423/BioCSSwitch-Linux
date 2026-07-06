#!/usr/bin/env python3
"""scanpy 全流程脚本生成器（QC → preprocess → neighbors/UMAP/Leiden → marker）。

不代跑分析。给用户一份可本地运行的 Python 脚本，包含：
  - AnnData 加载与基础 QC
  - 可选 doublet / batch integration hook
  - normalize/log/HVG/PCA/neighbors/UMAP/Leiden
  - marker gene ranking + dotplot/heatmap
  - provenance JSON（输入描述、参数、seed、脚本版本）

CLI:
    python packs/bio-workflows/generators/sc_scanpy_pipeline.py \
      --h5ad data/pbmc.h5ad --organism human --tissue blood \
      --analysis-goals clustering marker --out scripts/scanpy_pbmc.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


PY_TEMPLATE = '''# ============================================================================
# scanpy scRNA-seq pipeline
# Generator: CSSwitch bio-workflows/generators/sc_scanpy_pipeline.py
# Generated: {ts}
#
# Input h5ad: {h5ad}
# Organism  : {organism}
# Tissue    : {tissue}
# Goals     : {goals}
# Output dir: {outdir}
# ============================================================================

import json
import numpy as np
import scanpy as sc

np.random.seed({seed})
outdir = "{outdir}"

adata = sc.read_h5ad("{h5ad}")
adata.uns["csswitch_scanpy_pipeline"] = {{
    "generator": "bio-workflows/generators/sc_scanpy_pipeline.py",
    "generated_at": "{ts}",
    "organism": "{organism}",
    "tissue": "{tissue}",
    "analysis_goals": {goals_json},
    "seed": {seed},
    "params": {{
        "min_genes": {min_genes},
        "min_cells": {min_cells},
        "n_top_genes": {n_top_genes},
        "n_pcs": {n_pcs},
        "resolution": {resolution}
    }}
}}

# 1. QC
sc.pp.filter_cells(adata, min_genes={min_genes})
sc.pp.filter_genes(adata, min_cells={min_cells})
if "mt" not in adata.var:
    adata.var["mt"] = adata.var_names.str.upper().str.startswith("MT-")
sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], percent_top=None, log1p=False, inplace=True)
adata.obs[["n_genes_by_counts", "total_counts", "pct_counts_mt"]].to_csv(f"{{outdir}}_qc_metrics.tsv", sep="\\t")

# Preserve raw counts before any normalization. If X is already normalized/log-transformed,
# provide adata.layers["counts"] before running this script.
if "counts" not in adata.layers:
    adata.layers["counts"] = adata.X.copy()

{doublet_block}

# 2. Preprocess
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
adata.raw = adata.copy()  # full log-normalized gene space for marker ranking
sc.pp.highly_variable_genes(adata, n_top_genes={n_top_genes}, flavor="seurat_v3", layer="counts")
adata = adata[:, adata.var["highly_variable"]].copy()
sc.pp.scale(adata, max_value=10)
sc.tl.pca(adata, svd_solver="arpack", n_comps={n_pcs})

{batch_block}

# 3. Graph / UMAP / clustering
sc.pp.neighbors(adata, n_pcs={n_pcs}{neighbors_rep})
sc.tl.umap(adata)
sc.tl.leiden(adata, resolution={resolution}, key_added="leiden")
sc.pl.umap(adata, color=["leiden", "n_genes_by_counts", "pct_counts_mt"], save="_scanpy_pipeline.png")

# 4. Marker genes
sc.tl.rank_genes_groups(adata, groupby="leiden", method="wilcoxon", pts=True, use_raw=True)
markers = sc.get.rank_genes_groups_df(adata, group=None)
markers.to_csv(f"{{outdir}}_markers.tsv", sep="\\t", index=False)
sc.pl.rank_genes_groups_dotplot(adata, n_genes=5, use_raw=True, save="_markers.png")

# 5. Provenance
with open(f"{{outdir}}_provenance.json", "w", encoding="utf-8") as f:
    json.dump(adata.uns["csswitch_scanpy_pipeline"], f, ensure_ascii=False, indent=2)
adata.write_h5ad(f"{{outdir}}_processed.h5ad")
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5ad", required=True, help="Input AnnData .h5ad")
    ap.add_argument("--organism", default="human")
    ap.add_argument("--tissue", default="unknown")
    ap.add_argument("--analysis-goals", nargs="+", default=["clustering", "marker"])
    ap.add_argument("--out", type=Path, required=True, help="Output Python script")
    ap.add_argument("--outdir", default="scanpy_out")
    ap.add_argument("--min-genes", type=int, default=200)
    ap.add_argument("--min-cells", type=int, default=3)
    ap.add_argument("--n-top-genes", type=int, default=2000)
    ap.add_argument("--n-pcs", type=int, default=50)
    ap.add_argument("--resolution", type=float, default=1.0)
    ap.add_argument("--include-doublet", action="store_true", help="Add Scrublet hook")
    ap.add_argument("--batch-key", help="Add Harmony batch integration hook")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    doublet_block = ""
    if args.include_doublet:
        doublet_block = '''# Optional doublet hook (requires scrublet)
import scrublet as scr
scrub = scr.Scrublet(adata.layers["counts"] if "counts" in adata.layers else adata.X)
doublet_scores, predicted_doublets = scrub.scrub_doublets()
adata.obs["doublet_score"] = doublet_scores
adata.obs["predicted_doublet"] = predicted_doublets
adata = adata[~adata.obs["predicted_doublet"]].copy()
'''

    batch_block = ""
    neighbors_rep = ""
    if args.batch_key:
        batch_block = f'''# Optional Harmony batch integration hook
import scanpy.external as sce
assert "{args.batch_key}" in adata.obs, "missing batch key"
sce.pp.harmony_integrate(adata, key="{args.batch_key}")
'''
        neighbors_rep = ', use_rep="X_pca_harmony"'

    content = PY_TEMPLATE.format(
        ts=datetime.now().isoformat(timespec="seconds"),
        h5ad=args.h5ad,
        organism=args.organism,
        tissue=args.tissue,
        goals=", ".join(args.analysis_goals),
        goals_json=json.dumps(args.analysis_goals, ensure_ascii=False),
        outdir=args.outdir,
        seed=args.seed,
        min_genes=args.min_genes,
        min_cells=args.min_cells,
        n_top_genes=args.n_top_genes,
        n_pcs=args.n_pcs,
        resolution=args.resolution,
        doublet_block=doublet_block.rstrip(),
        batch_block=batch_block.rstrip(),
        neighbors_rep=neighbors_rep,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(content, "utf-8")
    print(f"[sc_scanpy_pipeline] Python 脚本 → {args.out}")
    print(f"[sc_scanpy_pipeline] 跑：python {args.out}")
    print("必需 Python 包：scanpy numpy；可选：scrublet scanpy.external[harmony]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
