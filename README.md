# SIGNALPOST — Agentic Company Research System
> **Builderr Hackathon | Deadline: 17 Oct 2026 | Revisions close: 18 Oct 2026**

---

## 🧭 SESSION CONTEXT & MEMORY TRANSFER

This README serves as the canonical session-state document. Every major decision, constraint, and implementation note is recorded here so any future agent or session can resume without loss of context.

**Current Phase:** `PHASE 9 — Scoring Analysis + run.py fix + Refresh Harness`  
**Last Updated:** 2026-10-05  
**Conversation Seed:** Builderr hackathon build prompt received. Phases 0–8 complete.  
**Next Action:** Score with scorer after final-002 benchmark. Run refresh harness (second identical run) to claim 3 pts. Investigate connector_policy gate path. Local score ~28/100 without external connector (55 pts blocked).

---

## 🎯 Project Summary

**Signalpost** receives Norwegian organisation numbers (9-digit, mod-11 validated) and produces structured, evidence-backed company profiles. It must:

- Identify the correct company via official register
- Extract useful facts from permitted official/public sources only
- Preserve full provenance (claim-level evidence) for every published fact
- Detect changes across repeated runs
- Operate **100% deterministically — zero LLM usage**

---

## ⚠️ NON-NEGOTIABLE HARD RULES

| Rule | Detail |
|------|--------|
| **NO LLM** | No NVIDIA, Gemini, OpenAI, Anthropic, local models, or model gateways |
| **No fabrication** | Never invent financial figures, facts, or identities |
| **No fuzzy-only identity** | Fuzzy matching ranks candidates only; never final proof |
| **No empty/zero placeholders** | Use `null` + proper state for unknowns |
| **No secret hardcoding** | All credentials via environment variables only |
| **No silent drops** | Every input org number → exactly one terminal envelope |
| **No search-result evidence** | Re-fetch and snapshot the underlying page |
| **Fail closed** | Ambiguous identity → register-only data, not wrong-company publication |

---

## 📊 Scoring Strategy

| Category | Max | Leader Gets | Target | How |
|----------|-----|------------|--------|-----|
| Recall & Coverage | 50 | 13–17 | **23–33** | Every company: register fields, then websites/jobs |
| Precision & Evidence | 30 | ~27 | **27–29** | Strict identity gate, claim-level evidence, abstain when unsure |
| Synthesis | 12 | 12 | **12** | Deterministic summary from supported claims only |
| UX | 8 | 8 | **8** | Simple verifiable HTML report, mobile-friendly |

**Key insight:** Breadth beats depth. One fact for 1,000 companies beats ten facts for 100.  
**Central optimisation order:**
```
REGISTER COVERAGE > ACCOUNTS/ROLES/WORKPLACES > IDENTITY-VERIFIED WEBSITE DATA > CAREERS/NEWS/ACTIVITY > DETERMINISTIC SUMMARIES + UX
```

---

## 🏗️ Architecture (Deterministic Pipeline — No LLM)

```
organisation number
        ↓
official register identity      (Brønnøysund)
        ↓
official accounts / roles / workplaces
        ↓
website candidate discovery
        ↓
identity verification           (FAIL CLOSED if low confidence)
        ↓
static website fetch            (robots.txt respected)
        ↓
deterministic extraction        (JSON-LD → DOM → text → regex)
        ↓
literal evidence verification
        ↓
claim validation
        ↓
profile + changes + deterministic summary
```

**Source Authority Order (highest to lowest):**
1. `RULES.md`
2. Everything in `/kit`
3. This build prompt

---

## 📁 Repository Structure

