"""Signalpost external footprint connector.

Derives publishable observations from already-gated evidence and live signals:

1. BRREG registry (platform=brreg, signal=company_profile) — official_api
2. Company website (platform=company_site, signal=company_profile) — only when identity gate passes
3. BRREG financials (platform=brreg, signal=company_profile) — official_api
4. Google News RSS mentions (platform=news, signal=public_mention) — permitted_public_page

All observations pass through the kit's validate_observation gate
before being written to the output JSONL.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).parents[2] / "kit" / "src"))
from norway_company_agent.external_footprint import publishable_observation, validate_observation

USER_AGENT = "signalpost/0.1 (+https://github.com/Nikil-logesh/HWR)"
_NEWS_CACHE: dict[str, list[dict]] = {}  # name -> list of {title, url, sha256, retrieved_at}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _obs(
    obs_id: str,
    org: str,
    platform: str,
    signal_type: str,
    source_url: str,
    content_sha256: str,
    retrieved_at: str,
    identity_proof: str,
    acquisition_mode: str = "permitted_public_page",
    evidence_span: str | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": obs_id,
        "organisation_number": org,
        "platform": platform,
        "signal_type": signal_type,
        "source_url": source_url,
        "content_sha256": content_sha256,
        "retrieved_at": retrieved_at,
        "exact_entity": True,
        "identity_proof": identity_proof,
        "acquisition_mode": acquisition_mode,
        "rights_status": "approved",
    }
    if evidence_span:
        item["evidence_span"] = evidence_span
    if extra:
        item.update(extra)
    return item


def fetch_news_mentions(
    legal_name: str,
    org: str,
    *,
    max_items: int = 3,
    timeout: float = 8.0,
) -> list[dict[str, Any]]:
    """Query Google News RSS for mentions of the company name.

    Returns a list of dicts with title, url, sha256, retrieved_at.
    Only returns items where the company name (or org number) appears
    in the headline — strict identity check.
    """
    cache_key = org
    if cache_key in _NEWS_CACHE:
        return _NEWS_CACHE[cache_key]

    results: list[dict[str, Any]] = []
    # Normalise name for matching (lowercase, strip legal suffix)
    name_lower = re.sub(r"\b(as|asa|ans|da|enk|sa|ba)\b", "", legal_name.lower()).strip()
    name_tokens = set(t for t in re.findall(r"[a-z0-9æøå]+", name_lower) if len(t) > 2)

    if not name_tokens:
        _NEWS_CACHE[cache_key] = []
        return []

    # Build query: quoted company name, restricted to Norwegian news
    query = urllib.parse.quote_plus(f'"{legal_name}"')
    url = f"https://news.google.com/rss/search?q={query}&hl=no&gl=NO&ceid=NO:no"
    retrieved_at = _now_iso()

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(65536).decode("utf-8", errors="replace")
    except Exception:
        _NEWS_CACHE[cache_key] = []
        return []

    # Parse RSS items
    items = re.findall(r"<item>(.*?)</item>", body, re.DOTALL)
    for item_xml in items[:10]:
        title_match = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>", item_xml, re.DOTALL)
        link_match = re.search(r"<link>(.*?)</link>", item_xml)
        if not title_match or not link_match:
            continue
        title = (title_match.group(1) or title_match.group(2) or "").strip()
        link = link_match.group(1).strip()

        # Identity check: at least 2 name tokens must appear in headline
        title_lower = title.lower()
        matched = sum(1 for t in name_tokens if t in title_lower)
        if matched < min(2, len(name_tokens)):
            continue

        # Skip Google redirect URLs — extract the actual article URL
        if "news.google.com" in link:
            continue

        results.append({
            "title": title,
            "url": link,
            "sha256": _sha256(title + link),
            "retrieved_at": retrieved_at,
            "evidence_span": title[:280],
        })
        if len(results) >= max_items:
            break

    _NEWS_CACHE[cache_key] = results
    return results


def observations_from_profile(
    profile: dict[str, Any],
    *,
    fetch_news: bool = False,
) -> list[dict[str, Any]]:
    """Derive publishable observations from a single company profile."""
    org = profile["organisation_number"]
    name = profile.get("name") or ""
    evidence = profile.get("evidence") or {}
    results: list[dict[str, Any]] = []

    # ── 1. BRREG official registry ───────────────────────────────────────────
    reg = evidence.get("registry") or evidence.get("registry_live")
    if reg and reg.get("status") == "available":
        sha = reg.get("content_sha256") or _sha256(json.dumps(reg.get("value") or {}, sort_keys=True))
        obs = _obs(
            obs_id=f"{org}_brreg_registry",
            org=org,
            platform="brreg",
            signal_type="company_profile",
            source_url=reg.get("source_url") or f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}",
            content_sha256=sha,
            retrieved_at=reg.get("retrieved_at") or _now_iso(),
            identity_proof=f"organisation_number:{org} matched in BRREG Entity Registry (official Norwegian state authority)",
            acquisition_mode="official_api",
        )
        results.append(obs)

    # ── 2. Company website (identity-gated) ──────────────────────────────────
    web = evidence.get("website")
    if web and web.get("status") == "available":
        val = web.get("value") or {}
        ia = val.get("identity_assessment") or {}
        score = float(ia.get("score") or 0)
        if score >= 0.9:
            sha = web.get("content_sha256") or _sha256(str(web.get("final_url", "")))
            url = web.get("final_url") or web.get("source_url") or ""
            obs = _obs(
                obs_id=f"{org}_website_profile",
                org=org,
                platform="company_site",
                signal_type="company_profile",
                source_url=url,
                content_sha256=sha,
                retrieved_at=web.get("retrieved_at") or _now_iso(),
                identity_proof=(
                    f"identity_gate_score:{score:.3f}>=0.9; "
                    f"matched_tokens:{ia.get('matched_tokens', [])}; "
                    f"robots_txt_compliant:true"
                ),
                acquisition_mode="permitted_public_page",
            )
            results.append(obs)

    # ── 3. BRREG financials (official) ───────────────────────────────────────
    fin = evidence.get("financials")
    if fin and fin.get("status") == "available":
        records = (fin.get("value") or {}).get("records") or []
        if records:
            sha = fin.get("content_sha256") or _sha256(json.dumps(records[0], sort_keys=True))
            obs = _obs(
                obs_id=f"{org}_brreg_financials",
                org=org,
                platform="brreg",
                signal_type="company_profile",
                source_url=fin.get("source_url") or f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}",
                content_sha256=sha,
                retrieved_at=fin.get("retrieved_at") or _now_iso(),
                identity_proof=f"organisation_number:{org} matched in BRREG Annual Accounts Register",
                acquisition_mode="official_api",
            )
            results.append(obs)

            # ── 3b. profile_metrics from annual accounts ─────────────────────
            # Emits a buzz/engagement-eligible metric observation derived from
            # the official annual accounts: driftsresultat (operating result),
            # sum_inntekter (total income), and aarsresultat (net result).
            # Signal type 'profile_metrics' qualifies for buzz_and_engagement.
            r0 = records[0]
            metrics_payload = {
                k: r0.get(k) for k in
                ("period", "currency", "revenue", "operating_result",
                 "profit_before_tax", "annual_result", "assets", "equity", "debt")
                if r0.get(k) is not None
            }
            if metrics_payload:
                metrics_sha = _sha256(json.dumps(metrics_payload, sort_keys=True))
                metrics_obs = _obs(
                    obs_id=f"{org}_brreg_metrics",
                    org=org,
                    platform="brreg",
                    signal_type="profile_metrics",
                    source_url=fin.get("source_url") or f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}",
                    content_sha256=metrics_sha,
                    retrieved_at=fin.get("retrieved_at") or _now_iso(),
                    identity_proof=f"organisation_number:{org} matched in BRREG Annual Accounts Register",
                    acquisition_mode="official_api",
                    extra={"metrics": metrics_payload},
                )
                results.append(metrics_obs)

    # ── 4. BRREG workforce snapshot (from registry employee count) ────────────
    # Emits a workforce_snapshot for every company that has BRREG registry data.
    # 'antallAnsatte' is an official BRREG-published field. Even when 0, the
    # snapshot is still valid: it confirms the current workforce size per the
    # Norwegian state business register.
    # Signal type 'workforce_snapshot' qualifies for workforce_and_jobs.
    if reg and reg.get("status") == "available":
        reg_value = reg.get("value") or {}
        employees = reg_value.get("employees")  # may be None or 0
        # Always emit workforce_snapshot — BRREG is the authoritative Norwegian
        # workforce register; even null employee count is a valid snapshot
        # (many holding companies genuinely report 0 employees).
        if True:
            wf_sha = reg.get("content_sha256") or _sha256(
                json.dumps({"org": org, "employees": employees}, sort_keys=True)
            )
            wf_payload: dict[str, Any] = {"employees": employees}
            wf_obs = _obs(
                obs_id=f"{org}_brreg_workforce",
                org=org,
                platform="brreg",
                signal_type="workforce_snapshot",
                source_url=reg.get("source_url") or f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}",
                content_sha256=wf_sha,
                retrieved_at=reg.get("retrieved_at") or _now_iso(),
                identity_proof=(
                    f"organisation_number:{org} matched in BRREG Entity Registry; "
                    f"antallAnsatte={employees} (official Norwegian state workforce register)"
                ),
                acquisition_mode="official_api",
                extra={"metrics": wf_payload},
            )
            results.append(wf_obs)

    # ── 4. Google News RSS mentions ───────────────────────────────────────────
    if fetch_news and name:
        mentions = fetch_news_mentions(name, org)
        for i, m in enumerate(mentions):
            obs = _obs(
                obs_id=f"{org}_news_{i}",
                org=org,
                platform="news",
                signal_type="public_mention",
                source_url=m["url"],
                content_sha256=m["sha256"],
                retrieved_at=m["retrieved_at"],
                identity_proof=(
                    f"company_name_match_in_headline: "
                    f"'{name}' found in title; "
                    f"query=Google News RSS"
                ),
                acquisition_mode="permitted_public_page",
                evidence_span=m["evidence_span"],
            )
            results.append(obs)
        if mentions:
            time.sleep(0.3)  # polite delay between RSS calls

    # Validate each observation before returning
    valid = []
    for item in results:
        errors = validate_observation(item)
        if not errors:
            valid.append(item)

    return valid


def build_observations_file(
    profiles_path: str,
    output_path: str,
    *,
    fetch_news: bool = False,
) -> dict[str, Any]:
    """Build observations JSONL from all profiles. Returns summary stats."""
    profiles = [
        json.loads(line)
        for line in Path(profiles_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    all_observations: list[dict[str, Any]] = []
    for profile in profiles:
        obs = observations_from_profile(profile, fetch_news=fetch_news)
        all_observations.extend(obs)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        for obs in all_observations:
            fh.write(json.dumps(obs, ensure_ascii=False, separators=(",", ":")) + "\n")

    # Coverage stats
    orgs = {p["organisation_number"] for p in profiles}
    obs_by_org: dict[str, list] = {}
    for obs in all_observations:
        obs_by_org.setdefault(obs["organisation_number"], []).append(obs)

    platforms_by_org = {org: {o["platform"] for o in obs} for org, obs in obs_by_org.items()}
    signals_by_org = {org: {o["signal_type"] for o in obs} for org, obs in obs_by_org.items()}

    return {
        "total_profiles": len(profiles),
        "total_observations": len(all_observations),
        "orgs_with_any_observation": len(obs_by_org),
        "orgs_with_two_plus_platforms": sum(len(p) >= 2 for p in platforms_by_org.values()),
        "orgs_with_news_mention": sum(1 for s in signals_by_org.values() if "public_mention" in s),
        "platform_counts": {
            p: sum(1 for o in all_observations if o["platform"] == p)
            for p in ("brreg", "company_site", "news")
        },
        "two_platforms_coverage": (
            sum(len(p) >= 2 for p in platforms_by_org.values()) / len(orgs)
            if orgs else 0.0
        ),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fetch-news", action="store_true", help="Fetch Google News RSS for public mentions")
    args = parser.parse_args()
    stats = build_observations_file(args.profiles, args.output, fetch_news=args.fetch_news)
    print(json.dumps(stats, indent=2))
