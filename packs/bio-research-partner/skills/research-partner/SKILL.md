---
name: research-partner
description: Use when the user opts into a local research-interest model, wants personalized paper/preprint/trial updates, saves or rejects research suggestions, asks for a proactive briefing, or wants workflow prediction across sessions.
---

# Privacy-first research partner

This skill turns repeated research interactions into a local, inspectable profile. It is not permission to retain conversation text.

## Consent and data boundary

1. Before the first `research_interest_observe` call, obtain explicit opt-in for local learning. Pass `consent=true` only within that consent scope. A user asking a biomedical question is not consent by itself.
2. Send only structured public concepts such as HGNC symbols, disease terms, pathway names, PMID/DOI/NCT identifiers, and short workflow slugs. Never send raw prompts, abstracts, notes, filenames, PHI, or arbitrary metadata.
3. Default storage is HMAC-pseudonymized aggregates. No event history is retained; time is reduced to coarse weekday/weekend buckets.
4. Honor inspection and deletion immediately with `research_interest_inspect` and `research_interest_delete`.

## Learning events

- Saving a paper: `paper_saved` with its public ID and canonical topics.
- Repeated gene/target lookup: `entity_queried`.
- Accepted or rejected suggestion: `suggestion_accepted` / `suggestion_rejected`; rejection is weak negative feedback, not proof that a topic is irrelevant.
- Completed workflow: `workflow_observed` with a short task slug.
- Shown recommendation: `recommendation_shown` so cooldown deduplication can work.

## Proactive loop

1. At the beginning of a research session, call `research_session_brief` only if a local profile exists. Build `topic_catalog` from concepts already present in the local project, saved-paper index, or local KG.
2. The returned refresh actions are a plan, not executed requests. Keep `allow_remote_queries=false` until the user or an existing policy explicitly authorizes outbound public-database queries.
3. Execute authorized actions through `bio-lit` / `bio-trials`, normalize results into the candidate schema, and call `research_updates_rank` locally.
4. Explain why each suggestion matched, distinguish relevance from evidence quality, and include source IDs. Do not present a high relevance score as scientific validity.
5. Record `recommendation_shown`, then record later acceptance or rejection if the user provides that feedback.

## Active behavior boundary

This version supports session-start proactive briefings and scheduler-ready refresh actions. It does not silently run a background daemon, contact external services, or issue OS notifications. Any host scheduler must preserve the same consent, sensitive-mode, endpoint, cooldown, and deletion guarantees.
