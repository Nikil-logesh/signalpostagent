# Signalpost

Signalpost builds evidence-first profiles for Norwegian organisation numbers. The official Brønnøysundregistrene record is the identity anchor; company websites are enriched only after an exact-entity gate. The default path is register-only and requires no LLM or external search key.

## Current status

Phase 1 project shell is in place. The kit's evaluator contract and reference workflow remain authoritative. Implementation phases will add deterministic sampling, official register/accounts extraction, identity-gated website enrichment, refresh diffs, budgets, and submission tooling.

## Setup

Requires Python 3.12+ and the dependencies declared in `pyproject.toml`. Copy `.env.example` to `.env`; keep `LLM_ENABLED=false` unless an approved endpoint is configured.

```bash
python -m pip install -e '.[dev]'
make test
```

## Run interface

The intended evaluator-compatible command is:

```bash
make run INPUT=<organisation-batch.jsonl> OUT=out/
```

The CLI will always emit one terminal envelope per input organisation number. Missing information is represented explicitly and is never converted to zero.

## Source and safety boundary

Only the official registry/accounts layer and an identity-verified company-owned website are enabled by default. Search, social, jobs, news, reviews, and other external connectors remain quarantined unless the source rights and kit gates permit publication. Secrets are read from environment variables only.

See `RULES.md`, `kit/README.md`, `kit/OUTPUT_CONTRACT.md`, and `ARCHITECTURE.md` for the governing contract and design.
