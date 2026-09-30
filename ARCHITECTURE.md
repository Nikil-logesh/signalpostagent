# Signalpost architecture

## Authority

`RULES.md` has priority, followed by the checked-in builder kit under `kit/`, followed by implementation preferences. The kit's output contract and run interface must not be broken.

## Pipeline

1. Read and validate organisation numbers from the evaluator input.
2. Anchor identity from official Brønnøysundregistrene data.
3. Fetch official accounts, roles, groups, and registered workplaces with cached provenance.
4. Optionally fetch the register-listed website, respecting public URL safety and robots policy.
5. Publish website facts only after exact-entity identity matching and literal evidence verification.
6. Compare fresh profiles with prior snapshots and emit provenance-backed material changes.
7. Write one deterministic terminal envelope per input, including explicit unavailable/blocked states.

## Default policy

The register-only path works without model keys, search keys, or paid APIs. LLM extraction is disabled by default and is permitted only on already fetched, identity-verified page text. External search/social/jobs/news/review connectors are quarantined unless the governing rules and rights evidence permit publication.

## Budgets and state

SQLite stores request/cache metadata and previous profiles. Raw response snapshots remain content-addressed. The run enforces a global request budget, a per-company budget, concurrency limits, and a wall-clock deadline; interrupted runs preserve valid partial output and terminal envelopes for completed work.

## Evidence invariants

Every published claim points to a source URL, retrieval time, content hash, and literal evidence snippet/span. Financial values come only from official accounts or official filings. Identity uncertainty fails closed to official register facts.
