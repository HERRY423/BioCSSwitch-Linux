---
name: biomedical-ml-strategy
description: Use for biomedical machine learning strategy, multimodal foundation models, virtual cells, perturbation-response prediction, AI drug discovery ML, federated learning, privacy-preserving medical ML, digital twins, clinical ML validation, model calibration, external validation, self-driving laboratories, AI co-scientist planning, or adding an ML section to BioCSSwitch. Do not use to claim that a model has run; generate recipes, validation gates and provenance only.
---

# Biomedical ML Strategy

This skill turns biomedical ML ideas into reproducible BioCSSwitch plans. It does not train heavy models or make clinical claims. It routes frontier ideas through study design, validation gates, privacy boundaries and provenance.

## Workflow

1. Call `biomedical_ml_capability_map` first to choose the relevant frontier and failure modes.
2. For any ML prediction task, call `ml_study_design_recipe` before recommending a model.
3. For multimodal work, call `multimodal_foundation_model_plan`; require single-modality and late-fusion baselines.
4. For patient/EHR or multi-institutional data, call `federated_learning_recipe` if raw data cannot centralize, and route PHI through `sensitive-mode`.
5. For single-cell or spatial perturbation prediction, call `virtual_cell_perturbation_plan` and hand off to `bio-scfm` / `bio-spatial`.
6. For AI drug discovery, call `ai_drug_discovery_ml_plan`; separate target evidence, molecule evidence, ADMET/safety and orthogonal assays.
7. For autonomous experimentation, call `self_driving_lab_plan`; keep human approval, stopping rules and assay QC explicit.
8. Before writing conclusions, call `biomedical_ml_validation_gate` for the intended claim scope.
9. Close biological or medical claims with evidence audit and an uncertainty-first summary.

## Do

- Split by patient, donor, site, slide or perturbation target before expanding to cells, spots, image tiles or visits.
- Use external validation and calibration for translational or clinical claims.
- Report baseline models, ablations, confidence intervals and subgroup/site performance.
- Attach dataset, split, preprocessing, model-version, seed and metric hashes.
- Keep foundation models framed as representations that need baselines and validation.
- State when an ML output is hypothesis-generating rather than validated biological evidence.

## Don't

- Do not call a script runnable when it contains a skeleton guard.
- Do not present internal test performance as clinical readiness.
- Do not use random cell/tile/visit splits as evidence of patient-level generalization.
- Do not claim a virtual-cell response without held-out perturbation or wet-lab validation.
- Do not claim drug discovery success from docking, generated affinity or literature association alone.
- Do not let PHI or site-level patient data leave governance boundaries for convenience.

## Handoffs

- Evidence and claim grounding: `evidence-audit`, `scientific-critique`, `uncertainty-first`.
- PHI or clinical records: `sensitive-mode`.
- Single-cell and foundation models: `single-cell-prep`, `scfm-embed`, `sc-analysis`.
- Spatial and histology-to-ST: `spatial-analysis`.
- Drug/target databases: `target-discovery`, `bio-drug`, `bio-gene`.
