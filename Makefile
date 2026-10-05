.PHONY: test lint run smoke samples report help

PYTHON ?= python
INPUT  ?= smoke-5.jsonl
BULK   ?= smoke-bulk.csv
OUT    ?= out

# ── Development ──────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check src tests

# ── Smoke test (5 companies, no LLM) ────────────────────────────────────────
smoke:
	$(PYTHON) run.py \
	  --organisations $(INPUT) \
	  --bulk $(BULK) \
	  --profiles-output $(OUT)/smoke-profiles.jsonl \
	  --output $(OUT)/smoke-envelopes.jsonl \
	  --report $(OUT)/smoke-report.json \
	  --run-id smoke-local \
	  --expected-count 5 \
	  --workers 4 \
	  --modules registry,financials,roles,locations,website

# ── Full evaluator-style batch run (set INPUT/BULK/N as needed) ──────────────
run:
	$(PYTHON) run.py \
	  --organisations $(INPUT) \
	  --bulk $(BULK) \
	  --profiles-output $(OUT)/profiles.jsonl \
	  --output $(OUT)/envelopes.jsonl \
	  --report $(OUT)/run-report.json \
	  --run-id local-$(shell date +%Y%m%d) \
	  --expected-count $(shell python -c "import json,pathlib; lines=[l for l in pathlib.Path('$(INPUT)').read_text().splitlines() if l.strip()]; print(len(lines))" 2>/dev/null || echo 100) \
	  --workers 8

# ── Build samples from data/orgs.json ───────────────────────────────────────
samples:
	$(PYTHON) -c "
import sys; sys.path.insert(0,'src')
from signalpost.sampling import build_samples
r = build_samples('data/orgs.json', 'data/samples',
                  profiles_count=1500, daily_count=100, dev_count=60,
                  kit_metadata_path='kit/data/universe-metadata.json')
import json; print(json.dumps(r['samples'], indent=2))
"

# ── HTML report ──────────────────────────────────────────────────────────────
report:
	$(PYTHON) report/build_report.py \
	  --profiles $(OUT)/profiles.jsonl \
	  --output $(OUT)/report/index.html \
	  --run-id $$(python -c "import json; r=json.load(open('$(OUT)/run-report.json')); print(r['run_id'])" 2>/dev/null || echo local)

help:
	@echo "make test     — Run unit tests"
	@echo "make lint     — Run ruff linter"
	@echo "make smoke    — Run 5-company smoke test"
	@echo "make run      — Run full batch (set INPUT=, BULK=, OUT=)"
	@echo "make samples  — Build stratified samples from data/orgs.json"
	@echo "make report   — Build HTML report from out/profiles.jsonl"
