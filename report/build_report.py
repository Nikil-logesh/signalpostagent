#!/usr/bin/env python3
"""Signalpost static HTML report builder.

Reads out/profiles.jsonl and produces a self-contained HTML report
with no external runtime dependencies.

Usage:
    python report/build_report.py \
        --profiles out/profiles.jsonl \
        --output out/report/index.html
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── helpers ────────────────────────────────────────────────────────────────

def _get(d: Any, *path: str, default: Any = None) -> Any:
    val = d
    for key in path:
        if not isinstance(val, dict):
            return default
        val = val.get(key)
    return val if val is not None else default


def _fmt_nok(value: Any) -> str:
    if value is None:
        return "—"
    try:
        n = int(float(value))
        return f"NOK {n:,}"
    except (TypeError, ValueError):
        return str(value)


def _badge(state: str) -> str:
    colour = {
        "available": "#22c55e",
        "not_available": "#94a3b8",
        "blocked": "#f97316",
        "ambiguous": "#eab308",
        "failed": "#ef4444",
        "not_applicable": "#8b5cf6",
        "source_error": "#f43f5e",
        "not_found": "#64748b",
    }.get(state, "#64748b")
    label = state.replace("_", " ")
    return f'<span class="badge" style="background:{colour}">{html.escape(label)}</span>'


def _esc(value: Any) -> str:
    return html.escape(str(value or "—"))


# ── per-company card HTML ───────────────────────────────────────────────────

def _render_profile(profile: dict) -> str:
    org = profile.get("organisation_number", "")
    name = profile.get("name") or f"Organisation {org}"
    legal_form = profile.get("legal_form") or ""
    municipality = profile.get("municipality") or ""
    industry = profile.get("industry_label") or ""
    summary = profile.get("summary") or ""
    latest_accounts = profile.get("latest_submitted_accounts") or "—"
    ev = profile.get("evidence", {})

    # Registry state
    reg_ev = ev.get("registry_live") or ev.get("registry") or {}
    reg_status = reg_ev.get("status", "not_fetched")
    reg_val = _get(reg_ev, "value") or {}

    # Financial records
    fin_ev = ev.get("financials") or {}
    fin_status = fin_ev.get("status", "not_fetched")
    fin_records = _get(fin_ev, "value", "records") or []

    # Roles
    roles_ev = ev.get("roles") or {}
    roles_status = roles_ev.get("status", "not_fetched")
    roles_list = _get(roles_ev, "value", "roles") or []
    active_roles = [r for r in roles_list if not r.get("inactive")]

    # Locations
    loc_ev = ev.get("locations") or {}
    loc_status = loc_ev.get("status", "not_fetched")
    locations = _get(loc_ev, "value", "locations") or []

    # Website
    web_ev = ev.get("website") or {}
    web_status = web_ev.get("status", "not_fetched")
    web_url = web_ev.get("final_url") or web_ev.get("source_url") or profile.get("website") or ""
    web_id = _get(web_ev, "value", "identity_assessment") or {}
    web_score = web_id.get("score")

    # Accounting obligation
    aob_ev = ev.get("accounting_obligation") or {}
    aob_val = _get(aob_ev, "value") or {}
    aob_class = aob_val.get("classification", "")

    # Build financials table rows
    fin_rows = ""
    for rec in fin_records[:3]:
        period_raw = rec.get("period") or {}
        year = period_raw.get("tilDato", "")[:4] if isinstance(period_raw, dict) else str(period_raw)[:4]
        fin_rows += f"""
        <tr>
            <td>{html.escape(year)}</td>
            <td>{_fmt_nok(rec.get("revenue"))}</td>
            <td>{_fmt_nok(rec.get("operating_result"))}</td>
            <td>{_fmt_nok(rec.get("annual_result"))}</td>
            <td>{_fmt_nok(rec.get("assets"))}</td>
            <td>{_fmt_nok(rec.get("equity"))}</td>
        </tr>"""

    # Build roles list
    roles_html = ""
    for r in active_roles[:10]:
        roles_html += f"""
        <div class="role-item">
            <strong>{_esc(r.get("name"))}</strong>
            <span class="role-label">{_esc(r.get("role") or r.get("role_code"))}</span>
        </div>"""

    # Build locations list
    loc_html = ""
    for loc in locations[:5]:
        addr = loc.get("address") or {}
        city = addr.get("poststed") if isinstance(addr, dict) else ""
        loc_html += f"""
        <div class="loc-item">
            <strong>{_esc(loc.get("name"))}</strong>
            {f"· {html.escape(city)}" if city else ""}
            {f'<span class="badge-sm">Employees: {loc.get("employees")}</span>' if loc.get("employees") is not None else ""}
        </div>"""

    # Website identity score bar
    if web_score is not None:
        bar_colour = "#22c55e" if web_score >= 0.9 else "#eab308" if web_score >= 0.7 else "#ef4444"
        score_bar = f"""
        <div class="score-bar-wrap">
            <div class="score-bar" style="width:{int(web_score*100)}%;background:{bar_colour}"></div>
            <span class="score-label">{web_score:.2f}</span>
        </div>"""
    else:
        score_bar = ""

    source_url = reg_ev.get("source_url", "")
    retrieved = reg_ev.get("retrieved_at", "")[:10]

    return f"""
