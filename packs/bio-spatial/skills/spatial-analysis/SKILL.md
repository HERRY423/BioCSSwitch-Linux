---
name: spatial-analysis
description: Use for spatial transcriptomics, Visium, Visium HD, Xenium, CosMx, MERFISH, Slide-seq, Stereo-seq, DBiT-seq, GeoMx, RAEFISH, spatial domains, spatially variable genes, spatial communication, spatial multi-omics, H&E-to-spatial prediction, 3D/4D spatial atlases, spatial deconvolution, rare spatial cell detection, spatial foundation models, scGPT-Spatial, Nicheformer, CELLama, STORM, IPF spatial niches, KRT17 epithelial states and orthogonal spatial validation. Do not use for ordinary dissociated scRNA-seq only; route that to sc-analysis / single-cell-prep.
---

# Spatial Transcriptomics Analysis

This skill coordinates spatial transcriptomics recipe generation. It does not run heavy spatial analysis or claim biological results. It produces platform-aware recipes, scripts/skeletons, provenance fields and uncertainty boundaries.

## Workflow

1. Clarify platform and data shape: Visium, Visium HD, Xenium, CosMx, MERFISH, Slide-seq, Stereo-seq, DBiT-seq, GeoMx or emerging sequencing-free imaging; matched histology; segmentation/ROI source; coordinate key; raw counts; panel genes; donors and sample groups.
2. Call `spatial_platform_matrix` before cross-platform interpretation or platform selection.
3. Call `spatial_preprocess_recipe` to generate platform-specific QC, spatial graph and provenance steps.
4. For spatially variable genes or spatial domains, call `spatial_domain_recipe`; report SVG tables, graph settings and shuffled-coordinate controls.
5. For cell-type mixture or reference transfer, call `spatial_deconvolution_recipe`. For rare populations, require `marker_score` as a baseline even when a complex method is also used.
6. For rare cell detection, call `spatial_rare_cell_recipe`; require negative controls, donor-level replication and an orthogonal check before strong claims.
7. For cell-cell communication or niche signaling, call `spatial_communication_recipe`; treat ligand-receptor output as candidate interactions unless adjacency, controls and donor summaries support it.
8. For RNA plus protein/ATAC/metabolite/lipid/histology data, call `spatial_multimodal_recipe`; keep modality controls and provenance separate.
9. For virtual ST or H&E-to-expression prediction, call `spatial_histology_prediction_plan`; require donor/slide/site holdouts and measured-ST validation.
10. For serial-section, whole-organ or spatiotemporal maps, call `spatial_atlas_3d_recipe`.
11. For translational, diagnostic or companion-diagnostic wording, call `spatial_translation_readiness_gate`.
12. For spatial foundation models, call `spatial_scfm_model_matrix` and `spatial_scfm_plan`; always pair the foundation model with simpler expression-only and marker/deconvolution baselines.
13. For IPF/KRT17 questions, call `ipf_krt17_spatial_validation_recipe` and state what is validation, what is association and what remains mechanistic hypothesis.
14. Close with an uncertainty-first summary if the answer contains biological or translational claims.

## Do

- Keep platform, bin size, panel, segmentation and coordinate provenance explicit.
- Separate discovery platforms from validation platforms.
- Use sample/donor replication for claims; do not treat neighboring spots/cells as biological replicates.
- Audit neighbor contamination and segmentation quality for imaging platforms.
- Audit ROI selection rules for GeoMx/ROI platforms.
- Preserve raw counts and panel metadata.
- Use shuffled-coordinate, shuffled-label or decoy-marker controls for spatial domains, communication and rare-cell claims.
- Split histology prediction by donor/slide/site before tiling; never evaluate virtual ST with random tile-level splits.
- Record 3D registration residuals and keep original 2D coordinates immutable when building atlases.

## Don't

- Do not pool platforms without platform-stratified QC and covariates.
- Do not claim a rare cell type from one deconvolution method alone.
- Do not treat spatial foundation-model embeddings as self-explaining biological evidence.
- Do not treat ligand-receptor co-expression as proof of signaling.
- Do not present H&E-predicted expression as measured spatial transcriptomics.
- Do not use translational or diagnostic language without replication, orthogonal validation, benchmarks and locked provenance.
- Do not infer cell-state origin or mechanics from static spatial co-localization alone.

## Handoffs

- Dissociated scRNA-seq QC, doublet, batch and annotation: `single-cell-prep`.
- scFM provenance and embedding quality for non-spatial models: `scfm-embed`.
- DEG, trajectory, communication and enrichment after annotation: `sc-downstream-analysis`.
- Literature or medical claims: `evidence-audit` and `uncertainty-first`.
