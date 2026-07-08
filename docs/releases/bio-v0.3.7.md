# BioCSSwitch bio-v0.3.7

Release date: 2026-07-08

BioCSSwitch bio-v0.3.7 is a biomedical infrastructure hardening release. It upgrades the GRADE engine from outcome-only heuristics into structured evidence dossiers, turns the single-cell layer into executable workflow recipe generation for established toolchains, and gives the pack system a schema-backed dependency model suitable for broader MCP exposure.

## Highlights

- **Structured GRADE evidence dossiers**
  - Adds dossier-level evidence-body modeling through `grade_evidence_dossier`.
  - Aggregates study design, sample size, directness, consistency, precision, publication bias, upgrades, and RoB-style domain ratings across studies.
  - Replaces the hard-coded starting-certainty path with weighted design and risk-of-bias signals.
  - Adds probabilistic EtD reasoning through `etd_probabilistic_recommendation`, including benefit/harm balance, values, resources, equity, acceptability, feasibility, uncertainty, and Monte Carlo-style support intervals.

- **Real single-cell workflow recipes**
  - Adds `sc_workflow_recipe` for Snakemake and Nextflow-style workflow package generation.
  - Wires concrete scanpy, Scrublet, scvi-tools, Harmony, CellTypist, SingleR, Seurat, Bioconductor, and nf-core/scrnaseq handoff steps into generated recipes.
  - Covers QC, doublet detection, normalization, HVG selection, dimensionality reduction, batch correction, clustering, marker calling, annotation, multimodal hooks, and scFM embedding preparation.

- **Pack manifest infrastructure**
  - Adds `packs/pack.schema.json` as the canonical manifest contract.
  - Extends pack manifests with `version`, `dependencies`, and `requires_tools`.
  - Validates pack IDs, semantic versions, tool requirements, and dependency edges during desktop pack loading.
  - Preserves compatibility with legacy string-form `optional_env` values.
  - Updates the desktop UI and fallback pack model to surface dependency metadata.

- **Broader biomedical pack surface**
  - Expands scFM, spatial, ML, critique, drug, and evaluation support already present in the current BioCSSwitch workspace.
  - Keeps `bio-mcp-shim` positioned as the compatibility layer for local biomedical MCP tool exposure.

## Verification

Completed on the local Windows workspace before release packaging:

- `python -m py_compile packs/bio-audit/grade_server.py packs/bio-singlecell/singlecell_server.py test/test_bio_offline.py`
- `python test/test_bio_offline.py`
- `node --check desktop/src/main.js`
- `git diff --check`

Not completed in this local environment:

- Rust/Tauri checks: `cargo` is not installed on this Windows machine.
- GitHub Release publication through `gh`: the stored GitHub token for `HERRY423` is invalid and needs re-authentication before `gh release create` can run.

## Notes

The upstream CSSwitch tags remain separate from BioCSSwitch biomedical releases. This release intentionally uses the `bio-v0.3.7` tag so the release points at the BioCSSwitch branch state.