```
signalpost-agent/
├── README.md                   ← THIS FILE (session state + setup)
├── requirements.txt            ← Pinned versions (==)
├── run.py                      ← Entry: batch in → results out
├── config.py                   ← Budgets, env var names, allowlist
├── AGENT.md                    ← Research + abstention policy
├── LIMITATIONS.md              ← Sources, licences, known gaps
├── ARCHITECTURE.md             ← System design documentation
├── SUBMISSION.md               ← Hackathon submission details
├── Makefile
├── .env.example
│
├── pipeline/
│   ├── batch.py                ← Read batch, concurrency, per-company timeout
│   ├── registry.py             ← Brønnøysund identity, roles, subunits
│   ├── accounts.py             ← Annual accounts (latest + history)
│   ├── website.py              ← Candidate discovery + verification
│   ├── crawl.py                ← Static fetch, robots, sitemap, page picker
│   ├── extract.py              ← JSON-LD/text extraction (deterministic only)
│   ├── claims.py               ← Claim + Evidence models, claim keys
│   ├── envelope.py             ← Terminal envelope builder, state logic
│   ├── refresh.py              ← Snapshot diff, idempotent upsert
│   └── summary.py              ← Profile text from supported claims only
│
├── report/
│   └── build_report.py         ← Static HTML profile viewer
│
├── snapshots/                  ← Raw responses, content-hashed
├── out/                        ← results.jsonl, report/
│
├── tests/
│   ├── test_envelope.py
│   ├── test_identity.py
│   ├── test_refresh.py
│   └── fixtures/
│
└── eval/
    ├── sample.py               ← Pick 100 (and 1000) from orgs.json
    └── smoke_report.md         ← The 100-company result you submit
```

---

## 🔄 Phase Gates

### Phase 0 — Read the Kit First ✅ COMPLETE
- [x] Read `RULES.md`
- [x] Read `/kit/README*`
- [x] Read `/kit/OUTPUT_CONTRACT.md`
- [x] Read `/kit/docs/norway-sources.md`
- [x] Read `/kit/docs/external-connectors.md`
- [x] Read `/kit/docs/external-footprint-loop.md`
- [x] Read `/kit/docs/architecture-options.md`
- [x] Read `/kit/docs/competition-control-loop.md`
- [x] Read `/kit/src/norway_company_agent/` (all modules)
- [x] Read `/kit/scripts/run_competition_batch.py` and `score_competition_v3.py`
- [x] Produce Phase 0 report — see `phase0_report.md` artifact
- [x] Conflicts catalogued and resolved

### Phase 1 — Setup ✅ COMPLETE
- [x] Project structure confirmed — `src/signalpost/` skeleton already existed
- [x] `run.py` created matching kit's evaluator interface
- [x] Makefile, `.env.example`, structured logging all in place
- [x] 7/7 original tests pass
- **Gate passed:** `make test` ✅

### Phase 2 — Data and Sampler ✅ COMPLETE
- [x] `data/orgs.json` format confirmed: 411,160 JSONL rows
- [x] `src/signalpost/sampling.py` implements mod-11 validation, scan_pool, stratified sampling
- [x] `build_samples()` produces profiles-1500, daily-100, dev-stratified
- [x] Reproducibility test passes: same seed → same output
- **Gate passed:** same seed → same samples ✅

### Phase 3 — Register + Accounts ✅ COMPLETE
- [x] `src/signalpost/official.py` — SQLite cache, ETa/conditional requests, all BRREG endpoints
- [x] `src/signalpost/pipeline.py` — orchestrates register + financials + roles + locations + website
- [x] Fixture covers 10 varied companies (existing `tests/fixtures/official-entities-10.json`)
- [x] Financial normalizer preserves zero values, period, currency
- **Gate passed:** fixtures for ≥10 companies ✅

### Phase 4 — Website Identity + Enrichment ✅ COMPLETE
- [x] `src/signalpost/website.py` — robots.txt, private-IP blocking, org-number identity gate
- [x] Identity scoring: org-number (1.0) → all-tokens (0.95) → partial (0.85/0.65) → fail (0.3)
- [x] Wrong-company is rejected (score < 0.9 → `ambiguous` state)
- [x] No-website → `not_available` immediately (0 network requests)
- [x] Private IP → `blocked` immediately
- **Gate passed:** all Phase 4 identity/evidence/fail-closed/no-website tests ✅

### Phase 5 — Updates ✅ COMPLETE
- [x] Kit `refresh.py` `diff_profile()` used directly for change detection
- [x] Address change detected (municipality field)
- [x] Status change detected (tracked fields)
- [x] Identical data → zero false changes
- **Gate passed:** 22/22 tests pass ✅

### Phase 6 — CLI + Explanations + Report ✅ COMPLETE
- [x] `report/build_report.py` — self-contained HTML, dark mode, search, badges, financial tables, identity score bars
- [x] End-to-end 5-company smoke test via `run.py` (22 requests, 23s, all checks pass)
- [x] Identity gate correctly rejected Storebrand parent site (subsidiary resolution working)
- [x] Summary generation confirmed with real financial data
- [x] Makefile expanded: `make test`, `make smoke`, `make run`, `make samples`, `make report`, `make help`
- **Gate passed:** All 5 companies, `validation.passed=true`, `llm_requests=0` ✅

