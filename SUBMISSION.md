# SIGNALPOST — Submission Document

**Hackathon:** Builderr — Norwegian Company Research Agent  
**Deadline:** 17 Oct 2026 · Revisions close: 18 Oct 2026  
**Email:** submit@builderr.ai

---

## One Reproducible Run Command

```bash
# 1. Clone and set up
git clone <repo-url>
cd signalpost
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -e .[dev]

# 2. Download the Brreg entity snapshot (done once; ~100 MB)
python -c "
import urllib.request, time
url = 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv'
req = urllib.request.Request(url, headers={'User-Agent':'signalpost/0.1'})
with urllib.request.urlopen(req, timeout=300) as r:
    open('brreg-enheter.csv','wb').write(r.read())
print('Downloaded brreg-enheter.csv')
"

# 3. Run the agent (replace placeholders with Builderr-supplied values)
python run.py \
  --organisations <builderr-batch.jsonl> \
  --bulk brreg-enheter.csv \
  --profiles-output out/profiles.jsonl \
  --output out/envelopes.jsonl \
  --report out/run-report.json \
  --run-id <builderr-run-id> \
  --expected-count <N> \
  --workers 8 \
  --modules registry,financials,roles,locations,website

# 4. Build the HTML report (optional, for UX review)
python report/build_report.py \
  --profiles out/profiles.jsonl \
  --output out/report/index.html
```

---

## Models / APIs Used

| Component | Status | Notes |
|-----------|--------|-------|
| Any LLM / model API | ❌ **NOT USED** | `LLM_ENABLED=false` always |
| NVIDIA / Gemini / OpenAI | ❌ **NOT USED** | Keys are never populated |
| Brave Search API | ❌ NOT ACTIVE | Quarantined; `BRAVE_SEARCH_API_KEY=` empty |
| Google Places API | ❌ NOT USED | Not implemented in this version |
| YouTube Data API | ❌ NOT USED | Not implemented in this version |

**All extraction is deterministic.** The agent uses only official Norwegian public-sector sources.

---

## Sources Used

| Source | Licence | Use |
|--------|---------|-----|
| Brønnøysundregistrene — Enhetsregisteret (bulk CSV) | NLOD 2.0 | Identity anchor, company status, legal form |
| Brønnøysundregistrene — Entity API | NLOD 2.0 | Live registry data, employees, address, website |
| Brønnøysundregistrene — Roles API | NLOD 2.0 | Board members, management |
| Brønnøysundregistrene — Group structure API | NLOD 2.0 | Corporate group relationships |
| Brønnøysundregistrene — Subunits API | NLOD 2.0 | Registered workplaces |
| Brønnøysundregistrene — Regnskapsregisteret | NLOD 2.0 | Annual accounts, revenue, result, equity |
| Company websites (after identity gate) | N/A — publicly crawled | Verified company-owned pages only |

**Rights assumption:** All Brreg APIs are open public data under NLOD 2.0.  
Company websites are crawled with `robots.txt` respect and a declared `User-Agent: signalpost/0.1`.  
No proprietary, licensed, or scraped data from third-party platforms.

---

## Third-Party Cost

**Total third-party API cost: $0.00**

- No paid model API
- No paid search API
- All sources are free public APIs

---

## Evidence and Provenance Policy

Every published claim has:
- `source_url` — exact BRREG API endpoint or company website URL
- `source_class` — `official_registry_live`, `official_annual_accounts`, `official_roles`, `official_group_structure`, `official_subunits`, `company_owned`
- `retrieved_at` — ISO 8601 UTC timestamp
- `content_sha256` — SHA-256 of the raw HTTP response body
- `claim_span` — excerpt of source text supporting the claim

**Identity gate:** A company website is only published if the identity score ≥ 0.9 (org-number in page = 1.0; all name tokens = 0.95). Ambiguous matches are published as `status: ambiguous` — never as `available`.

**Fabrication policy:** If a fact cannot be deterministically supported, it is published as `not_available`, `ambiguous`, or `not_applicable` — never fabricated or defaulted to zero.

---

## Refresh / Idempotence Policy

- The same source snapshot produces identical output on repeated runs (idempotent)
- SQLite response cache (ETag / If-Modified-Since) prevents duplicate requests
- `kit/src/norway_company_agent/refresh.py::diff_profile()` tracks all changes across tracked fields
- Changes are published in the `changes[]` array with `old_value`, `new_value`, `retrieved_at`, `source_url`
- No change is fabricated from identical data (zero-false-change guarantee — tested)

---

## Safe URL Handling

- Private/loopback/link-local IPs blocked before any network request
- Only `http://` and `https://` schemes accepted
- `robots.txt` checked per host (cached) before crawling
- 10-second connection timeout; 512 KB max response body per page
- `User-Agent: signalpost/0.1 (+https://github.com/Nikil-logesh/HWR)` declared on all requests

---

## Server-Side Secrets

No server-side secrets are required to reproduce this run.  
The only optional secrets are:
- `BRAVE_SEARCH_API_KEY` — leave empty (not used in this version)
- `NVIDIA_API_KEY` / `GEMINI_API_KEY` — leave empty (`LLM_ENABLED=false`)

---

## Pinned Dependencies

See `pyproject.toml`:

```toml
requires-python = ">=3.12"
dependencies = [
  "beautifulsoup4>=4.14,<5",
  "extruct>=0.18,<1",
  "lxml>=6,<7",
  "pydantic>=2.12,<3",
  "pypdf>=6,<7",
  "tldextract>=5.3,<6",
  "trafilatura>=2.0,<3",
]
```

Standard library only for HTTP (`urllib.request`), JSON, CSV, SQLite, threading.  
No web framework. No async runtime. No hidden system packages.

---

## Result Envelope Guarantee

```
✅ Exactly one terminal envelope per input company
✅ All entity states are terminal (complete / not_found / blocked_* / source_error / submission_error)
✅ No silent drops (emitted == expected)
✅ All organisation numbers unique in output
✅ Zero LLM requests
✅ Third-party cost = $0.00
```

---

## Known Limitations (this version)

| Gap | Impact | Planned fix |
|-----|--------|-------------|
| No job postings | 7 pts external recall | Add Finn.no or Nav.no public job feeds |
| No Google Places rating/reviews | 8 pts external recall | Add Google Places API (requires key) |
| No LinkedIn/social | 10 pts external recall | Blocked by terms; official API path only |
| No news mentions | 7 pts buzz | Add Google News RSS + structured extract |
| Website coverage limited to registered URL | Some recall loss | Add Brave Search candidate discovery |

---

## Submission Artefacts Checklist

- [x] One reproducible run command (this document)
- [x] Declared models: **none**
- [x] Declared APIs: Brreg (free, NLOD 2.0)
- [x] Declared third-party cost: **$0.00**
- [x] Source-rights documentation: NLOD 2.0 (open)
- [x] Pinned dependencies: `pyproject.toml`
- [x] Smoke-test result: `out/smoke-report.json` (5 companies, all checks pass)
- [x] Idempotence: SQLite ETag cache + `diff_profile()` zero-false-change test
- [ ] 100-company batch result (Phase 7 — in progress)
- [ ] Local score from `kit/scripts/score_competition_v3.py`