<article class="company-card" id="c{html.escape(org)}"
         data-name="{html.escape(name.lower())}"
         data-org="{html.escape(org)}"
         data-muni="{html.escape(municipality.lower())}">

  <header class="card-header">
    <div>
      <h2 class="company-name">{html.escape(name)}</h2>
      <div class="company-meta">
        <span class="org-number">Org. {html.escape(org)}</span>
        {"· " + html.escape(legal_form) if legal_form else ""}
        {"· " + html.escape(municipality) if municipality else ""}
        {"· " + html.escape(industry) if industry else ""}
      </div>
    </div>
    <div class="card-badges">
      {_badge(reg_status)}
      {f'<a href="{html.escape(web_url)}" class="web-link" target="_blank" rel="noopener">🌐 Website</a>' if web_url and web_status == "available" else ""}
    </div>
  </header>

  {f'<p class="summary-text">"{html.escape(summary)}"</p>' if summary else ""}

  <div class="sections">

    <!-- Identity -->
    <section class="section">
      <h3>🪪 Legal Identity</h3>
      <div class="kv-grid">
        <span class="kv-key">Org number</span><span class="kv-val">{html.escape(org)}</span>
        <span class="kv-key">Legal name</span><span class="kv-val">{_esc(name)}</span>
        <span class="kv-key">Legal form</span><span class="kv-val">{_esc(legal_form)}</span>
        <span class="kv-key">Municipality</span><span class="kv-val">{_esc(municipality)}</span>
        <span class="kv-key">Industry</span><span class="kv-val">{_esc(industry)}</span>
        <span class="kv-key">Status</span><span class="kv-val">{_badge(reg_status)}</span>
        <span class="kv-key">Accounts obligation</span><span class="kv-val">{_esc(aob_class)}</span>
        <span class="kv-key">Latest accounts year</span><span class="kv-val">{_esc(latest_accounts)}</span>
        <span class="kv-key">Source</span><span class="kv-val">
          {f'<a href="{html.escape(source_url)}" target="_blank" rel="noopener">BRREG</a>' if source_url else "—"}
          {f" · {html.escape(retrieved)}" if retrieved else ""}
        </span>
      </div>
    </section>

    <!-- Financials -->
    <section class="section">
      <h3>💰 Annual Accounts {_badge(fin_status)}</h3>
      {"<p class='empty-note'>No financial data available.</p>" if not fin_rows else f"""
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Year</th><th>Revenue</th><th>Op. Result</th>
                <th>Net Result</th><th>Assets</th><th>Equity</th></tr>
          </thead>
          <tbody>{fin_rows}</tbody>
        </table>
      </div>"""}
    </section>

    <!-- Leadership -->
    <section class="section">
      <h3>👤 Leadership {_badge(roles_status)}</h3>
      {roles_html if roles_html else "<p class='empty-note'>No active roles found.</p>"}
    </section>

    <!-- Locations -->
    <section class="section">
      <h3>📍 Registered Workplaces {_badge(loc_status)}</h3>
      {loc_html if loc_html else "<p class='empty-note'>No registered workplaces found.</p>"}
    </section>

    <!-- Website -->
    <section class="section">
      <h3>🌐 Website {_badge(web_status)}</h3>
      {f'<p><a href="{html.escape(web_url)}" target="_blank" rel="noopener">{html.escape(web_url)}</a></p>' if web_url else ""}
      {score_bar}
      {f'<p class="note">Identity score reasons: {html.escape(str(web_id.get("reasons", [])))}</p>' if web_id.get("reasons") else ""}
      {f'<p class="empty-note">{html.escape(web_ev.get("note",""))}</p>' if web_status in ("not_available","ambiguous","blocked") and web_ev.get("note") else ""}
    </section>

  </div>
