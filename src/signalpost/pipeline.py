"""Signalpost pipeline — per-company orchestrator.

Fetches register + accounts + website in sequence. Never uses an LLM.
Returns a profile dict matching the terminal envelope contract.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .logging import configure_logging  # noqa: F401 (re-exported)
from .official import OfficialClient, SQLiteResponseCache, build_register_envelope, utc_now
from .summary import build_summary

import os
import logging

log = logging.getLogger("signalpost.pipeline")

CACHE_DIR = Path(os.environ.get("CACHE_DIR", "state/cache"))
DEFAULT_MODULES = {"registry", "roles", "group", "locations", "financials", "financial_history"}


def _make_client() -> OfficialClient:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = SQLiteResponseCache(CACHE_DIR / "http_cache.sqlite3")
    return OfficialClient(cache, timeout=20.0)


def run_company(
    organisation_number: str,
    *,
    bulk_row: dict[str, Any] | None = None,
    modules: set[str] | None = None,
    run_id: str = "local",
    timeout: float = 45.0,
) -> dict[str, Any]:
    """Process a single company. Always returns a profile dict (never raises)."""
    started = time.monotonic()
    started_at = utc_now()
    modules = modules or DEFAULT_MODULES
    evidence: dict[str, Any] = {}
    errors: list[dict] = []

    try:
        client = _make_client()

        # Seed from bulk snapshot if available
        bulk_data = bulk_row or {}

        # ── Register layer (live API) ────────────────────────────────────────
        fetch_modules = modules - {"website"}
        responses = client.fetch_modules(organisation_number, fetch_modules)

        # Build evidence records from responses
        from .official import (
            normalize_entity, normalize_financials,
            BRREG_ENTITY, BRREG_ROLES, BRREG_GROUP, BRREG_SUBUNITS,
            BRREG_ACCOUNTS, BRREG_ACCOUNT_YEARS,
        )
        from norway_company_agent.official import (
            normalize_roles, normalize_locations, normalize_financial_history,
            _classified,
        )
        from norway_company_agent.evidence import evidence as kit_evidence

        def _ev(module: str, source_type: str) -> dict[str, Any] | None:
            resp = responses.get(module)
            if resp is None:
                return None
            if resp.status == 200:
                body_json = None
                try:
                    import json
                    body_json = json.loads(resp.body.decode("utf-8"))
                except Exception:
                    pass
                if module == "registry":
                    value = normalize_entity(body_json) if body_json else None
                elif module == "financials":
                    value = {"records": normalize_financials(body_json)} if body_json else None
                elif module == "financial_history":
                    value = normalize_financial_history(body_json, organisation_number) if body_json else None
                elif module == "roles":
                    value = normalize_roles(body_json) if body_json else None
                elif module == "locations":
                    value = normalize_locations(body_json) if body_json else None
                else:
                    value = body_json
                return kit_evidence(module, "available", source_type, resp.url,
                                    value=value, content_sha256=resp.content_sha256,
                                    retrieved_at=resp.retrieved_at)
            elif resp.status in {404, 410}:
                return kit_evidence(module, "not_found", source_type, resp.url,
                                    content_sha256=resp.content_sha256, retrieved_at=resp.retrieved_at)
            else:
                return kit_evidence(module, "source_error", source_type, resp.url,
                                    note=resp.error or f"HTTP {resp.status}",
                                    content_sha256=resp.content_sha256, retrieved_at=resp.retrieved_at)

        module_source_map = {
            "registry": (BRREG_ENTITY.format(org=organisation_number), "official_registry_live"),
            "financials": (BRREG_ACCOUNTS.format(org=organisation_number), "official_annual_accounts"),
            "financial_history": (BRREG_ACCOUNT_YEARS.format(org=organisation_number), "official_annual_account_copies"),
            "roles": (BRREG_ROLES.format(org=organisation_number), "official_roles"),
            "group": (BRREG_GROUP.format(org=organisation_number), "official_group_structure"),
            "locations": (BRREG_SUBUNITS.format(org=organisation_number), "official_subunits"),
        }
        for module, (_url, source_type) in module_source_map.items():
            if module not in fetch_modules:
                continue
            ev = _ev(module, source_type)
            if ev is not None:
                evidence[module] = ev
                # The kit scorer reads registry evidence as 'registry_live' — alias it
                if module == "registry":
                    evidence["registry_live"] = ev

        # ── Website layer — multi-candidate discovery ────────────────────────
        if "website" in modules:
            registered_url = bulk_data.get("website") or ""
            reg_ev_tmp = evidence.get("registry") or {}
            if not registered_url and isinstance(reg_ev_tmp.get("value"), dict):
                registered_url = reg_ev_tmp["value"].get("website") or ""

            name_for_disc = bulk_data.get("name") or ""
            muni_for_disc = bulk_data.get("municipality") or ""

            from .discovery import discover_candidates
            from .website import fetch_and_gate_website, _utc_now, _sha256

            registry_profile = {
                "organisation_number": organisation_number,
                "name": name_for_disc,
                "evidence": evidence,
            }
            candidates = discover_candidates(
                organisation_number,
                name_for_disc,
                registered_url=registered_url,
                municipality=muni_for_disc,
                enable_news_rss=True,
            )

            # Normalise registered URL host for BRREG-authority comparison
            def _host(u: str) -> str:
                return u.strip().lstrip("https://").lstrip("http://").rstrip("/").lower()

            _reg_host = _host(registered_url) if registered_url else ""

            best_ev: dict | None = None
            for candidate_url in candidates:
                # BRREG-registered URL is authoritative — the company declared it to the state
                cand_host = _host(candidate_url)
                is_brreg_url = bool(_reg_host and (_reg_host in cand_host or cand_host in _reg_host))
                website_ev, website_metrics = fetch_and_gate_website(
                    candidate_url, registry_profile,
                    brreg_registered=is_brreg_url,
                )
                client.request_count += website_metrics.get("requests", 0)
                client.bytes_received += website_metrics.get("bytes", 0)
                client.latencies_ms.extend(website_metrics.get("latencies_ms", []))
                if website_ev.get("status") == "available":
                    best_ev = website_ev
                    break
                if best_ev is None or website_ev.get("status") not in ("not_available",):
                    best_ev = website_ev

            if best_ev is None:
                best_ev = {
                    "status": "not_available",
                    "source_url": registered_url or "",
                    "source_class": "company_owned",
                    "note": "no candidates discovered",
                    "retrieved_at": _utc_now(),
                    "content_sha256": _sha256(b""),
                }
            evidence["website"] = best_ev

        # ── Accounting obligation (deterministic) ────────────────────────────
        from norway_company_agent.official import accounting_obligation_assessment
        reg_value = (evidence.get("registry") or {}).get("value") or {}
        fake_profile_for_obligation = {
            "legal_form": bulk_data.get("legal_form") or reg_value.get("legal_form"),
            "latest_submitted_accounts": bulk_data.get("latest_submitted_accounts") or reg_value.get("latest_submitted_accounts"),
        }
        evidence["accounting_obligation"] = accounting_obligation_assessment(fake_profile_for_obligation)

        elapsed_ms = int((time.monotonic() - started) * 1000)

        # ── Summary ──────────────────────────────────────────────────────────
        name = bulk_data.get("name") or reg_value.get("name")
        summary = build_summary(organisation_number, name, evidence, bulk_data)

        profile: dict[str, Any] = {
            "organisation_number": organisation_number,
            "name": name,
            "legal_form": bulk_data.get("legal_form") or reg_value.get("legal_form"),
            "municipality": bulk_data.get("municipality") or reg_value.get("municipality"),
            "industry_code": bulk_data.get("industry_code") or reg_value.get("industry_code"),
            "industry_label": bulk_data.get("industry_label") or reg_value.get("industry_label"),
            "website": bulk_data.get("website") or reg_value.get("website"),
            "latest_submitted_accounts": bulk_data.get("latest_submitted_accounts") or reg_value.get("latest_submitted_accounts"),
            "evidence": evidence,
            "summary": summary,
            "run_metrics": {
                "requests": client.request_count,
                "bytes": client.bytes_received,
                "latencies_ms": client.latencies_ms,
                "elapsed_ms": elapsed_ms,
            },
            "_run_id": run_id,
            "_started_at": started_at,
        }
        client.cache.close()
        return profile

    except Exception as exc:
        log.error(f"Pipeline error for {organisation_number}: {exc}", exc_info=True,
                  extra={"event": "pipeline_error", "organisation_number": organisation_number})
        return {
            "organisation_number": organisation_number,
            "name": bulk_row.get("name") if bulk_row else None,
            "evidence": evidence,
            "summary": None,
            "run_metrics": {"requests": 0, "bytes": 0, "latencies_ms": [], "elapsed_ms": int((time.monotonic() - started) * 1000)},
            "_error": str(exc),
            "_run_id": run_id,
            "_started_at": started_at,
        }
