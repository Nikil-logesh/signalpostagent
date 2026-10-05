# SIGNALPOST — Architecture

> **No LLM. No fabrication. Every claim has evidence.**
>
> `RULES.md` has priority, followed by the checked-in builder kit under `kit/`, followed by implementation preferences. The kit's output contract and run interface must not be broken.

---

## System Overview

```
Input: Norwegian org numbers (JSONL batch)
          │
          ▼
  ┌─────────────────┐
  │   run.py (CLI)  │  ← evaluator-compatible interface
  │  ThreadPoolExec │     --organisations --bulk --output --report
  └────────┬────────┘
           │  per-company thread
           ▼
  ┌─────────────────────────────────────────────────────┐
  │              pipeline.py  run_company()             │
  │                                                     │
  │  1. OfficialClient  (official.py)                   │
  │     ├── BRREG Entity API   → registry evidence      │
  │     ├── BRREG Roles API    → leadership evidence    │
  │     ├── BRREG Group API    → group evidence         │
  │     ├── BRREG Subunits API → locations evidence     │
  │     ├── Regnskapsregisteret → financial evidence    │
  │     └── Account years API  → filing history         │
  │                                                     │
  │  2. fetch_and_gate_website()  (website.py)          │
  │     ├── robots.txt check                            │
  │     ├── Private IP guard                            │
  │     ├── Static HTTP fetch (trafilatura + extruct)   │
  │     └── Identity gate (org-number → token scoring)  │
  │         score >= 0.9 → published as company_owned   │
  │         score < 0.9  → published as ambiguous        │
  │                                                     │
  │  3. accounting_obligation_assessment() (kit reuse)  │
  │                                                     │
  │  4. build_summary()  (summary.py)                   │
  │     Deterministic 2–4 sentence summary              │
  └──────────────────────┬──────────────────────────────┘
                         │
                         ▼
            profile dict + evidence dict
                         │
                         ▼
         _terminal_envelope()  (run.py)
           module states → complete/not_found/blocked/source_error
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
  out/profiles.jsonl           out/envelopes.jsonl
  (internal enriched)          (scored terminal artefact)
          │
          ▼
  report/build_report.py
  → out/report/index.html  (static HTML, UX points)
```

---

## Key Design Decisions

### 1. No LLM — by design
LLMs are non-deterministic and expensive. Our no-LLM stance is a feature:
- Every run with the same inputs produces byte-identical output (modulo timestamps)
- Zero third-party cost
- Full reproducibility for Builderr evaluation
- No hallucination risk

### 2. Fail-closed identity gate
The identity gate is strict (scoring in `website.py::_score_identity`):

| Score | Status | Condition |
|-------|--------|-----------|
| 1.0 | `exact` ✅ | Org-number digits appear in page text |
| 0.95 | `exact` ✅ | All name tokens in domain or page text |
| 0.95 | `exact` ✅ | Single distinctive token + ≥100 chars of content |
| 0.85 | `review` ❌ | ≥75% overlap, ≥2 tokens |
| 0.65 | `uncertain` ❌ | ≥50% overlap, ≥2 tokens |
| 0.30 | `uncertain` ❌ | Default / parked domain |

**score ≥ 0.9 → `available`**  
**score < 0.9 → `ambiguous`** — zero wrong-company publications.

### 3. Evidence provenance on every claim
- `source_url` — exact endpoint URL
- `content_sha256` — SHA-256 of raw HTTP body
- `retrieved_at` — ISO 8601 UTC
- `claim_span` — text excerpt proving the claim
- `source_class` — one of: `official_registry_live`, `official_annual_accounts`, `official_roles`, `official_group_structure`, `official_subunits`, `company_owned`

### 4. HTTP cache (SQLite, ETag-based)
- Conditional requests (`If-None-Match`, `If-Modified-Since`)
- 304 Not Modified → reuse cached body, count as 0 new bytes
- Content-addressed: same URL + same body → same SHA-256
- Guarantees idempotence across daily refresh runs

