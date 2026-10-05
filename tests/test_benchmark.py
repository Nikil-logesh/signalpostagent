"""Phase 7 gate test — validates 100-company daily benchmark output.

Run after:
  python run.py ... --expected-count 100 --output out/daily-envelopes.jsonl
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ENVELOPES_PATH = Path("out/phase8-envelopes.jsonl")
REPORT_PATH = Path("out/phase8-report.json")

TERMINAL_STATES = {
    "complete", "not_applicable", "not_found",
    "blocked_policy", "blocked_robots", "source_error",
    "budget_exhausted", "submission_error",
}


def _load_envelopes() -> list[dict]:
    if not ENVELOPES_PATH.exists():
        pytest.skip(f"{ENVELOPES_PATH} not found — run the benchmark first")
    return [json.loads(l) for l in ENVELOPES_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]


def _load_report() -> dict:
    if not REPORT_PATH.exists():
        pytest.skip(f"{REPORT_PATH} not found — run the benchmark first")
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


# ── Gate 1: count and uniqueness ─────────────────────────────────────────────

def test_exactly_100_envelopes() -> None:
    envelopes = _load_envelopes()
    assert len(envelopes) == 100, f"Expected 100 envelopes, got {len(envelopes)}"


def test_no_duplicate_org_numbers() -> None:
    envelopes = _load_envelopes()
    orgs = [e["organisation_number"] for e in envelopes]
    assert len(orgs) == len(set(orgs)), "Duplicate organisation numbers in output"


# ── Gate 2: all states terminal ──────────────────────────────────────────────

def test_all_entity_states_terminal() -> None:
    envelopes = _load_envelopes()
    non_terminal = [
        e["organisation_number"] for e in envelopes
        if e.get("state") not in TERMINAL_STATES
    ]
    assert not non_terminal, f"Non-terminal entity states: {non_terminal}"


def test_all_module_states_terminal() -> None:
    envelopes = _load_envelopes()
    bad = []
    for e in envelopes:
        for module, state_obj in e.get("modules", {}).items():
            if state_obj.get("state") not in TERMINAL_STATES:
                bad.append(f"{e['organisation_number']}.{module}={state_obj.get('state')}")
    assert not bad, f"Non-terminal module states: {bad[:10]}"


# ── Gate 3: zero silent drops ────────────────────────────────────────────────

def test_validation_passed_in_report() -> None:
    report = _load_report()
    val = report.get("validation", {})
    assert val.get("passed") is True, f"Validation failed: {val}"


# ── Gate 4: no LLM ───────────────────────────────────────────────────────────

def test_zero_llm_requests() -> None:
    report = _load_report()
    llm_req = report.get("operations", {}).get("llm_requests", 0)
    assert llm_req == 0, f"LLM requests should be 0, got {llm_req}"


def test_zero_third_party_cost() -> None:
    report = _load_report()
    cost = report.get("operations", {}).get("third_party_cost_usd", 0)
    assert cost == 0.0, f"Third-party cost should be $0, got ${cost}"


# ── Gate 5: register coverage ────────────────────────────────────────────────

def test_register_coverage_at_least_90_percent() -> None:
    """At least 90% of companies should have a registry record."""
    envelopes = _load_envelopes()
    available = sum(
        1 for e in envelopes
        if (e.get("profile", {}).get("evidence") or {}).get("registry", {}).get("status") == "available"
        or (e.get("profile", {}).get("evidence") or {}).get("registry_live", {}).get("status") == "available"
    )
    pct = available / len(envelopes)
    assert pct >= 0.90, f"Registry coverage {pct:.1%} < 90% ({available}/100)"


def test_financials_coverage_at_least_80_percent() -> None:
    """At least 80% of companies should have financial records (all have 2025 accounts in bulk)."""
    envelopes = _load_envelopes()
    available = sum(
        1 for e in envelopes
        if (e.get("profile", {}).get("evidence") or {}).get("financials", {}).get("status") == "available"
    )
    pct = available / len(envelopes)
    assert pct >= 0.80, f"Financials coverage {pct:.1%} < 80% ({available}/100)"


# ── Gate 6: identity precision ───────────────────────────────────────────────

def test_no_wrong_company_website_published() -> None:
    """No website should be 'available' with an identity score below 0.9."""
    envelopes = _load_envelopes()
    wrong = []
    for e in envelopes:
        web_ev = (e.get("profile", {}).get("evidence") or {}).get("website") or {}
        if web_ev.get("status") == "available":
            score = (web_ev.get("value") or {}).get("identity_assessment", {}).get("score", 1.0)
            if score < 0.9:
                wrong.append(f"{e['organisation_number']} score={score}")
    assert not wrong, f"Wrong-company websites published: {wrong}"


def test_all_available_claims_have_evidence() -> None:
    """Every 'available' website claim has content_sha256 set."""
    envelopes = _load_envelopes()
    missing = []
    for e in envelopes:
        web_ev = (e.get("profile", {}).get("evidence") or {}).get("website") or {}
        if web_ev.get("status") == "available":
            if not web_ev.get("content_sha256"):
                missing.append(e["organisation_number"])
    assert not missing, f"Available website claims missing content_sha256: {missing}"


# ── Gate 7: request budget ───────────────────────────────────────────────────

def test_total_requests_within_budget() -> None:
    report = _load_report()
    total = report.get("operations", {}).get("requests", 0)
    assert total <= 2000, f"Total requests {total} exceeds MAX_REQUESTS=2000"