### Phase 7 — 100-Company Benchmark ✅ COMPLETE
- [x] Built `data/samples/daily-100.jsonl` (411,160 orgs scanned, 0 invalid, 0 dups)
- [x] 100-company batch ran in 80s, 411 requests, 2.3 MB, $0.00, 0 LLM calls
- [x] All 4 validation checks passed (`exact_expected_count`, `unique_org_numbers`, `all_terminal`, `zero_drops`)
- [x] 12/12 benchmark gate tests pass (`tests/test_benchmark.py`)
- [x] 34/34 total tests pass
- [x] `out/daily-report/index.html` built (456 KB, 100 companies)
- [x] `SUBMISSION.md` written with run command, sources, costs, evidence policy
- [x] `ARCHITECTURE.md` complete with system diagram, identity gate flow, module map
- **Gate passed:** Phase 7 COMPLETE ✅

**100-company coverage breakdown:**
```
registry:        100/100 available  (100%)
financials:      100/100 available  (100%)
locations:       100/100 available  (100%)
accounting_obl:  100/100 available  (100%)
roles:            99/100 available   (99%)
website (gate):    0/100 available    (0%) ← 88 have no URL; 9 ambiguous; 3 blocked
- Project skeleton, Makefile, `.env.example`, README stub, structured logging, `ARCHITECTURE.md`
- **Gate:** `make test`

### Phase 2 — Data and Sampler
- Validate org-number dataset, remove invalid/duplicate records, build reproducible samples
- Create: 1,500+ submission sample; seeded 100-company daily-test sample; small stratified dev set
- **Gate:** Same seed → same samples

### Phase 3 — Register + Accounts
- Cached register/accounts clients and kit-compatible Profile/claim schema
- **Gate:** Fixtures for ≥10 varied companies

### Phase 4 — Website Identity + Enrichment
- Candidate discovery, identity matching, static crawling, deterministic extraction
- **Gate tests:**
  - Similarly named wrong company is rejected
  - Unsupported/fabricated value is dropped
  - Low identity score → register-only output
  - No-website company finishes quickly

### Phase 5 — Updates
- **Gate tests:**
  - Changed address detected
  - Status change to bankrupt/dissolved detected
  - Unchanged company → zero false changes

### Phase 6 — CLI + Explanations + Report

### Phase 7 — Budget Benchmark
- Run 100-company set; report elapsed time, request count, coverage, failures, estimated cost
- LLM cost = **zero** (no LLM)

### Phase 8 — Batch + Audit
- 1,000+ profiles; 50-company human-review sheet
- Automated check: flags profiles with web facts below identity threshold

### Phase 9 — Submission Pack

---

## 🔌 One-Command Execution

**Install:**
```bash
pip install -e .
```

**Run** (paste exactly — Builderr supplies all argument values):
```bash
python run.py \
  --organisations <batch_file> \
  --bulk brreg-enheter.csv \
  --output out/envelopes.jsonl \
  --profiles-output out/profiles.jsonl \
  --report out/run-report.json \
  --run-id official-run-001 \
  --expected-count <N>