</article>
"""


# ── full page HTML ───────────────────────────────────────────────────────────

def _build_html(profiles: list[dict], run_id: str, generated_at: str) -> str:
    cards = "\n".join(_render_profile(p) for p in profiles)
    total = len(profiles)
    available_web = sum(1 for p in profiles if (p.get("evidence") or {}).get("website", {}).get("status") == "available")
    available_reg = sum(1 for p in profiles if (p.get("evidence") or {}).get("registry_live", {}).get("status") == "available"
                        or (p.get("evidence") or {}).get("registry", {}).get("status") == "available")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="Signalpost — Norwegian company research profiles. Evidence-backed, deterministic, no LLM.">
  <title>Signalpost — Company Research Report</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #0f172a; --surface: #1e293b; --surface2: #273447;
      --accent: #38bdf8; --accent2: #818cf8;
      --text: #e2e8f0; --muted: #94a3b8; --border: #334155;
      --green: #22c55e; --yellow: #eab308; --red: #ef4444; --orange: #f97316;
      --radius: 10px; --shadow: 0 4px 24px rgba(0,0,0,.4);
    }}
    body {{ font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text);
            min-height: 100vh; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* ── Header ── */
    .site-header {{ background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
                    border-bottom: 1px solid var(--border); padding: 2rem 1rem 1.5rem; text-align: center; }}
    .site-header h1 {{ font-size: clamp(1.8rem,4vw,2.8rem); font-weight: 800;
                       background: linear-gradient(90deg,var(--accent),var(--accent2));
                       -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
    .site-header .subtitle {{ color: var(--muted); margin-top: .4rem; font-size: .95rem; }}
    .stats-bar {{ display: flex; justify-content: center; gap: 2rem; margin-top: 1.2rem; flex-wrap: wrap; }}
    .stat {{ text-align: center; }}
    .stat-value {{ font-size: 1.6rem; font-weight: 700; color: var(--accent); }}
    .stat-label {{ font-size: .75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }}

    /* ── Search ── */
    .search-wrap {{ max-width: 700px; margin: 1.5rem auto; padding: 0 1rem; }}
    #search {{ width: 100%; padding: .75rem 1.1rem; border-radius: 8px;
               border: 1.5px solid var(--border); background: var(--surface);
               color: var(--text); font-size: 1rem; outline: none; transition: border-color .2s; }}
    #search:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px rgba(56,189,248,.15); }}

    /* ── Cards ── */
    .cards-container {{ max-width: 960px; margin: 0 auto; padding: 1rem 1rem 3rem; }}
    .company-card {{ background: var(--surface); border: 1px solid var(--border);
                     border-radius: var(--radius); margin-bottom: 1.5rem;
                     box-shadow: var(--shadow); overflow: hidden;
                     transition: transform .15s, box-shadow .15s; }}
    .company-card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 32px rgba(0,0,0,.5); }}
    .company-card.hidden {{ display: none; }}

    /* ── Card header ── */
    .card-header {{ display: flex; justify-content: space-between; align-items: flex-start;
                    padding: 1.2rem 1.4rem .8rem; gap: 1rem; flex-wrap: wrap;
                    background: linear-gradient(90deg, var(--surface2) 0%, var(--surface) 100%);
                    border-bottom: 1px solid var(--border); }}
    .company-name {{ font-size: 1.2rem; font-weight: 700; color: var(--text); }}
    .company-meta {{ color: var(--muted); font-size: .82rem; margin-top: .3rem; }}
    .org-number {{ font-family: monospace; background: var(--bg); padding: .1rem .4rem;
                   border-radius: 4px; font-size: .8rem; }}
    .card-badges {{ display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }}
    .web-link {{ background: linear-gradient(135deg,var(--accent),var(--accent2));
                 color: #0f172a; padding: .25rem .7rem; border-radius: 6px;
                 font-size: .78rem; font-weight: 700; white-space: nowrap; }}

    /* ── Summary ── */
    .summary-text {{ padding: .8rem 1.4rem; color: #cbd5e1; font-size: .9rem; font-style: italic;
                     border-bottom: 1px solid var(--border); line-height: 1.6; }}

    /* ── Sections ── */
    .sections {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0;
                 border-top: none; }}
    @media (max-width: 640px) {{ .sections {{ grid-template-columns: 1fr; }} }}
    .section {{ padding: 1rem 1.4rem; border-right: 1px solid var(--border);
                border-bottom: 1px solid var(--border); }}
    .section:nth-child(even) {{ border-right: none; }}
    .section:nth-last-child(-n+2) {{ border-bottom: none; }}
    .section h3 {{ font-size: .85rem; font-weight: 700; color: var(--accent); text-transform: uppercase;
                   letter-spacing: .05em; margin-bottom: .7rem; display: flex; align-items: center; gap: .4rem; }}

    /* ── KV grid ── */
    .kv-grid {{ display: grid; grid-template-columns: auto 1fr; gap: .2rem .8rem; font-size: .82rem; }}
    .kv-key {{ color: var(--muted); white-space: nowrap; }}
    .kv-val {{ color: var(--text); word-break: break-word; }}

    /* ── Table ── */
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .8rem; }}
    th {{ color: var(--muted); text-transform: uppercase; font-size: .72rem;
          letter-spacing: .04em; padding: .4rem .5rem; text-align: left;
          border-bottom: 1px solid var(--border); }}
    td {{ padding: .4rem .5rem; border-bottom: 1px solid rgba(255,255,255,.04); }}
    tr:last-child td {{ border-bottom: none; }}

    /* ── Roles & Locations ── */
    .role-item {{ display: flex; justify-content: space-between; align-items: center;
                  padding: .3rem 0; border-bottom: 1px solid rgba(255,255,255,.05); font-size: .83rem; }}
    .role-item:last-child {{ border-bottom: none; }}
    .role-label {{ color: var(--muted); font-size: .78rem; background: var(--bg);
                   padding: .1rem .4rem; border-radius: 4px; }}
    .loc-item {{ display: flex; gap: .5rem; align-items: center; padding: .25rem 0;
                 font-size: .83rem; flex-wrap: wrap; }}

    /* ── Badges ── */
    .badge {{ display: inline-block; padding: .15rem .5rem; border-radius: 999px;
              font-size: .72rem; font-weight: 700; color: #fff; letter-spacing: .02em;
              text-transform: uppercase; }}
    .badge-sm {{ font-size: .72rem; color: var(--muted); background: var(--bg);
                 padding: .1rem .35rem; border-radius: 4px; }}

    /* ── Score bar ── */
    .score-bar-wrap {{ background: var(--bg); border-radius: 4px; height: 8px;
                       position: relative; margin: .4rem 0; overflow: hidden; }}
    .score-bar {{ height: 100%; border-radius: 4px; transition: width .3s; }}
    .score-label {{ font-size: .75rem; color: var(--muted); }}

    /* ── Misc ── */
    .empty-note {{ color: var(--muted); font-size: .83rem; font-style: italic; }}
    .note {{ color: var(--muted); font-size: .78rem; margin-top: .4rem; word-break: break-word; }}
    .no-results {{ text-align: center; padding: 3rem; color: var(--muted); font-size: 1.1rem; display: none; }}

    /* ── Footer ── */
    .site-footer {{ text-align: center; padding: 1.5rem; color: var(--muted); font-size: .78rem;
                    border-top: 1px solid var(--border); background: var(--surface); }}
  </style>
</head>
<body>

<header class="site-header">
  <h1>📡 Signalpost</h1>
  <p class="subtitle">Norwegian company research — deterministic, evidence-backed, zero LLM</p>
  <div class="stats-bar">
    <div class="stat"><div class="stat-value">{total:,}</div><div class="stat-label">Companies</div></div>
    <div class="stat"><div class="stat-value">{available_reg:,}</div><div class="stat-label">Registry ✓</div></div>
    <div class="stat"><div class="stat-value">{available_web:,}</div><div class="stat-label">Websites ✓</div></div>
    <div class="stat"><div class="stat-value">{html.escape(run_id)}</div><div class="stat-label">Run ID</div></div>
    <div class="stat"><div class="stat-value">{html.escape(generated_at[:10])}</div><div class="stat-label">Generated</div></div>
  </div>
</header>

<div class="search-wrap">
  <input id="search" type="search" placeholder="Search by name, org number, or municipality…"
         autocomplete="off" spellcheck="false" aria-label="Search companies">
</div>

<main class="cards-container" role="main">
  <p class="no-results" id="no-results">No companies match your search.</p>
  {cards}
</main>

<footer class="site-footer">
  Signalpost · Builderr Hackathon 2026 · Run <strong>{html.escape(run_id)}</strong> ·
  Generated {html.escape(generated_at[:19].replace("T"," "))} UTC ·
  <strong>No LLM used</strong> · All data from official Norwegian sources (Brønnøysundregistrene)
</footer>

<script>
(function() {{
  const input = document.getElementById("search");
  const noResults = document.getElementById("no-results");
  const cards = Array.from(document.querySelectorAll(".company-card"));

  input.addEventListener("input", function() {{
    const q = this.value.trim().toLowerCase();
    let visible = 0;
    cards.forEach(function(card) {{
      const match = !q
        || card.dataset.name.includes(q)
        || card.dataset.org.includes(q)
        || card.dataset.muni.includes(q);
      card.classList.toggle("hidden", !match);
      if (match) visible++;
    }});
    noResults.style.display = visible === 0 ? "block" : "none";
  }});
}})();
</script>

</body>
</html>
"""


# ── entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Build Signalpost static HTML report")
    parser.add_argument("--profiles", required=True, help="Profiles JSONL file")
    parser.add_argument("--output", required=True, help="Output HTML file path")
    parser.add_argument("--run-id", default="local", help="Run identifier")
    args = parser.parse_args()

    profiles_path = Path(args.profiles)
    if not profiles_path.exists():
        raise SystemExit(f"Profiles file not found: {profiles_path}")

    profiles = [
        json.loads(line)
        for line in profiles_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"Loaded {len(profiles)} profiles")

    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    html_content = _build_html(profiles, run_id=args.run_id, generated_at=generated_at)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_content, encoding="utf-8")
    print(f"Report written to {output}  ({output.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
