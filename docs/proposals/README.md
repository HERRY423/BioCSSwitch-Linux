# Proposal Index

This directory holds larger design proposals that are not yet release notes or stable operating docs. Keep active implementation guidance in `docs/`, and use these files for exploratory roadmaps, tradeoffs, and staged plans.

| Proposal | Status | Scope | Next tracking home |
| --- | --- | --- | --- |
| [Bioinformatics Expansion](bioinformatics-expansion.md) | Proposed | Adds structure biology, genetics/GWAS, regulatory genomics, oncology immunology, and bulk multi-omics packs. | Break into pack-level issues before implementation. |
| [Single-Cell Upgrade Plan](single-cell-upgrade-plan.md) | In progress | Expands `bio-singlecell`, `bio-scfm`, and downstream scRNA-seq workflows. | Track concrete shipped work in `docs/packs.md` and release notes. |
| [Critique Engine Design](critique-engine-design.md) | Proposed | Counter-evidence, methodology critique, believability scoring, and counter-experiment design. | Promote stable pieces into `packs/bio-audit` docs. |
| [Ultra Subagent Design](ultra-subagent-design.md) | Proposed | Ultra mode orchestration, subagents, WellFallback, routing, and fallback ledger behavior. | Track implementation in proxy and provider-routing docs. |

## Lifecycle

- Proposed: useful design direction, not yet committed as product behavior.
- In progress: has at least one implemented slice or active branch of work.
- Accepted: design is stable enough to split into implementation tasks.
- Superseded: kept for history, with a link to the replacement.

When a proposal becomes implementation guidance, move that stable subset into the main docs tree and leave a note here pointing to the canonical doc.