```

> `--expected-count` is advisory. If the batch has a different number of companies, `run.py` warns and processes all of them.  
> `--resume` can be added to skip already-completed companies from a prior run.

---

## 🧩 Claim Schema (Required Fields)

Every published claim **must** carry all of these:

| Field | Description |
|-------|-------------|
| `claim_key` | Stable identifier for this claim type |
| `value` | The actual value (null if unknown) |
| `state` | `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed` |
| `source_url` / `source_id` | Where this was fetched from |
| `retrieved_at` | ISO timestamp of retrieval |
| `reporting_period` | For financial data: the fiscal period |
| `content_hash` | Hash of the source content |
| `snapshot_path` | Path to saved immutable snapshot |
| `extraction_method` | How the value was extracted |
| `evidence_span` | Selector, char range, table cell, or PDF page |

**No evidence = no publication.**

---

## 🌐 Website Identity Gate

Website facts are published **only when** identity threshold passes. Valid signals:

1. Organisation number appears on the site (footer, imprint, privacy policy, "Om oss") — this alone is sufficient
2. OR at least **3 of**: exact legal name, address/municipality, phone, registered leader name, matching industry

**Never use fuzzy name similarity alone as final proof.**

When identity is ambiguous → **FAIL CLOSED** → return register-only data.

---

## 🕷️ Crawling Rules

- Respect `robots.txt` and declared rate limits
- Per-domain throttling and bounded concurrency
- Block private/internal IP ranges
- Limit to ~8–10 pages per company
- Target ~15 requests per company globally
- Priority pages: `/`, `/about`, `/om-oss`, `/contact`, `/kontakt`, `/ledelse`, `/careers`, `/karriere`, `/jobs`, `/news`, `/nyheter`
- Save immutable snapshots: requested URL, final URL, HTTP status, retrieval timestamp, content hash
- Static HTTP first; Playwright only if kit explicitly requires it and budget allows

---

## 🔍 Deterministic Extraction Order

```
JSON-LD / OpenGraph
        ↓
DOM attributes
        ↓
cleaned text (Trafilatura)
        ↓
CSS/DOM rules
        ↓
