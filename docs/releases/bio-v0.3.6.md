# BioCSSwitch bio-v0.3.6

Release date: 2026-07-07

BioCSSwitch bio-v0.3.6 merges the upstream CSSwitch 0.3.6 provider baseline into the biomedical research branch, then layers in new BioCSSwitch-only research capabilities for critique, spatial biology, and multi-agent fallback.

## Highlights

- **Upstream CSSwitch 0.3.6 baseline**
  - Adds custom OpenAI Responses-compatible provider support.
  - Hardens DashScope Responses tool requests and schema compatibility.
  - Refactors Anthropic-compatible provider handling into clearer policy and compatibility modules.
  - Adds a provider capability matrix and stronger proxy golden tests.

- **BioCSSwitch biomedical research packs preserved and extended**
  - Keeps the local biomedical MCP/Skill pack system, bundled under the BioCSSwitch app resources.
  - Preserves BioCSSwitch branding, bundle identity, pack configuration panel, sensitive-mode guardrails, and smoke verification flow.
  - Adds a dedicated `test/run-bio.sh` layer so upstream S0 test aggregation can include biomedical offline regression checks.

- **New critique and counter-evidence engine**
  - Adds `bio-critique` with scientific critique workflows.
  - Adds rule-based extrapolation checks, methodology checks, believability scoring, and counter-experiment design helpers.
  - Targets common biomedical failure modes such as animal-to-human overclaiming, endpoint extrapolation, underpowered study claims, and missing validation paths.

- **New spatial biology support**
  - Adds `bio-spatial` for spatial transcriptomics planning and review.
  - Includes platform guidance for Xenium, Visium HD, MERFISH-style workflows, spatial preprocessing recipes, rare-cell deconvolution guardrails, spatial foundation model planning, and IPF/KRT17-focused report contracts.

- **Ultra / WellFallback orchestration**
  - Adds task routing, fallback policy, and ultra orchestration modules.
  - Allows BioCSSwitch to route biomedical tasks through planner, critic, verifier, and fallback paths while preserving sensitive-mode constraints.
  - Falls back safely for streaming requests and avoids cloud routing for PHI-sensitive paths.

## Verification

Completed on the local Windows workspace:

- `python -m py_compile proxy/csswitch_proxy.py proxy/provider_policy.py proxy/anthropic_compat.py proxy/fallback_policy.py proxy/task_router.py proxy/ultra_orchestrator.py`
- `python -m unittest discover -s test -p "test_*.py" -v` — 164 tests passed.
- `python test/test_bio_offline.py` — all biomedical offline checks passed.
- JSON/TOML config parsing for desktop package files passed.
- `git diff --check` passed.

Not completed in this local environment:

- Rust/Tauri build checks: `cargo` is not installed on this Windows machine.
- Bash layered runner: current Windows environment has no usable WSL distribution.
- Node virtual OAuth symlink tests: Windows symlink permissions/path semantics block the test setup.

## Notes

The upstream `v0.3.6` tag belongs to pure CSSwitch. This BioCSSwitch release intentionally uses the `bio-v0.3.6` tag so the release points at the merged biomedical branch rather than the upstream-only commit.
