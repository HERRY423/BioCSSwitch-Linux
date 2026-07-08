#!/usr/bin/env python3
"""Spatial transcriptomics recipe MCP (bio-spatial).

The tools here follow the BioCSSwitch rule: do not run heavy analysis in the
MCP subprocess. They produce deterministic recipe hashes, scripts/skeletons,
and provenance templates that the user runs locally.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import provenance as prov  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-spatial", "0.2.0")


_PLATFORMS: Dict[str, Dict[str, Any]] = {
    "visium": {
        "assay_class": "spot-based whole transcriptome",
        "resolution": "multi-cell spots",
        "strengths": ["whole-transcriptome coverage", "mature ecosystem", "histology alignment"],
        "failure_modes": ["mixed-cell spots", "lower single-cell specificity", "spot-level deconvolution required"],
        "best_for": ["broad tissue architecture", "discovery scans", "paired histology studies"],
    },
    "visium_hd": {
        "assay_class": "high-resolution whole transcriptome",
        "resolution": "near-cellular bins",
        "strengths": ["whole-transcriptome coverage", "near-cellular spatial grid"],
        "failure_modes": ["sparsity", "bin-size sensitivity", "newer computational defaults"],
        "best_for": ["rare-region screening", "whole-transcriptome niche discovery"],
    },
    "xenium": {
        "assay_class": "imaging-based targeted panel",
        "resolution": "single-cell / subcellular molecules",
        "strengths": ["low-background targeted signal", "cell segmentation", "molecule-level coordinates"],
        "failure_modes": ["panel-limited genes", "segmentation bias", "neighbor contamination"],
        "best_for": ["orthogonal validation", "rare cell localization", "niche marker checks"],
    },
    "cosmx": {
        "assay_class": "imaging-based targeted panel",
        "resolution": "single-cell / subcellular molecules",
        "strengths": ["large targeted panels", "cell segmentation", "subcellular molecule coordinates"],
        "failure_modes": ["background/specificity must be audited", "segmentation-sensitive counts"],
        "best_for": ["targeted spatial validation", "immune/tumor microenvironment panels"],
    },
    "merfish": {
        "assay_class": "multiplexed imaging",
        "resolution": "single-cell / subcellular molecules",
        "strengths": ["high molecule localization precision", "custom gene panels", "3D-capable designs"],
        "failure_modes": ["panel design bias", "segmentation and decoding QC dominate"],
        "best_for": ["3D/subcellular atlas work", "mechanistic niche mapping"],
    },
    "slideseq": {
        "assay_class": "bead-based high-resolution capture",
        "resolution": "near-cellular bead coordinates",
        "strengths": ["high spatial density", "whole-transcriptome-like discovery"],
        "failure_modes": ["bead registration", "capture efficiency variation", "coordinate QC"],
        "best_for": ["fine-grained tissue gradients", "discovery when imaging panels are too narrow"],
    },
    "stereo_seq": {
        "assay_class": "ultra-dense sequencing-based spatial barcoding",
        "resolution": "near single-cell to subcellular bins",
        "strengths": ["large field of view", "whole-transcriptome discovery", "3D atlas compatibility"],
        "failure_modes": ["binning sensitivity", "registration and section warping", "sparsity at small bins"],
        "best_for": ["organ-scale atlases", "fine tissue gradients", "serial-section reconstruction"],
    },
    "dbit_seq": {
        "assay_class": "microfluidic spatial barcoding",
        "resolution": "grid pixels / regions",
        "strengths": ["whole-transcriptome readout", "spatial multi-omics extensions", "custom tissue workflows"],
        "failure_modes": ["pixel mixing", "microfluidic alignment", "lower intrinsic single-cell specificity"],
        "best_for": ["method development", "multi-omic discovery", "hypothesis-driven tissue maps"],
    },
    "geomx": {
        "assay_class": "region-of-interest digital spatial profiling",
        "resolution": "user-defined ROIs",
        "strengths": ["FFPE-friendly", "protein plus RNA panels", "pathologist-guided ROI selection"],
        "failure_modes": ["ROI selection bias", "not single-cell by default", "limited coordinate graph structure"],
        "best_for": ["clinical-adjacent cohorts", "hypothesis-driven ROI comparisons", "protein/RNA validation"],
    },
    "raefish": {
        "assay_class": "sequencing-free single-molecule imaging",
        "resolution": "single-molecule / subcellular",
        "strengths": ["emerging genome-scale coverage", "molecule-level localization", "no NGS readout"],
        "failure_modes": ["early-method benchmarking gaps", "decoding error audit", "throughput and protocol maturity"],
        "best_for": ["single-molecule whole-genome spatial assays", "subcellular transcript organization"],
    },
    "seqfish": {
        "assay_class": "multiplexed imaging",
        "resolution": "single-molecule / subcellular",
        "strengths": ["combinatorial barcoding", "subcellular localization", "custom panels"],
        "failure_modes": ["optical cycle errors", "panel design bias", "segmentation and decoding QC"],
        "best_for": ["subcellular maps", "developmental and neural architecture", "targeted mechanistic studies"],
    },
    "starmap": {
        "assay_class": "in situ sequencing / imaging",
        "resolution": "single-cell / subcellular",
        "strengths": ["intact-tissue molecular maps", "3D-capable imaging designs", "cellular neighborhood detail"],
        "failure_modes": ["targeted panel limits", "image decoding QC", "tissue clearing and registration effects"],
        "best_for": ["neuroscience", "3D tissue architecture", "mechanistic niche mapping"],
    },
}


_PLATFORM_ALIASES = {
    "slide_seq": "slideseq",
    "slide_seqv2": "slideseq",
    "slide_seq_v2": "slideseq",
    "visiumhd": "visium_hd",
    "visium_hd": "visium_hd",
    "stereo_seq": "stereo_seq",
    "stereoseq": "stereo_seq",
    "dbit_seq": "dbit_seq",
    "dbitseq": "dbit_seq",
    "geo_mx": "geomx",
    "geomx_dsp": "geomx",
    "seqfish_plus": "seqfish",
    "seqfish+": "seqfish",
    "star_map": "starmap",
}


_IMAGING_PLATFORMS = {"xenium", "cosmx", "merfish", "raefish", "seqfish", "starmap"}
_SPOT_PLATFORMS = {"visium", "visium_hd", "slideseq", "stereo_seq", "dbit_seq"}
_ROI_PLATFORMS = {"geomx"}
_HIGH_RESOLUTION_PLATFORMS = {
    "visium_hd",
    "xenium",
    "cosmx",
    "merfish",
    "raefish",
    "seqfish",
    "starmap",
    "stereo_seq",
    "slideseq",
}
_SUPPORTED_PLATFORMS = sorted(_PLATFORMS)


_MODALITY_GUIDANCE: Dict[str, Dict[str, Any]] = {
    "transcriptome": {
        "common_inputs": ["raw counts", "gene identifiers", "spatial coordinates"],
        "qc": ["library size", "gene-count distribution", "ambient/background signal"],
        "integration_note": "Keep raw counts and normalized expression separate.",
    },
    "protein": {
        "common_inputs": ["antibody counts", "negative/isotype controls", "panel metadata"],
        "qc": ["antibody background", "spillover or bleed-through", "batch/panel lot effects"],
        "integration_note": "Protein can validate post-transcriptional states invisible to RNA alone.",
    },
    "atac": {
        "common_inputs": ["peak matrix", "fragment counts", "peak-to-gene links"],
        "qc": ["TSS enrichment", "FRiP", "peak calling consistency"],
        "integration_note": "Use gene activity scores and peak-to-gene provenance, not RNA-only labels.",
    },
    "metabolomics": {
        "common_inputs": ["ion images", "metabolite annotations", "mass accuracy metadata"],
        "qc": ["mass calibration", "annotation confidence", "batch drift"],
        "integration_note": "Treat metabolite identity confidence as part of the evidence level.",
    },
    "lipidomics": {
        "common_inputs": ["lipid ion maps", "annotation confidence", "normalization metadata"],
        "qc": ["adduct handling", "isobaric ambiguity", "ion suppression"],
        "integration_note": "Report lipid class and annotation confidence alongside spatial enrichment.",
    },
    "histology": {
        "common_inputs": ["H&E or IF image", "tile manifest", "registration transform"],
        "qc": ["stain normalization", "focus/tissue folds", "registration residuals"],
        "integration_note": "Never let tile-level splits leak tissue or donor identity across train/test.",
    },
}


_SPATIAL_MODELS: Dict[str, Dict[str, Any]] = {
    "scgpt_spatial": {
        "family": "spatial expression foundation model",
        "inputs": ["gene expression", "platform/protocol metadata", "spatial profiles"],
        "use_when": ["zero-shot or fine-tuned spatial cell representation", "protocol-aware benchmarking"],
        "baseline": "scVI plus platform-stratified marker scoring",
        "script_status": "skeleton; verify current official API before running",
    },
    "nicheformer": {
        "family": "joint dissociated + spatial representation model",
        "inputs": ["single-cell expression", "spatial expression", "cell/niche context"],
        "use_when": ["joint scRNA-seq and spatial reference mapping", "niche-aware embeddings"],
        "baseline": "cell2location/RCTD plus scVI",
        "script_status": "skeleton; verify current official API before running",
    },
    "cellama": {
        "family": "cell sentence / metadata-aware representation",
        "inputs": ["expression summary", "metadata", "optional niche context"],
        "use_when": ["zero-shot reference mapping", "metadata-rich atlas harmonization"],
        "baseline": "CellTypist/SingleR plus marker scoring",
        "script_status": "skeleton; verify current official API before running",
    },
    "storm": {
        "family": "histology + spatial multimodal model",
        "inputs": ["spatial expression", "H&E image tiles"],
        "use_when": ["histology-aligned prediction", "therapy-response style multimodal studies"],
        "baseline": "squidpy image features plus expression-only model",
        "script_status": "skeleton; verify current official API before running",
    },
    "novae": {
        "family": "graph spatial representation",
        "inputs": ["spatial graph", "expression"],
        "use_when": ["neighborhood graph embeddings", "spatial domain discovery"],
        "baseline": "squidpy neighbors plus Leiden/PAGA",
        "script_status": "skeleton; verify current official API before running",
    },
    "past": {
        "family": "pathology-fused spatial model",
        "inputs": ["spatial expression", "histology features"],
        "use_when": ["pathology-aware spatial embedding", "histology-expression fusion"],
        "baseline": "expression-only embedding plus image-feature ablation",
        "script_status": "skeleton; verify current official API before running",
    },
    "histology_to_st": {
        "family": "virtual spatial transcriptomics / histology prediction",
        "inputs": ["H&E image tiles", "matched spatial expression", "registration transforms"],
        "use_when": ["retrospective pathology cohorts", "biomarker recovery from standard slides", "cost-sensitive screening"],
        "baseline": "tile morphology features plus expression-only and shuffled-label controls",
        "script_status": "skeleton; verify current official API and leakage controls before running",
    },
}


def _recipe_hash(tool: str, params: Dict[str, Any]) -> str:
    return prov.content_hash({"tool": tool, "params": params})


def _normalize_platform(platform: str) -> str:
    key = (platform or "").strip().lower().replace("-", "_").replace(" ", "_").replace("/", "_")
    key = key.replace("__", "_")
    return _PLATFORM_ALIASES.get(key, key)


def _provenance(tool: str, recipe_hash: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": "bio-spatial/recipe-provenance/1",
        "tool": tool,
        "recipe_hash": recipe_hash,
        "input": {
            "anndata_fingerprint": "<FILL from bio-singlecell>",
            "anndata_sha256": "<FILL true content hash>",
            "spatial_coordinate_hash": "<FILL if coordinate table is separate>",
            "image_sha256": "<FILL if histology/image is used>",
        },
        "params": params,
        "run": {"created_at": "<FILL ISO8601>", "executed_by_user": True},
    }


def _platform_names(platforms: Optional[List[str]]) -> List[str]:
    if not platforms:
        return sorted(_PLATFORMS)
    chosen = []
    for p in platforms:
        key = _normalize_platform(p)
        if key in _PLATFORMS and key not in chosen:
            chosen.append(key)
    return chosen


@server.tool(
    "spatial_platform_matrix",
    "Return a platform-aware spatial transcriptomics comparison matrix and QC decision guide. Use before mixing "
    "Visium/Visium HD/Xenium/CosMx/MERFISH/Stereo-seq/GeoMx-style data or making rare-cell claims.",
    {
        "type": "object",
        "properties": {
            "platforms": {"type": "array", "items": {"type": "string"}},
            "tissue": {"type": "string", "default": "generic"},
            "goal": {"type": "string", "default": "platform_selection"},
        },
    },
)
def spatial_platform_matrix(platforms: Optional[List[str]] = None, tissue: str = "generic", goal: str = "platform_selection"):
    chosen = _platform_names(platforms)
    rows = []
    for p in chosen:
        item = dict(_PLATFORMS[p])
        item["platform"] = p
        rows.append(item)
    return {
        "platforms": rows,
        "goal": goal,
        "tissue": tissue,
        "decision_rules": [
            "Use whole-transcriptome spot/bin platforms for discovery; use imaging platforms for targeted orthogonal validation.",
            "Keep platform as an explicit covariate; do not pool Visium, Xenium and CosMx counts without platform-stratified QC.",
            "For rare cells, require a marker-score baseline and at least one orthogonal check before claiming a new population.",
            "Audit segmentation quality and neighbor contamination for imaging platforms before interpreting niche enrichment.",
            "For Visium HD, report bin size and sparsity diagnostics because conclusions can change with binning choices.",
            "For ROI platforms, report ROI selection criteria and pathologist/blinded annotation rules before cohort claims.",
            "For same-slide multi-omics, track modality-specific controls; do not treat RNA/protein/ATAC evidence as interchangeable.",
        ],
        "method_families": [
            {
                "family": "imaging-based single-molecule / in situ",
                "platforms": sorted(_IMAGING_PLATFORMS),
                "core_tradeoff": "highest resolution, but panel/decoding/segmentation QC can dominate interpretation",
            },
            {
                "family": "sequencing-based spatial barcoding",
                "platforms": sorted(_SPOT_PLATFORMS),
                "core_tradeoff": "whole-transcriptome discovery, but bin/spot mixing and sparsity need explicit modeling",
            },
            {
                "family": "ROI / microdissection",
                "platforms": sorted(_ROI_PLATFORMS),
                "core_tradeoff": "clinical and hypothesis-driven flexibility, but ROI selection bias must be controlled",
            },
        ],
        "trend_map": {
            "resolution_coverage_convergence": ["visium_hd", "stereo_seq", "raefish"],
            "ai_native_analysis": ["nicheformer", "novae", "scgpt_spatial", "histology_to_st"],
            "spatial_multiomics": ["protein", "atac", "metabolomics", "lipidomics", "histology"],
            "whole_organ_4d_atlas": ["serial sections", "3D registration", "timepoint or disease-stage axis"],
            "clinical_standardization": ["cross-platform benchmark", "orthogonal validation", "locked provenance"],
        },
        "high_resolution_platforms": sorted(_HIGH_RESOLUTION_PLATFORMS),
        "matched_section_design": {
            "minimum": ["adjacent sections", "shared tissue landmarks", "shared marker panel or marker genes"],
            "strong": ["matched H&E", "matched scRNA-seq reference", "platform-specific negative controls", "replicate donors"],
        },
    }


@server.tool(
    "spatial_preprocess_recipe",
    "Generate a platform-aware spatial preprocessing recipe. Covers Visium/Visium HD binning, Xenium/CosMx segmentation "
    "QC, molecule contamination checks, squidpy neighborhoods and provenance.",
    {
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": _SUPPORTED_PLATFORMS, "default": "visium"},
            "has_matched_histology": {"type": "boolean", "default": True},
            "segmentation_source": {"type": "string"},
            "coordinate_key": {"type": "string", "default": "spatial"},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def spatial_preprocess_recipe(
    platform: str = "visium",
    has_matched_histology: bool = True,
    segmentation_source: Optional[str] = None,
    coordinate_key: str = "spatial",
    seed: int = 0,
):
    platform = _normalize_platform(platform)
    params = {
        "platform": platform,
        "has_matched_histology": has_matched_histology,
        "segmentation_source": segmentation_source,
        "coordinate_key": coordinate_key,
        "seed": seed,
    }
    recipe_hash = _recipe_hash("spatial_preprocess_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script": _render_preprocess_script(platform, coordinate_key, has_matched_histology, segmentation_source, seed),
        "qc_checks": _preprocess_qc_checks(platform, has_matched_histology),
        "provenance_skeleton": _provenance("spatial_preprocess_recipe", recipe_hash, params),
        "warnings": [
            "Do not interpret spatial domains until coordinate and image alignment are recorded in provenance.",
            "Do not erase raw counts; keep raw/counts layers for deconvolution and downstream model baselines.",
        ],
    }


def _preprocess_qc_checks(platform: str, has_image: bool) -> List[str]:
    checks = ["coordinate completeness", "raw-count layer present", "per-spot/cell UMI and gene-count distributions"]
    if has_image:
        checks.append("histology/image registration audit")
    if platform in _IMAGING_PLATFORMS:
        checks.extend(["segmentation area/nucleus overlap", "negative probe/control probe background", "neighbor contamination audit"])
    if platform in {"visium_hd", "stereo_seq"}:
        checks.extend(["bin-size sensitivity", "sparsity by bin", "aggregate-to-cell-radius comparison"])
    if platform == "slideseq":
        checks.extend(["bead registration", "bead density", "coordinate outlier removal"])
    if platform == "dbit_seq":
        checks.extend(["microfluidic grid registration", "pixel-size sensitivity", "multi-omic lane alignment if applicable"])
    if platform == "geomx":
        checks.extend(["ROI selection audit", "AOI/ROI area normalization", "negative probe and nuclei count controls"])
    return checks


def _render_preprocess_script(platform: str, coordinate_key: str, has_image: bool, segmentation_source: Optional[str], seed: int) -> str:
    if platform == "visium":
        loader = 'adata = sq.read.visium("SPACERANGER_OUT_DIR")'
    elif platform in {"visium_hd", "stereo_seq", "dbit_seq"}:
        loader = f'adata = sc.read_h5ad("{platform}_bins.h5ad")  # include bin_size/pixel_size in adata.uns["spatial_qc"]'
    elif platform == "geomx":
        loader = 'adata = sc.read_h5ad("geomx_roi_expression.h5ad")  # include ROI coordinates/areas in obs and obsm["spatial"] if available'
    else:
        loader = f'adata = sc.read_h5ad("{platform}_cell_feature_matrix.h5ad")  # must include adata.obsm["{coordinate_key}"]'
    seg_block = ""
    if platform in _IMAGING_PLATFORMS:
        seg_block = f'''
# Imaging-platform segmentation and background audit.
adata.obs["segmentation_source"] = {segmentation_source!r}
for col in ["cell_area", "nucleus_area", "negative_probe_count", "control_probe_count"]:
    if col not in adata.obs:
        adata.obs[col] = np.nan
adata.obs[["cell_area", "nucleus_area", "negative_probe_count", "control_probe_count"]].to_csv("segmentation_background_qc.tsv", sep="\\t")
# TODO: inspect molecule-to-cell assignment and neighbor contamination before rare-cell claims.
'''
    roi_block = ""
    if platform == "geomx":
        roi_block = '''
# ROI-platform audit: keep ROI selection and area/nuclei normalization visible.
for col in ["roi_area", "nuclei_count", "roi_selection_rule"]:
    if col not in adata.obs:
        adata.obs[col] = np.nan
adata.obs[["roi_area", "nuclei_count", "roi_selection_rule"]].to_csv("roi_selection_qc.tsv", sep="\\t")
'''
    image_note = "# Matched histology is expected; record image_sha256 and registration method.\n" if has_image else "# No matched histology declared; image-derived claims are disabled.\n"
    return f'''# bio-spatial.spatial_preprocess_recipe
import json
import numpy as np
import scanpy as sc
import squidpy as sq

np.random.seed({seed})
{loader}
{image_note}assert "{coordinate_key}" in adata.obsm or "spatial" in adata.obsm, "missing spatial coordinates"
if "counts" not in adata.layers:
    adata.layers["counts"] = adata.X.copy()
sc.pp.filter_genes(adata, min_cells=3)
sc.pp.calculate_qc_metrics(adata, inplace=True)
adata.obs[["total_counts", "n_genes_by_counts"]].to_csv("spatial_qc_cell_or_spot_metrics.tsv", sep="\\t")
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=3000, flavor="seurat_v3", layer="counts")
sc.tl.pca(adata)
sc.pp.neighbors(adata)
sc.tl.leiden(adata, key_added="spatial_leiden")
sq.gr.spatial_neighbors(adata, coord_type="generic")
sq.gr.spatial_autocorr(adata, mode="moran")
sq.gr.nhood_enrichment(adata, cluster_key="spatial_leiden")
{seg_block}
{roi_block}
provenance = {{
  "platform": "{platform}",
  "coordinate_key": "{coordinate_key}",
  "has_matched_histology": {has_image!r},
  "seed": {seed}
}}
json.dump(provenance, open("spatial_preprocess_provenance_stub.json", "w", encoding="utf-8"), indent=2)
adata.write_h5ad("spatial_preprocessed.h5ad")
'''


@server.tool(
    "spatial_deconvolution_recipe",
    "Generate spatial deconvolution or reference-mapping recipes. Auto mode uses marker scoring for rare-cell-heavy "
    "questions, otherwise cell2location for Visium-like data and RCTD for imaging/spot transfer checks.",
    {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["auto", "marker_score", "cell2location", "rctd", "tangram", "stereoscope"], "default": "auto"},
            "platform": {"type": "string", "enum": _SUPPORTED_PLATFORMS, "default": "visium"},
            "reference_modality": {"type": "string", "default": "scRNA-seq"},
            "rare_cell_expected": {"type": "boolean", "default": False},
            "celltype_key": {"type": "string", "default": "cell_type"},
            "sample_key": {"type": "string", "default": "sample_id"},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def spatial_deconvolution_recipe(
    method: str = "auto",
    platform: str = "visium",
    reference_modality: str = "scRNA-seq",
    rare_cell_expected: bool = False,
    celltype_key: str = "cell_type",
    sample_key: str = "sample_id",
    seed: int = 0,
):
    platform = _normalize_platform(platform)
    chosen = _choose_deconv_method(method, platform, rare_cell_expected)
    params = {
        "method": chosen,
        "platform": platform,
        "reference_modality": reference_modality,
        "rare_cell_expected": rare_cell_expected,
        "celltype_key": celltype_key,
        "sample_key": sample_key,
        "seed": seed,
    }
    recipe_hash = _recipe_hash("spatial_deconvolution_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "recommended_method": chosen,
        "script": _render_deconv_script(chosen, platform, celltype_key, sample_key, seed),
        "method_guidance": {
            "marker_score": "Mandatory baseline for rare populations and targeted panels; robust but marker-list dependent.",
            "cell2location": "Strong for Visium-like spot/bin deconvolution when a matched scRNA-seq reference exists.",
            "rctd": "Useful for reference transfer and doublet/mixed-spot modeling; good orthogonal check.",
            "tangram": "Maps scRNA-seq cells onto space; sensitive to reference and gene overlap.",
            "stereoscope": "Probabilistic spot deconvolution; useful baseline for whole-transcriptome spots.",
        },
        "rare_cell_guardrails": [
            "Report agreement between deconvolution and marker-score baseline; do not rely on one complex model alone.",
            "Use donor/sample-level replication; do not count spots/cells as independent biological replicates.",
            "For rare cell types, require manual marker audit and a negative-control marker set.",
        ],
        "provenance_skeleton": _provenance("spatial_deconvolution_recipe", recipe_hash, params),
    }


def _choose_deconv_method(method: str, platform: str, rare: bool) -> str:
    if method != "auto":
        return method
    if rare:
        return "marker_score"
    if platform in _SPOT_PLATFORMS:
        return "cell2location"
    if platform in _ROI_PLATFORMS:
        return "marker_score"
    return "rctd"


def _render_deconv_script(method: str, platform: str, celltype_key: str, sample_key: str, seed: int) -> str:
    if method == "marker_score":
        return f'''# Marker-score baseline for spatial deconvolution / rare-cell checks.
import json
import numpy as np
import scanpy as sc
import squidpy as sq

np.random.seed({seed})
adata = sc.read_h5ad("spatial_preprocessed.h5ad")
markers = json.load(open("celltype_marker_genes.json", encoding="utf-8"))
for name, genes in markers.items():
    genes = [g for g in genes if g in adata.var_names]
    if genes:
        sc.tl.score_genes(adata, genes, score_name=f"score_{{name}}")
score_cols = [c for c in adata.obs.columns if c.startswith("score_")]
adata.obs[score_cols].to_csv("spatial_marker_scores.tsv", sep="\\t")
sq.gr.nhood_enrichment(adata, cluster_key="spatial_leiden")
adata.write_h5ad("spatial_marker_scored.h5ad")
'''
    if method == "cell2location":
        return f'''# cell2location recipe skeleton for {platform}; fill current API details locally.
raise SystemExit("SKELETON: install/pin cell2location, fill TODOs, verify current API, then remove this guard")
import numpy as np
import scanpy as sc
np.random.seed({seed})
sp = sc.read_h5ad("spatial_preprocessed.h5ad")
ref = sc.read_h5ad("matched_scrna_reference.h5ad")
assert "{celltype_key}" in ref.obs, "reference needs cell-type labels"
assert "counts" in sp.layers and "counts" in ref.layers, "cell2location requires raw counts"
# TODO: train reference regression model, export cell-type signatures.
# TODO: train cell2location spatial model and write abundance estimates.
'''
    if method == "rctd":
        return f'''# RCTD / spacexr recipe skeleton.
suppressPackageStartupMessages({{
  library(spacexr)
  library(zellkonverter)
}})
set.seed({seed})
sp <- readH5AD("spatial_preprocessed.h5ad")
ref <- readH5AD("matched_scrna_reference.h5ad")
# TODO: construct SpatialRNA and Reference objects using {celltype_key} and {sample_key}.
# TODO: run RCTD and export weights for each spot/cell/bin.
'''
    if method == "tangram":
        return f'''# Tangram mapping recipe skeleton.
raise SystemExit("SKELETON: install/pin tangram-sc, fill TODOs, verify current API, then remove this guard")
import numpy as np
import scanpy as sc
np.random.seed({seed})
sp = sc.read_h5ad("spatial_preprocessed.h5ad")
ref = sc.read_h5ad("matched_scrna_reference.h5ad")
# TODO: select shared genes, preprocess ref/spatial, run tangram.map_cells_to_space.
'''
    return f'''# Stereoscope recipe skeleton.
raise SystemExit("SKELETON: install/pin stereoscope, fill TODOs, verify current API, then remove this guard")
# TODO: export counts and labels from matched_scrna_reference.h5ad, train reference model, deconvolve spatial counts.
'''


@server.tool(
    "spatial_rare_cell_recipe",
    "Generate a rare-cell spatial validation recipe with marker scoring, negative controls, neighborhood enrichment, "
    "and simulation/stress-test hooks.",
    {
        "type": "object",
        "properties": {
            "rare_population": {"type": "string", "default": "rare epithelial state"},
            "marker_genes": {"type": "array", "items": {"type": "string"}},
            "platform": {"type": "string", "enum": _SUPPORTED_PLATFORMS, "default": "xenium"},
            "min_spots_or_cells": {"type": "integer", "default": 25},
            "validation_mode": {"type": "string", "enum": ["marker_only", "orthogonal", "simulation_stress"], "default": "orthogonal"},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def spatial_rare_cell_recipe(
    rare_population: str = "rare epithelial state",
    marker_genes: Optional[List[str]] = None,
    platform: str = "xenium",
    min_spots_or_cells: int = 25,
    validation_mode: str = "orthogonal",
    seed: int = 0,
):
    platform = _normalize_platform(platform)
    markers = marker_genes or _default_rare_markers(rare_population)
    params = {
        "rare_population": rare_population,
        "marker_genes": markers,
        "platform": platform,
        "min_spots_or_cells": min_spots_or_cells,
        "validation_mode": validation_mode,
        "seed": seed,
    }
    recipe_hash = _recipe_hash("spatial_rare_cell_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script": _render_rare_cell_script(rare_population, markers, min_spots_or_cells, seed),
        "decision_thresholds": {
            "minimum_detected_units": min_spots_or_cells,
            "required_evidence": ["marker score above background", "spatial clustering or niche enrichment", "negative-control marker set", "sample-level replication"],
            "orthogonal_mode_adds": ["matched scRNA-seq reference", "second spatial platform or imaging/protein validation"],
        },
        "stress_tests": [
            "Shuffle marker labels and rerun score distribution.",
            "Use decoy markers matched for expression level.",
            "Downsample counts to test stability.",
            "Repeat analysis stratified by sample/donor and platform.",
        ],
        "provenance_skeleton": _provenance("spatial_rare_cell_recipe", recipe_hash, params),
    }


def _default_rare_markers(population: str) -> List[str]:
    p = population.lower()
    if "krt17" in p or "basaloid" in p or "ipf" in p:
        return ["KRT17", "KRT5", "KRT8", "EPCAM", "KRT14", "SPP1", "COL1A1"]
    if "immune" in p:
        return ["PTPRC", "CD3D", "NKG7", "MS4A1", "LYZ"]
    return ["EPCAM", "PTPRC", "COL1A1", "PECAM1"]


def _render_rare_cell_script(population: str, markers: List[str], min_units: int, seed: int) -> str:
    return f'''# Rare-cell spatial validation recipe: {population}
import json
import numpy as np
import scanpy as sc
import squidpy as sq

np.random.seed({seed})
adata = sc.read_h5ad("spatial_preprocessed.h5ad")
markers = {markers!r}
present = [g for g in markers if g in adata.var_names]
assert len(present) >= max(2, len(markers) // 3), "too few marker genes present for a defensible rare-cell score"
sc.tl.score_genes(adata, present, score_name="rare_population_score")
threshold = adata.obs["rare_population_score"].quantile(0.95)
adata.obs["rare_population_candidate"] = adata.obs["rare_population_score"] >= threshold
assert int(adata.obs["rare_population_candidate"].sum()) >= {min_units}, "candidate count below predeclared minimum; report as underpowered"
sq.gr.spatial_neighbors(adata)
sq.gr.nhood_enrichment(adata, cluster_key="rare_population_candidate")
adata.obs[["rare_population_score", "rare_population_candidate"]].to_csv("rare_population_marker_score.tsv", sep="\\t")
json.dump({{"population": {population!r}, "markers": present, "threshold_quantile": 0.95}}, open("rare_population_recipe_meta.json", "w"), indent=2)
adata.write_h5ad("spatial_rare_population_scored.h5ad")
'''


@server.tool(
    "spatial_domain_recipe",
    "Generate a spatially variable gene and spatial-domain recipe. Covers squidpy Moran/Geary baselines, "
    "Leiden neighborhoods, and not-runnable hooks for BayesSpace/SpaGCN/STAGATE-style domain models.",
    {
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": _SUPPORTED_PLATFORMS, "default": "visium"},
            "task": {"type": "string", "enum": ["spatially_variable_genes", "domain_identification", "both"], "default": "both"},
            "coordinate_key": {"type": "string", "default": "spatial"},
            "domain_key": {"type": "string", "default": "spatial_domain"},
            "n_top_genes": {"type": "integer", "default": 2000},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def spatial_domain_recipe(
    platform: str = "visium",
    task: str = "both",
    coordinate_key: str = "spatial",
    domain_key: str = "spatial_domain",
    n_top_genes: int = 2000,
    seed: int = 0,
):
    platform = _normalize_platform(platform)
    params = {
        "platform": platform,
        "task": task,
        "coordinate_key": coordinate_key,
        "domain_key": domain_key,
        "n_top_genes": n_top_genes,
        "seed": seed,
    }
    recipe_hash = _recipe_hash("spatial_domain_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script": _render_domain_script(platform, task, coordinate_key, domain_key, n_top_genes, seed),
        "method_ladder": [
            "Baseline: squidpy spatial_neighbors plus Moran's I / Geary spatial autocorrelation.",
            "Domain baseline: PCA/neighbors/Leiden on expression with spatial-neighborhood enrichment.",
            "Model check: BayesSpace for spot/bin platforms; SpaGCN/STAGATE/SEDR for graph-aware domains.",
            "Robustness: rerun across samples, bin sizes, coordinate perturbations and negative-control genes.",
        ],
        "qc_checks": [
            "coordinate completeness and duplicate coordinates",
            "spatial graph degree distribution",
            "SVG stability across donors or serial sections",
            "domain enrichment versus shuffled coordinates",
            "platform/bin-size stratified domain labels",
        ],
        "provenance_skeleton": _provenance("spatial_domain_recipe", recipe_hash, params),
        "warnings": [
            "Spatial domains are descriptive tissue partitions until validated with morphology, markers or perturbation.",
            "Do not compare only UMAP colors; report SVG tables, domain markers and spatial graph settings.",
        ],
    }


def _render_domain_script(platform: str, task: str, coordinate_key: str, domain_key: str, n_top_genes: int, seed: int) -> str:
    return f'''# Spatially variable genes and domain identification baseline.
import json
import numpy as np
import pandas as pd
import scanpy as sc
import squidpy as sq

np.random.seed({seed})
adata = sc.read_h5ad("spatial_preprocessed.h5ad")
if "{coordinate_key}" != "spatial" and "{coordinate_key}" in adata.obsm:
    adata.obsm["spatial"] = adata.obsm["{coordinate_key}"]
assert "spatial" in adata.obsm, "missing spatial coordinates"
if "log1p" not in adata.uns:
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
sq.gr.spatial_neighbors(adata, coord_type="generic")
sc.pp.highly_variable_genes(adata, n_top_genes={n_top_genes})
svg_genes = adata.var_names[adata.var["highly_variable"]].tolist()
sq.gr.spatial_autocorr(adata, mode="moran", genes=svg_genes)
sq.gr.spatial_autocorr(adata, mode="geary", genes=svg_genes)
sc.tl.pca(adata)
sc.pp.neighbors(adata)
sc.tl.leiden(adata, key_added="{domain_key}")
sq.gr.nhood_enrichment(adata, cluster_key="{domain_key}")
if "moranI" in adata.uns:
    adata.uns["moranI"].to_csv("spatially_variable_genes_moran.tsv", sep="\\t")
adata.obs[["{domain_key}"]].to_csv("spatial_domains.tsv", sep="\\t")
json.dump({{"platform": "{platform}", "task": "{task}", "domain_key": "{domain_key}"}}, open("spatial_domain_recipe_meta.json", "w"), indent=2)
# TODO optional model checks: BayesSpace for spot/bin data; SpaGCN/STAGATE/SEDR for graph-aware domain discovery.
adata.write_h5ad("spatial_domains_scored.h5ad")
'''


@server.tool(
    "spatial_communication_recipe",
    "Generate a spatial cell-cell communication and niche-interaction recipe with spatial adjacency constraints, "
    "ligand-receptor resources, permutation controls and donor-level replication.",
    {
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": _SUPPORTED_PLATFORMS, "default": "xenium"},
            "method": {"type": "string", "enum": ["liana", "cellphonedb", "nichenet", "squidpy"], "default": "liana"},
            "celltype_key": {"type": "string", "default": "cell_type"},
            "condition_key": {"type": "string"},
            "ligand_receptor_resource": {"type": "string", "default": "consensus"},
            "spatial_radius_um": {"type": "number"},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def spatial_communication_recipe(
    platform: str = "xenium",
    method: str = "liana",
    celltype_key: str = "cell_type",
    condition_key: Optional[str] = None,
    ligand_receptor_resource: str = "consensus",
    spatial_radius_um: Optional[float] = None,
    seed: int = 0,
):
    platform = _normalize_platform(platform)
    params = {
        "platform": platform,
        "method": method,
        "celltype_key": celltype_key,
        "condition_key": condition_key,
        "ligand_receptor_resource": ligand_receptor_resource,
        "spatial_radius_um": spatial_radius_um,
        "seed": seed,
    }
    recipe_hash = _recipe_hash("spatial_communication_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script": _render_communication_script(platform, method, celltype_key, condition_key, spatial_radius_um, seed),
        "method_guidance": {
            "squidpy": "Good for neighborhood enrichment and adjacency-aware descriptive checks.",
            "liana": "Good ligand-receptor consensus wrapper; keep spatial adjacency as an extra constraint.",
            "cellphonedb": "Familiar LR baseline; spatial restriction and sample replication must be added explicitly.",
            "nichenet": "Useful when target-gene response is part of the hypothesis; treat as mechanistic candidate ranking.",
        },
        "guardrails": [
            "Ligand-receptor co-expression is not proof of signaling.",
            "Require spatial adjacency or distance-weighting, not only cell-type abundance.",
            "Use shuffled coordinates and shuffled cell-type labels as negative controls.",
            "Summarize at sample/donor level before condition claims.",
            "Report the ligand-receptor resource and version because databases disagree.",
        ],
        "provenance_skeleton": _provenance("spatial_communication_recipe", recipe_hash, params),
    }


def _render_communication_script(
    platform: str,
    method: str,
    celltype_key: str,
    condition_key: Optional[str],
    spatial_radius_um: Optional[float],
    seed: int,
) -> str:
    radius_line = f'sq.gr.spatial_neighbors(adata, radius={spatial_radius_um}, coord_type="generic")' if spatial_radius_um else 'sq.gr.spatial_neighbors(adata, coord_type="generic")'
    condition_note = f'"condition_key": "{condition_key}"' if condition_key else '"condition_key": None'
    return f'''# Spatial communication / niche-interaction recipe.
import json
import numpy as np
import scanpy as sc
import squidpy as sq

np.random.seed({seed})
adata = sc.read_h5ad("spatial_preprocessed.h5ad")
assert "{celltype_key}" in adata.obs, "cell-type annotations are required"
{radius_line}
sq.gr.nhood_enrichment(adata, cluster_key="{celltype_key}")
adata.uns["spatial_communication_plan"] = {{
    "method": "{method}",
    "platform": "{platform}",
    {condition_note},
    "negative_controls": ["shuffle_coordinates", "shuffle_celltype_labels", "decoy_ligand_receptor_pairs"],
}}
# SKELETON: install/pin LIANA/CellPhoneDB/NicheNet locally and run only after checking their current APIs.
# TODO {method}: restrict candidate ligand-receptor pairs by spatial adjacency and summarize by donor/sample.
adata.obs[[ "{celltype_key}" ]].to_csv("spatial_communication_celltypes.tsv", sep="\\t")
json.dump(adata.uns["spatial_communication_plan"], open("spatial_communication_plan.json", "w"), indent=2)
adata.write_h5ad("spatial_communication_ready.h5ad")
'''


def _modality_names(modalities: Optional[List[str]]) -> List[str]:
    if not modalities:
        return ["transcriptome", "protein", "histology"]
    out = []
    for m in modalities:
        key = (m or "").strip().lower().replace("-", "_").replace(" ", "_")
        if key in {"rna", "mrna", "spatial_transcriptome"}:
            key = "transcriptome"
        if key in {"he", "h_and_e", "h&e", "image"}:
            key = "histology"
        if key in _MODALITY_GUIDANCE and key not in out:
            out.append(key)
    return out or ["transcriptome", "histology"]


@server.tool(
    "spatial_multimodal_recipe",
    "Generate a spatial multi-omics integration recipe for same-slide or serial-section RNA, protein, ATAC, "
    "metabolomics, lipidomics and histology data.",
    {
        "type": "object",
        "properties": {
            "modalities": {"type": "array", "items": {"type": "string"}},
            "platform": {"type": "string", "enum": _SUPPORTED_PLATFORMS, "default": "geomx"},
            "same_slide": {"type": "boolean", "default": True},
            "integration_goal": {"type": "string", "default": "spatial_proteogenomics"},
            "sample_key": {"type": "string", "default": "sample_id"},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def spatial_multimodal_recipe(
    modalities: Optional[List[str]] = None,
    platform: str = "geomx",
    same_slide: bool = True,
    integration_goal: str = "spatial_proteogenomics",
    sample_key: str = "sample_id",
    seed: int = 0,
):
    platform = _normalize_platform(platform)
    mods = _modality_names(modalities)
    params = {
        "modalities": mods,
        "platform": platform,
        "same_slide": same_slide,
        "integration_goal": integration_goal,
        "sample_key": sample_key,
        "seed": seed,
    }
    recipe_hash = _recipe_hash("spatial_multimodal_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "modality_plan": {m: _MODALITY_GUIDANCE[m] for m in mods},
        "script": _render_multimodal_script(mods, platform, same_slide, sample_key, seed),
        "integration_contract": [
            "Keep each modality's normalization, control probes and missingness separate before fusion.",
            "For same-slide assays, record section reuse order and modality-specific loss; for serial sections, record registration transforms.",
            "Report RNA-only, non-RNA-only and fused-model baselines.",
            "Treat protein, chromatin and metabolite evidence as corroborating layers, not automatic replication.",
        ],
        "provenance_skeleton": _provenance("spatial_multimodal_recipe", recipe_hash, params),
    }


def _render_multimodal_script(modalities: List[str], platform: str, same_slide: bool, sample_key: str, seed: int) -> str:
    return f'''# Spatial multi-omics integration skeleton.
raise SystemExit("SKELETON: fill modality-specific loaders and pin muon/scvi-tools/registration versions before running")
import json
import numpy as np
import scanpy as sc

np.random.seed({seed})
modalities = {modalities!r}
same_slide = {same_slide!r}
rna = sc.read_h5ad("spatial_preprocessed.h5ad")
assert "{sample_key}" in rna.obs, "sample-level metadata is required"
# TODO: load protein/ATAC/metabolomics/lipidomics/histology modalities as available.
# TODO: build MuData or aligned AnnData objects; keep raw modality matrices and controls.
# TODO: run RNA-only, modality-only and fused baselines before making multi-omic claims.
json.dump({{"platform": "{platform}", "modalities": modalities, "same_slide": same_slide}}, open("spatial_multimodal_plan.json", "w"), indent=2)
'''


@server.tool(
    "spatial_histology_prediction_plan",
    "Generate a NOT-RUNNABLE virtual spatial transcriptomics plan for predicting spatial expression from H&E or "
    "pathology images, with leakage controls and validation requirements.",
    {
        "type": "object",
        "properties": {
            "model_family": {"type": "string", "default": "histology_to_st"},
            "task_type": {"type": "string", "enum": ["gene_expression_prediction", "biomarker_prediction", "domain_prediction"], "default": "gene_expression_prediction"},
            "platform": {"type": "string", "enum": _SUPPORTED_PLATFORMS, "default": "visium_hd"},
            "image_source": {"type": "string", "default": "H&E"},
            "validation_strategy": {"type": "string", "enum": ["donor_holdout", "slide_holdout", "site_holdout", "spatial_holdout"], "default": "donor_holdout"},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def spatial_histology_prediction_plan(
    model_family: str = "histology_to_st",
    task_type: str = "gene_expression_prediction",
    platform: str = "visium_hd",
    image_source: str = "H&E",
    validation_strategy: str = "donor_holdout",
    seed: int = 0,
):
    platform = _normalize_platform(platform)
    params = {
        "model_family": model_family,
        "task_type": task_type,
        "platform": platform,
        "image_source": image_source,
        "validation_strategy": validation_strategy,
        "seed": seed,
    }
    plan_hash = _recipe_hash("spatial_histology_prediction_plan", params)
    return {
        "plan_hash": plan_hash,
        "artifact_type": "skeleton",
        "runnable": False,
        "params": params,
        "script": _render_histology_prediction_script(model_family, task_type, platform, image_source, validation_strategy, seed),
        "validation_contract": [
            "Split by donor/slide/site before tiling to prevent image-neighborhood leakage.",
            "Report gene-level correlation, calibration, biomarker AUROC/AUPRC and spatial-domain agreement.",
            "Benchmark against morphology-only, expression-only and shuffled-label controls.",
            "State that predicted ST is approximate and must be validated on measured spatial data before clinical claims.",
        ],
        "provenance_skeleton": {
            "schema": "bio-spatial/histology-prediction-provenance/1",
            "plan_hash": plan_hash,
            "image": {"source": image_source, "tile_manifest_sha256": "<FILL>", "stain_normalization": "<FILL>"},
            "spatial_training_data": {"platform": platform, "spatial_recipe_hash": "<FILL>", "anndata_sha256": "<FILL>"},
            "split": {"strategy": validation_strategy, "split_hash": "<FILL>", "no_tile_leakage": "<FILL true/false>"},
            "model": {"family": model_family, "version": "<FILL>", "checkpoint": "<FILL>"},
            "metrics": {"heldout_gene_correlation": "<FILL>", "biomarker_auprc": "<FILL>"},
        },
        "warnings": [
            "This is a virtual-ST plan, not measured spatial transcriptomics.",
            "Do not use tile-level random splits for pathology-to-expression evaluation.",
        ],
    }


def _render_histology_prediction_script(
    model_family: str,
    task_type: str,
    platform: str,
    image_source: str,
    validation_strategy: str,
    seed: int,
) -> str:
    return f'''# {"=" * 68}
# SKELETON - NOT RUNNABLE AS-IS
# Virtual spatial transcriptomics from {image_source}: fill dataset-specific image
# loaders, registration transforms, model API and leakage-free splits first.
# {"=" * 68}
raise SystemExit("SKELETON: build tile_manifest, donor/slide split and measured-ST validation before running")

import json
import numpy as np

np.random.seed({seed})
plan = {{
    "model_family": "{model_family}",
    "task_type": "{task_type}",
    "platform": "{platform}",
    "image_source": "{image_source}",
    "validation_strategy": "{validation_strategy}",
    "required_controls": ["morphology_only", "shuffled_labels", "measured_ST_holdout"],
}}
# TODO: create tile_manifest with donor_id, slide_id, section_id, x/y, image_sha256 and linked expression target.
# TODO: split before tiling; block all tiles from the same donor/slide/site from crossing train/test.
# TODO: train histology-to-ST model and export calibrated predictions with held-out metrics.
json.dump(plan, open("spatial_histology_prediction_plan.json", "w"), indent=2)
'''


@server.tool(
    "spatial_atlas_3d_recipe",
    "Generate a serial-section 3D or spatiotemporal atlas recipe with section registration, coordinate harmonization, "
    "quality checks and 4D disease/development axis support.",
    {
        "type": "object",
        "properties": {
            "atlas_goal": {"type": "string", "default": "whole_organ_atlas"},
            "registration_method": {"type": "string", "enum": ["histology_landmarks", "fiducials", "optimal_transport", "hybrid"], "default": "hybrid"},
            "section_key": {"type": "string", "default": "section_id"},
            "coordinate_key": {"type": "string", "default": "spatial"},
            "timepoint_key": {"type": "string"},
            "z_step_um": {"type": "number"},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def spatial_atlas_3d_recipe(
    atlas_goal: str = "whole_organ_atlas",
    registration_method: str = "hybrid",
    section_key: str = "section_id",
    coordinate_key: str = "spatial",
    timepoint_key: Optional[str] = None,
    z_step_um: Optional[float] = None,
    seed: int = 0,
):
    params = {
        "atlas_goal": atlas_goal,
        "registration_method": registration_method,
        "section_key": section_key,
        "coordinate_key": coordinate_key,
        "timepoint_key": timepoint_key,
        "z_step_um": z_step_um,
        "seed": seed,
    }
    recipe_hash = _recipe_hash("spatial_atlas_3d_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "script": _render_atlas_3d_script(atlas_goal, registration_method, section_key, coordinate_key, timepoint_key, z_step_um, seed),
        "atlas_contract": [
            "Keep original 2D section coordinates immutable and write registered 3D coordinates to a new layer.",
            "Report registration residuals, landmark errors and missing tissue masks per section.",
            "For 4D atlases, model timepoint/disease stage at sample level, not as independent spots.",
            "Provide a browsing/export format that preserves section, z-depth, donor and platform metadata.",
        ],
        "provenance_skeleton": _provenance("spatial_atlas_3d_recipe", recipe_hash, params),
    }


def _render_atlas_3d_script(
    atlas_goal: str,
    registration_method: str,
    section_key: str,
    coordinate_key: str,
    timepoint_key: Optional[str],
    z_step_um: Optional[float],
    seed: int,
) -> str:
    z_expr = f'float({z_step_um})' if z_step_um is not None else "1.0"
    time_line = f'assert "{timepoint_key}" in adata.obs, "missing timepoint/disease-stage metadata"' if timepoint_key else "# Optional: add timepoint_key for 4D atlas analyses."
    return f'''# Serial-section 3D / 4D spatial atlas recipe.
import json
import numpy as np
import pandas as pd
import scanpy as sc

np.random.seed({seed})
adata = sc.read_h5ad("spatial_preprocessed_sections.h5ad")
assert "{section_key}" in adata.obs, "section metadata is required"
assert "{coordinate_key}" in adata.obsm, "2D spatial coordinates are required"
{time_line}
coords = np.asarray(adata.obsm["{coordinate_key}"], dtype=float)
section_codes = pd.Categorical(adata.obs["{section_key}"]).codes.astype(float)
z_step = {z_expr}
adata.obsm["spatial_3d_registered"] = np.column_stack([coords[:, 0], coords[:, 1], section_codes * z_step])
adata.uns["spatial_3d_registration"] = {{
    "atlas_goal": "{atlas_goal}",
    "registration_method": "{registration_method}",
    "z_step_um": z_step,
    "todo": ["replace ordinal z with measured section depth", "apply landmark/optimal-transport transforms", "export residual QC"],
}}
json.dump(adata.uns["spatial_3d_registration"], open("spatial_3d_registration_plan.json", "w"), indent=2)
adata.write_h5ad("spatial_3d_atlas_ready.h5ad")
'''


@server.tool(
    "spatial_translation_readiness_gate",
    "Score whether a spatial transcriptomics result is ready for discovery, translational pilot or diagnostic-style "
    "claims based on platform QC, replication, orthogonal validation, provenance and leakage controls.",
    {
        "type": "object",
        "properties": {
            "use_case": {"type": "string", "enum": ["discovery", "translational_pilot", "diagnostic_biomarker", "companion_diagnostic"], "default": "discovery"},
            "platform": {"type": "string", "enum": _SUPPORTED_PLATFORMS, "default": "xenium"},
            "has_replicates": {"type": "boolean", "default": False},
            "has_orthogonal_validation": {"type": "boolean", "default": False},
            "has_locked_provenance": {"type": "boolean", "default": False},
            "has_platform_benchmark": {"type": "boolean", "default": False},
            "has_leakage_audit": {"type": "boolean", "default": False},
        },
    },
)
def spatial_translation_readiness_gate(
    use_case: str = "discovery",
    platform: str = "xenium",
    has_replicates: bool = False,
    has_orthogonal_validation: bool = False,
    has_locked_provenance: bool = False,
    has_platform_benchmark: bool = False,
    has_leakage_audit: bool = False,
):
    platform = _normalize_platform(platform)
    checks = {
        "sample_or_donor_replicates": has_replicates,
        "orthogonal_validation": has_orthogonal_validation,
        "locked_provenance": has_locked_provenance,
        "platform_or_method_benchmark": has_platform_benchmark,
        "leakage_or_split_audit": has_leakage_audit,
    }
    required_by_use_case = {
        "discovery": ["locked_provenance"],
        "translational_pilot": ["sample_or_donor_replicates", "orthogonal_validation", "locked_provenance"],
        "diagnostic_biomarker": ["sample_or_donor_replicates", "orthogonal_validation", "locked_provenance", "platform_or_method_benchmark", "leakage_or_split_audit"],
        "companion_diagnostic": ["sample_or_donor_replicates", "orthogonal_validation", "locked_provenance", "platform_or_method_benchmark", "leakage_or_split_audit"],
    }
    required = required_by_use_case.get(use_case, required_by_use_case["discovery"])
    missing = [k for k in required if not checks[k]]
    if not missing:
        verdict = "ready_for_claim_scope"
    elif use_case == "discovery" and "locked_provenance" in missing:
        verdict = "exploratory_only_until_provenance_locked"
    else:
        verdict = "not_ready_for_claim_scope"
    return {
        "verdict": verdict,
        "use_case": use_case,
        "platform": platform,
        "checks": checks,
        "missing": missing,
        "minimum_next_steps": [
            "Lock recipe hashes, input hashes, coordinate/image hashes and software versions.",
            "Aggregate conclusions at donor/sample level.",
            "Add orthogonal validation with a second platform, protein/imaging assay or matched scRNA-seq reference.",
            "Run platform-stratified benchmarks and negative controls before diagnostic or companion-diagnostic language.",
        ],
        "allowed_language": _allowed_readiness_language(verdict, use_case),
    }


def _allowed_readiness_language(verdict: str, use_case: str) -> str:
    if verdict == "ready_for_claim_scope":
        return f"May support {use_case} claims if the filled provenance and validation artifacts are attached."
    if verdict == "exploratory_only_until_provenance_locked":
        return "Use exploratory language only; do not present as a reproducible spatial finding yet."
    return "Use hypothesis-generating language only; do not present as translational or diagnostic evidence."


@server.tool(
    "spatial_scfm_model_matrix",
    "Return spatial foundation-model and baseline matrix. Use before choosing scGPT-Spatial, Nicheformer, CELLama, "
    "STORM, Novae, PAST or histology-to-ST model skeletons.",
    {
        "type": "object",
        "properties": {"model": {"type": "string"}},
    },
)
def spatial_scfm_model_matrix(model: Optional[str] = None):
    if model:
        key = model.lower().replace("-", "_")
        return _SPATIAL_MODELS.get(key) or {"error": f"unknown spatial model: {model}", "available": sorted(_SPATIAL_MODELS)}
    return {
        "models": _SPATIAL_MODELS,
        "baseline_contract": [
            "Every spatial foundation-model run must include an expression-only baseline and a marker/deconvolution baseline.",
            "Record platform, panel/binning, coordinate preprocessing hash and image-feature provenance separately.",
            "Never compare UMAP aesthetics only; report batch/platform mixing and biology conservation metrics.",
        ],
    }


@server.tool(
    "spatial_scfm_plan",
    "Generate a NOT-RUNNABLE spatial foundation-model skeleton plus provenance fields for scGPT-Spatial, Nicheformer, "
    "CELLama, STORM, Novae, PAST or histology-to-ST workflows.",
    {
        "type": "object",
        "properties": {
            "model": {"type": "string", "enum": sorted(_SPATIAL_MODELS)},
            "platform": {"type": "string", "enum": _SUPPORTED_PLATFORMS, "default": "visium"},
            "task_type": {"type": "string", "enum": ["embedding", "reference_mapping", "niche_prediction", "histology_fusion"], "default": "embedding"},
            "anndata_sha256": {"type": "string"},
            "spatial_recipe_hash": {"type": "string"},
            "output_layer": {"type": "string"},
            "seed": {"type": "integer", "default": 0},
        },
        "required": ["model"],
    },
)
def spatial_scfm_plan(
    model: str,
    platform: str = "visium",
    task_type: str = "embedding",
    anndata_sha256: Optional[str] = None,
    spatial_recipe_hash: Optional[str] = None,
    output_layer: Optional[str] = None,
    seed: int = 0,
):
    key = model.lower().replace("-", "_")
    platform = _normalize_platform(platform)
    meta = _SPATIAL_MODELS.get(key)
    if not meta:
        return {"error": f"unknown spatial model: {model}", "available": sorted(_SPATIAL_MODELS)}
    out_layer = output_layer or f"X_{key}"
    params = {
        "model": key,
        "platform": platform,
        "task_type": task_type,
        "anndata_sha256": anndata_sha256,
        "spatial_recipe_hash": spatial_recipe_hash,
        "output_layer": out_layer,
        "seed": seed,
    }
    plan_hash = _recipe_hash("spatial_scfm_plan", params)
    gaps = []
    if not anndata_sha256:
        gaps.append("missing anndata_sha256 from true content hash snippet")
    if not spatial_recipe_hash:
        gaps.append("missing spatial_recipe_hash from spatial_preprocess_recipe")
    return {
        "plan_hash": plan_hash,
        "artifact_type": "skeleton",
        "runnable": False,
        "model": meta,
        "params": params,
        "script": _render_spatial_scfm_script(key, platform, task_type, out_layer, seed),
        "gaps": gaps,
        "provenance_skeleton": {
            "schema": "bio-spatial/foundation-model-provenance/1",
            "plan_hash": plan_hash,
            "model": {"name": key, "version": "<FILL>", "checkpoint": "<FILL>", "commit": "<FILL>"},
            "input": {"anndata_sha256": anndata_sha256 or "<FILL>", "platform": platform, "spatial_recipe_hash": spatial_recipe_hash or "<FILL>"},
            "embedding": {"output_layer": out_layer, "output_sha256": "<FILL>", "n_dims": "<FILL>"},
            "baseline": {"expression_only": "<FILL>", "marker_or_deconvolution": "<FILL>"},
            "run": {"seed": seed, "created_at": "<FILL ISO8601>", "device": "<FILL>"},
        },
        "warnings": [
            "This is a skeleton, not a runnable script. Verify the current official API and remove SystemExit only after filling TODOs.",
            "Spatial foundation-model claims require platform-stratified quality metrics and a simpler baseline.",
        ],
    }


def _render_spatial_scfm_script(model: str, platform: str, task_type: str, out_layer: str, seed: int) -> str:
    return f'''# {"=" * 68}
# SKELETON - NOT RUNNABLE AS-IS
# Spatial foundation-model APIs and checkpoints change quickly. Pin versions,
# fill TODOs, verify the current official API, then remove this guard.
# {"=" * 68}
raise SystemExit("SKELETON: fill TODOs, pin versions, verify official API, then remove this guard")

import hashlib
import json
import numpy as np
import scanpy as sc

np.random.seed({seed})
adata = sc.read_h5ad("spatial_preprocessed.h5ad")
assert "spatial" in adata.obsm or any(k.endswith("spatial") for k in adata.obsm.keys()), "missing spatial coordinates"

# TODO {model}: load checkpoint and run task={task_type} for platform={platform}.
# TODO: preserve protocol/platform metadata and spatial graph inputs.
# TODO: write embedding to adata.obsm["{out_layer}"].

E = np.ascontiguousarray(adata.obsm["{out_layer}"])
print("embedding_dim:", E.shape[1])
print("output_sha256:sha256:" + hashlib.sha256(E.tobytes()).hexdigest())
json.dump({{"model": "{model}", "platform": "{platform}", "task_type": "{task_type}"}}, open("spatial_scfm_run_stub.json", "w"), indent=2)
adata.write_h5ad("spatial_fm_embedded.h5ad")
'''


@server.tool(
    "ipf_krt17_spatial_validation_recipe",
    "Generate an IPF-focused spatial validation recipe for KRT17/KRT5-low aberrant epithelial states, SPP1 macrophage "
    "niches, fibrotic ECM neighborhoods and orthogonal Xenium/Visium HD-style checks.",
    {
        "type": "object",
        "properties": {
            "platforms": {"type": "array", "items": {"type": "string"}},
            "epithelial_markers": {"type": "array", "items": {"type": "string"}},
            "niche_markers": {"type": "array", "items": {"type": "string"}},
            "sample_groups": {"type": "array", "items": {"type": "string"}},
            "seed": {"type": "integer", "default": 0},
        },
    },
)
def ipf_krt17_spatial_validation_recipe(
    platforms: Optional[List[str]] = None,
    epithelial_markers: Optional[List[str]] = None,
    niche_markers: Optional[List[str]] = None,
    sample_groups: Optional[List[str]] = None,
    seed: int = 0,
):
    plats = _platform_names(platforms or ["xenium", "visium_hd"])
    epi = epithelial_markers or ["KRT17", "KRT5", "KRT8", "EPCAM", "KRT14", "TP63"]
    niche = niche_markers or ["SPP1", "TGFB1", "COL1A1", "COL3A1", "ACTA2", "APOE"]
    groups = sample_groups or ["control_lung", "ipf_early_or_normal_appearing", "ipf_fibrotic"]
    params = {"platforms": plats, "epithelial_markers": epi, "niche_markers": niche, "sample_groups": groups, "seed": seed}
    recipe_hash = _recipe_hash("ipf_krt17_spatial_validation_recipe", params)
    return {
        "recipe_hash": recipe_hash,
        "params": params,
        "validation_arms": [
            "KRT17 epithelial marker score with KRT5-low/KRT17-high stratification.",
            "SPP1 macrophage and fibroblast/ECM niche co-localization.",
            "TGF-beta / APOE / TP53-associated program scoring as hypothesis-generating context.",
            "Matched scRNA-seq or atlas reference mapping; do not infer origin from spatial data alone.",
            "Orthogonal platform check: targeted imaging for specificity plus Visium HD/whole-transcriptome bins for discovery.",
            "Morphology-aware check: compare normal-appearing alveoli, airway-adjacent and fibrotic regions.",
        ],
        "script": _render_ipf_script(epi, niche, groups, seed),
        "reporting_contract": [
            "State platform, panel genes, segmentation QC and bin size before biological conclusions.",
            "Report per-donor effects and avoid treating neighboring cells/spots as independent replicates.",
            "Phrase KRT17 state origin/mechanics as a hypothesis unless supported by perturbation or lineage evidence.",
        ],
        "provenance_skeleton": _provenance("ipf_krt17_spatial_validation_recipe", recipe_hash, params),
    }


def _render_ipf_script(epi: List[str], niche: List[str], groups: List[str], seed: int) -> str:
    return f'''# IPF KRT17 spatial validation recipe.
import json
import numpy as np
import scanpy as sc
import squidpy as sq

np.random.seed({seed})
adata = sc.read_h5ad("spatial_preprocessed.h5ad")
groups = {groups!r}
for required in ["sample_id", "group"]:
    assert required in adata.obs, f"missing {{required}} metadata"

def score(name, genes):
    present = [g for g in genes if g in adata.var_names]
    assert len(present) >= 2, f"too few genes present for {{name}}"
    sc.tl.score_genes(adata, present, score_name=name)
    return present

epi = score("KRT17_epithelial_state_score", {epi!r})
niche = score("SPP1_fibrotic_niche_score", {niche!r})
adata.obs["KRT17_candidate"] = adata.obs["KRT17_epithelial_state_score"] >= adata.obs["KRT17_epithelial_state_score"].quantile(0.95)
sq.gr.spatial_neighbors(adata)
sq.gr.nhood_enrichment(adata, cluster_key="KRT17_candidate")
summary = adata.obs.groupby(["sample_id", "group"], observed=True)[["KRT17_epithelial_state_score", "SPP1_fibrotic_niche_score", "KRT17_candidate"]].mean()
summary.to_csv("ipf_krt17_spatial_scores_by_sample.tsv", sep="\\t")
json.dump({{"epithelial_markers_present": epi, "niche_markers_present": niche, "groups": groups}}, open("ipf_krt17_recipe_meta.json", "w"), indent=2)
adata.write_h5ad("ipf_krt17_spatial_scored.h5ad")
'''


if __name__ == "__main__":
    server.run()