regex / structured parsers
```

**No LLM extraction at any stage.**

---

## 💰 Financial Data Rules

- Source: permitted official annual-accounts source **only**
- Never estimate or derive a missing figure
- If figure absent → mark `not_available`
- Every financial value **must** retain its reporting period
- Fabricated financials = **run invalidated**

---

## 🔁 Update Engine (Refresh)

Stable claim-key diff between previous and fresh profiles. Must detect:
- New facts
- Changed facts (address, name, status, description, etc.)
- New filings, new roles
- Status changes (e.g., active → bankrupt/dissolved)

A failed refresh **preserves the last supported value** and records the failure.  
No changes → no false change record.

---

## 📝 Deterministic Summary Format

Three parts, every sentence maps to a claim ID:
1. **What the company does** (from verified claims)
2. **What changed since the previous run**
3. **What remains unknown** (explicit list)

No marketing language. No unsupported claims. No LLM.

---

## 🖥️ Report Requirements (UX = 8 points)

Static HTML with:
- Search box
- Company profile page with sections
- Each claim showing source link + retrieval date
- State badges for unknowns
- Changes panel
- Mobile-friendly / responsive layout
- **No external runtime dependencies**

---

## 🧪 Minimum Test Coverage

| Test | Requirement |
|------|-------------|
| Identity | Similarly named different company must be **rejected** |
| Evidence | Value not literally in evidence → **removed** |
| Fail closed | Low identity confidence → **register-only** |
| No website | Must be a normal fast path (not an error) |
| Financials | Missing values → **never become fabricated numbers or misleading zeroes** |
| Updates — change | Address and status changes **detected** |
| Updates — stable | Unchanged data → **zero false changes** |
| Envelope | Every input org number → **exactly one terminal result** |
| Sampling | Same seed → **same company sets** |

**Critical:** Never claim a test passed unless the command was actually run.

---

## ⏱️ Request / Time Budget

- Global request budget: per `RULES.md` / kit
- Target: ~15 requests per company
- At ~85% of time budget: stop deep crawling, finalise remaining companies
- Every company **must** receive an envelope regardless
- Per-company timeout (suggested: 30–60s)
- Bounded concurrency (suggested start: 20–50 concurrent)

---

## 📋 Input Sampling Requirements

| Sample | Size | Seed |
|--------|------|------|
| Submission sample | 1,500+ | Reproducible |
| Daily-test-like | 100 | Seeded |
| Dev set (stratified) | Small | Varies |

Dev set must include: active, bankrupt/dissolved, sole proprietorships, dormant, large, and no-website companies.

Org number validation: **mod-11 checksum** — remove invalid and duplicate numbers.

---

## 📦 Submission Requirements

### `README.md` must contain:
- Setup instructions
- Python version
- Pinned dependencies
- Environment variables
- Permitted sources
- Architecture overview
- Identity policy
- Evidence policy
- No-LLM design statement
- Limitations
- One-command execution
- Expected official-run cost
- Example output

### `SUBMISSION.md` must contain:
- Agent name: **Signalpost**
- Repository URL placeholder
- Exact commit hash command
- One-command run
- Official source/API details
- Licences
- Expected cost per 100 companies / official run
- Smoke-test result
- `RULES.md` checklist
- Kit checklist
- **Explicit statement:** *"Signalpost uses no LLM/model API. All extraction and synthesis are deterministic."*

### Submission email to: `submit@builderr.ai`

---

## 🗓️ Build Timeline

| Day | Goal |
|-----|------|
| 1 (Oct 5–6) | Read kit. Build `run.py`, `batch.py`, `envelope.py` → 100 in → 100 out (all `not_available`) |
| 2–3 | `registry.py` + `accounts.py`. Smoke test on 100: >95% available on identity/accounts/leadership |
| 4–5 | `website.py` gate + `crawl.py`. Measure wrong-company rate on 50 companies. Target: zero |
| 6–7 | `extract.py`, hiring, activity, `summary.py` |
| 8 | `refresh.py` + idempotence tests (run twice, diff must be empty) |
| 9 | `report/` HTML, `LIMITATIONS.md`, `AGENT.md` |
| 10 | Scale test on 1,000 companies: check time, errors, request count. Tune concurrency |
| 11 | Clean-machine install test. Write `smoke_report.md` |
| 12 | Submit v1 by email. Keep up to 4 revisions for fixes |

**Submit v1 early (around day 8):** You get 4 revisions, and daily batches score only your active frozen version.

---

## 🌍 Permitted Sources

| Source | Use | Notes |
|--------|-----|-------|
| BRREG Bulk CSV | Identity anchor | NLOD 2.0; download before run |
| BRREG Entity API | Live identity, status, website | `data.brreg.no/enhetsregisteret/api/enheter/{org}` |
| BRREG Roles API | Board & management | `/roller` endpoint |
| BRREG Group API | Corporate relationships | `/konsernstruktur/{org}` |
| BRREG Subunits API | Registered workplaces | `/underenheter?overordnetEnhet={org}` |
| Regnskapsregisteret normalized | Latest accounts | `/regnskap/{org}` |
| Regnskapsregisteret years | Filing history | Rate-limited: 30 req/min (2.1s gap enforced) |
| Regnskapsregisteret PDF | Official annual report | Per year |
| Verified company website | After identity gate | Source class: `company_owned` |
| Brave Search API | Candidate discovery only (transient) | Keep transient; retain only fetched page evidence |
| Google Places API | Place, rating | Official API terms required |
| YouTube Data API | Channel, posts | Official API |
| Licensed news/search | Candidates + evidence | Declared connector + retained fetched evidence |
| Google News RSS | News mentions | RSS only; no scraping |

---

## 🚫 Forbidden Sources

| Source | Reason |
|--------|--------|
| LinkedIn (unofficial scrape) | Terms prohibit; experimental only, zero scoring |
| Meta / Instagram / X / TikTok (scrape) | Approved API access required |
| Glassdoor / Indeed (scrape) | Prohibited; no score from scraping |
| Google Custom Search JSON API | Closing 2027; no new customers |
| Google/Bing grounding for stored corpus | Not permitted for evidence retention |
| Private/internal IP ranges | Safe URL handling required |
| Robots.txt-blocked paths | Must respect |
| LLM / model APIs (our decision) | No NVIDIA, Gemini, OpenAI, Anthropic |

---

## ⚙️ Environment Variables

From confirmed `.env.example` + kit:

```env
# LLM — always disabled (our design decision)
LLM_ENABLED=false
NVIDIA_API_KEY=        # Never populate
NVIDIA_BASE_URL=
NVIDIA_MODEL=
GEMINI_API_KEY=        # Never populate
GEMINI_MODEL=

# Search discovery (quarantined until rights confirmed)
BRAVE_SEARCH_API_KEY=

# Runtime budgets (from kit)
MAX_REQUESTS=2000
MAX_REQUESTS_PER_COMPANY=15
MAX_RUNTIME_SECONDS=2700
MAX_CONCURRENCY=8

