---
name: crossmodal-discovery
description: Use for cross-modal target discovery from an unmet clinical need, combining literature, genetics, druggability, clinical trials, single-cell, and spatial evidence in one auditable context.
---

# Cross-modal discovery

Use this skill when the user asks for a new target, a translational opportunity, an unmet-need landscape, or a conclusion that must combine several BioCSSwitch packs.

## Required workflow

1. Call `crossmodal_plan_unmet_need` with a concrete disease and unmet need. Preserve its `context` as the only shared evidence state.
2. Execute plan steps in stage order. Resolve `$outputs...` references from actual earlier tool results and fan out `{target}` steps only over targets present in the context.
3. After every external pack call, pass the matching plan step and real result to `crossmodal_reduce_evidence`. Never summarize a result into an unsupported claim before reduction.
4. For measured single-cell or spatial results, add explicit claim-level records with `crossmodal_integrate_observations`. A generated analysis recipe is provenance, not biological evidence.
5. Call `crossmodal_synthesize`. If it reports conflicts, call `kg_generate_hypotheses` before recommending a decisive next experiment.
6. Present target rank, evidence coverage, corroborating sources, conflicts, missing modalities, and the next discriminating data collection step together.

## Evidence contract

- `supports`, `contradicts`, and `neutral` must be explicit. No result or a failed search means unknown, not refuted.
- No trial record means trial saturation is unknown. Only a completed zero-hit search may support a low-saturation interpretation.
- Preserve PMID, DOI, NCT, Ensembl, ChEMBL, and source-tool provenance exactly as returned. Never invent identifiers.
- Cross-modal corroboration requires independent sources; duplicate database rows are not replication.
- Rankings prioritize investigation only. They do not establish mechanism, efficacy, safety, or clinical utility.
- For PHI or patient-level inputs, use `bio-privacy` first and do not place identifiers in an evidence context.

## Minimum final table

For every shortlisted target report: score, assessed modalities, missing modalities, strongest evidence, explicit conflict status, trial-saturation basis, and a falsifiable next experiment.
