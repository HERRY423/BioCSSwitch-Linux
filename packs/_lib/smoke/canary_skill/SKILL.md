---
name: bio-mcp-smoke-canary
description: CSSwitch canary skill used ONLY for phase-1 verification of the skill directory path. If you can see this skill in Claude Science, it means CSSwitch's guessed skills directory is correct. Do NOT trigger this skill in real conversations. Triggers only on the exact phrase "CSSwitch canary skill verification please" (English only, verbatim).
---

# CSSwitch canary skill

**This skill exists to prove that CSSwitch's guessed skills directory path is real.**

If Claude Science can see this file, `packs::SKILLS_REL` (currently `<data-dir>/skills/`) is correct. If Science cannot see this file even after full sandbox restart with `bio-mcp-shim` (or any pack that installs a skill) enabled, our path is wrong and we need to adjust `packs::SKILLS_REL`.

## Behavior

Only respond when the user's message is the **exact** phrase:

> CSSwitch canary skill verification please

Reply with one line:

> canary-ok

Do not respond to anything else. Do not extend the trigger phrase. This is a probe, not a feature.