# Local state
CACHE_DIR=state/cache
DATABASE_PATH=state/signalpost.sqlite3
```

---

## 🔧 Python & Dependencies

- **Python version:** 3.12+ (tested on 3.13.7)
- **Package manager:** `pip` or `uv`
- **Install:** `pip install -e .[dev]` or `uv sync`
- All core dependencies pinned in `pyproject.toml`
- No LLM/model dependencies; `llm` extra is a placeholder only

**Key files added this session:**
- [`run.py`](file:///d:/Anti-gravity%27s%20SIgnalpost/run.py) — evaluator entry point (matches kit interface)
- [`src/signalpost/pipeline.py`](file:///d:/Anti-gravity%27s%20SIgnalpost/src/signalpost/pipeline.py) — per-company orchestrator
- [`src/signalpost/website.py`](file:///d:/Anti-gravity%27s%20SIgnalpost/src/signalpost/website.py) — identity gate + static crawler
- [`src/signalpost/summary.py`](file:///d:/Anti-gravity%27s%20SIgnalpost/src/signalpost/summary.py) — deterministic summary generator
- [`tests/test_pipeline.py`](file:///d:/Anti-gravity%27s%20SIgnalpost/tests/test_pipeline.py) — 15 gate tests (identity, evidence, refresh, envelope)

---

## 📌 Resolved Ambiguities (Phase 0 Complete)

| # | Conflict | Resolution |
|---|----------|------------|
| 1 | Terminal state names differ (prompt vs kit) | Kit internal states for `modules[]`; OUTPUT_CONTRACT availability for `claims[].availability` |
| 2 | CLI flags differ (prompt vs kit) | Build `run.py` matching kit's evaluator interface exactly |
| 3 | RULES.md says LLMs *can* be used; prompt says NO LLM | Honour no-LLM decision; it's a feature. Declare explicitly in SUBMISSION.md |
| 4 | Scorer v3 rubric (55/15/10/12/8) vs official rubric (50/30/12/8) | Build for official 50/30/12/8; use v3 proxy for local tracking only |
| 5 | `.env.example` has LLM placeholders | Set `LLM_ENABLED=false`; never populate API key fields |

**Open decisions for Phase 1:**
- [ ] Confirm `data/orgs.json` format (first few lines)
- [ ] Decide whether to extend kit in-place or import via `sys.path` (leaning: import via path, already in `pyproject.toml`)
- [ ] Confirm Brave Search API availability before enabling
- [ ] Set explicit per-company timeout (45s recommended)

---

## 🏷️ Session State Tracking

```
PHASE:           8 — Website Coverage Boost
CODE WRITTEN:    run.py, pipeline.py, website.py, summary.py,
                 test_pipeline.py, report/build_report.py,
                 tests/test_benchmark.py, SUBMISSION.md, ARCHITECTURE.md
TESTS RUN:       34/34 PASSED (python -m pytest tests/ -v)
ENVELOPES:       100/100 PASSED (daily-benchmark-001)
SAMPLES BUILT:   profiles-1500, daily-100, dev-60
LAST GATE:       Phase 7 PASSED — 100/100 companies, all checks true
NEXT ACTION:     1) Improve website identity gate for subsidiary pages
                 2) Add Brave Search candidate discovery (need API key)
                 3) Add Google News RSS connector
                 4) Re-run benchmark and score with score_competition_v3.py
BLOCKERS:        brreg-enheter.csv download in progress (~150 MB left)
                 Website coverage 0/100 gate-passed (88% have no registered URL)
KIT REUSE:       batch.py✓ official.py✓ identity.py✓ refresh.py✓ evidence.py✓ sampling.py✓
SCORING TARGET:  65 qualify / 70 goal / 80 stretch
LEADERBOARD:     Top score 45.59 (Karthik) as of Oct 1 — 0 qualified entries
TEST BREAKDOWN:  benchmark(12) + official(3) + phase1(2) + pipeline(15) + sampling(2) = 34
BENCHMARK:       411 req / 2.3 MB / 80s / $0.00 / 0 LLM / p50=1239ms p95=2754ms
COVERAGE:        registry 100% | financials 100% | roles 99% | website 0% (gate-pass)
```

---

## 🔗 Key References

- **Hackathon platform:** Unstop (deadline 17 Oct 2026); Builderr shows 21 Oct; revisions close 18 Oct 2026
- **Submit email:** submit@builderr.ai
- **Current leaderboard top:** 60.80
- **Target score:** 65 (qualify), 70 (goal), 80 (stretch)
- **Baseline without recall:** ~47 points

---

*This README is the living session document for Signalpost. Update the "Session State Tracking" section and phase checklists after every phase gate.*
