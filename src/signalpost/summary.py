"""Signalpost deterministic summary generator.

Produces a 2–4 sentence plain-text summary from confirmed evidence only.
No LLM. Every sentence maps to a specific evidence field.

Format:
  1. What the company does (name + industry + municipality)
  2. Financial snapshot (revenue/result + year)  [if available]
  3. What changed since last run                [if changes exist]
  4. What remains unknown                       [unknowns listed explicitly]
"""
from __future__ import annotations

from typing import Any


def _get(ev: dict, *path: str) -> Any:
    """Safe deep-get from a nested dict."""
    val = ev
    for key in path:
        if not isinstance(val, dict):
            return None
        val = val.get(key)
    return val


def build_summary(
    organisation_number: str,
    name: str | None,
    evidence: dict[str, Any],
    bulk_row: dict[str, Any] | None = None,
    changes: list[dict] | None = None,
) -> str | None:
    """Return a 2–4 sentence deterministic summary or None if insufficient evidence."""
    parts: list[str] = []
    unknowns: list[str] = []

    bulk = bulk_row or {}
    reg_ev = evidence.get("registry") or evidence.get("registry_live") or {}
    reg_val = _get(reg_ev, "value") or {}

    # Company name
    display_name = name or reg_val.get("name") or f"Organisation {organisation_number}"

    # Industry
    industry = (
        bulk.get("industry_label")
        or reg_val.get("industry_label")
        or _get(reg_val, "industry", "beskrivelse")
    )
    municipality = bulk.get("municipality") or reg_val.get("municipality")
    legal_form = bulk.get("legal_form") or reg_val.get("legal_form")

    # Sentence 1: identity + activity
    s1_parts = [display_name]
    if legal_form:
        s1_parts.append(f"({legal_form})")
    if industry:
        s1_parts.append(f"operates in {industry.lower()}")
    if municipality:
        s1_parts.append(f"and is registered in {municipality.capitalize()}")
    parts.append(" ".join(s1_parts) + ".")

    # Sentence 2: financials
    fin_ev = evidence.get("financials") or {}
    fin_records = _get(fin_ev, "value", "records") or []
    if fin_records:
        latest = fin_records[0]
        period = latest.get("period") or {}
        year = period.get("tilDato", "")[:4] if isinstance(period, dict) else str(period)[:4]
        revenue = latest.get("revenue")
        result = latest.get("annual_result")
        fin_parts = []
        if year:
            fin_parts.append(f"In {year}")
        if revenue is not None:
            fin_parts.append(f"revenue was NOK {revenue:,}")
        if result is not None:
            sign = "profit" if result >= 0 else "loss"
            fin_parts.append(f"with a net {sign} of NOK {abs(result):,}")
        if fin_parts:
            parts.append(", ".join(fin_parts) + ".")
    elif fin_ev.get("status") == "not_found":
        unknowns.append("annual accounts")
    else:
        unknowns.append("financial data")

    # Sentence 3: roles
    roles_ev = evidence.get("roles") or {}
    roles_list = _get(roles_ev, "value", "roles") or []
    active_roles = [r for r in roles_list if not r.get("inactive")]
    if active_roles:
        count = len(active_roles)
        parts.append(f"{count} active role{'s' if count != 1 else ''} are registered.")
    else:
        unknowns.append("leadership roles")

    # Sentence 4: website
    website_ev = evidence.get("website") or {}
    if website_ev.get("status") == "available":
        final_url = website_ev.get("final_url") or website_ev.get("source_url") or ""
        parts.append(f"An official website was verified at {final_url}.")
    elif website_ev.get("status") == "ambiguous":
        unknowns.append("verified website (identity gate failed)")
    elif website_ev.get("status") == "not_available":
        unknowns.append("website")
    elif website_ev.get("status") == "blocked":
        unknowns.append("website (blocked)")

    # Changes sentence
    if changes:
        change_labels = []
        for ch in changes[:3]:
            field = ch.get("field", "")
            change_labels.append(field)
        parts.append(f"Changes detected since last run: {', '.join(change_labels)}.")

    # Unknowns sentence
    if unknowns:
        parts.append(f"Not available: {', '.join(unknowns)}.")

    if not parts:
        return None

    return " ".join(parts)