### 5. Kit reuse over rewrite
We import `kit/src/norway_company_agent/` via `pythonpath` in `pyproject.toml`:
- `refresh.py::diff_profile()` — change detection across runs
- `batch.py::validate_envelopes()` — envelope contract validation
- `official.py::accounting_obligation_assessment()` — deterministic obligation classification

---

## Module Map

| Module | Location | Responsibility |
|--------|----------|----------------|
| `run.py` | root | CLI entry, thread pool, checkpoint, validation, report |
| `pipeline.py` | `src/signalpost/` | Per-company orchestration, never raises |
| `official.py` | `src/signalpost/` | All BRREG endpoints, SQLite cache, ETag support |
| `website.py` | `src/signalpost/` | Robots, IP guard, fetch, identity gate, extra pages |
| `summary.py` | `src/signalpost/` | Deterministic 2–4 sentence summaries |
| `models.py` | `src/signalpost/` | Pydantic `CompanyEnvelope`, `Claim`, `Evidence` |
| `sampling.py` | `src/signalpost/` | Mod-11 validation, stratified sampling, pool scanner |
| `logging.py` | `src/signalpost/` | JSON structured logging |
| `build_report.py` | `report/` | Self-contained static HTML report builder |
| `refresh.py` | `kit/src/...` | Change tracking (imported, not modified) |

---

## Identity Gate Flow

```
registry.website (bulk CSV)
        │
        ▼
  normalise URL ──→ safe_url() ──→ private IP? → BLOCKED
        │
        ▼
  robots.txt check ──→ Disallow: / → BLOCKED
        │
        ▼
  HTTP GET (12s timeout, 512 KB max)
        │
  ┌─────┴────────────────────────────┐
  │ trafilatura → boilerplate-free   │
  │               main text          │
  │ extruct → JSON-LD / OpenGraph    │
  └─────┬────────────────────────────┘
        │
        ▼
  _score_identity(org_number, legal_name, text, structured, final_url)
        │
  score >= 0.9? ──YES──→ fetch extra pages (/om-oss, /about, ...)
        │                        │
        │                        ▼
        │               status: "available"  (company_owned)
        │
        NO──→ status: "ambiguous"  (identity gate failed)
```

---

## Request Budget

```
Per company (typical):
  registry             1 req  (~1.2s)
  financials           1 req  (~1.2s)
  roles                1 req  (~1.2s)
  locations            1 req  (~1.2s)
  financial_history    1 req  (~1.2s)
  website homepage     1 req  (0 if no URL / blocked)
  extra pages          0–4 req (only if identity gate passes)
  ─────────────────────────────────────────────────
  Total                ~5–10 req / 5–15s per company

100-company run:
  ~500–1000 requests | well within MAX_REQUESTS=2000
  ~8–25 min at 8 workers | well within MAX_RUNTIME_SECONDS=2700

Rate limiting:
  financial_history: 2.1s gap enforced by kit official.py
  General: 8-worker concurrency limits overall rate
```

---

## Scoring Strategy

| Category | Points | Our Approach |
|----------|--------|-------------|
| Recall & coverage | 50 | Register (100%) + financials + verified websites + roles |
| Precision & evidence | 30 | Strict identity gate + full SHA-256 provenance on all claims |
| Synthesis | 12 | Deterministic 2–4 sentence summary citing real evidence |
| UX | 8 | Dark-mode HTML report, real-time search, mobile layout |

**Qualification floor:** 65/100  
**Target:** 70+ — register + accounts baseline ~25 pts; websites + synthesis push past 65.  
**Stretch:** 80+ — requires external footprint (jobs, news, reviews) in a future revision.

---

## Source Authority

`RULES.md` → `kit/` → this document.  
Any conflict with a higher-priority source is reported and resolved in favour of the higher-priority source.
