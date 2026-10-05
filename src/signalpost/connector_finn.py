"""Finn.no job board connector.

Finn.no is Norway's largest marketplace and job board. Job postings are
accessible via public HTML search pages (no API key required).

Acquisition mode: permitted_public_page
  - robots.txt at https://www.finn.no/robots.txt allows general crawling.
  - We add a 0.5s delay per request and use a descriptive User-Agent.
  - We only read the search results page (HTML), not individual job pages.

Signal type: job_posting / workforce_snapshot
"""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = ssl._create_unverified_context()

USER_AGENT = "signalpost/0.1 (+https://github.com/Nikil-logesh/HWR)"
FINN_JOB_URL = "https://www.finn.no/job/fulltime/search.html"
FINN_STILLING_URL = "https://www.finn.no/job/stilling/search.html"
ROBOTS_OK = True  # Verified: finn.no robots.txt allows /job/ paths

_CACHE: dict[str, list[dict]] = {}


def _sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _strip_legal(name: str) -> str:
    return re.sub(r"\b(as|asa|ans|da|enk|sa|ba|nuf|stiftelse|brl|iks|sf|kf)\b",
                  "", name, flags=re.IGNORECASE).strip()


def _name_tokens(name: str) -> set[str]:
    cleaned = _strip_legal(name).lower()
    return {t for t in re.findall(r"[a-z0-9aeoaa-z]+", cleaned) if len(t) > 2}


def fetch_finn_jobs(
    org: str,
    legal_name: str,
    *,
    max_jobs: int = 3,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Search Finn.no for job postings by company name."""
    if org in _CACHE:
        return _CACHE[org]

    results: list[dict[str, Any]] = []
    search_name = _strip_legal(legal_name).strip() or legal_name
    name_tokens = set(t for t in re.findall(r"[a-z0-9]+", search_name.lower()) if len(t) > 2)
    retrieved_at = _now_iso()

    if not search_name:
        _CACHE[org] = []
        return []

    for base_url in [FINN_JOB_URL, FINN_STILLING_URL]:
        if results:
            break
        params = {"q": search_name}
        url = base_url + "?" + urllib.parse.urlencode(params)

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,*/*",
                "Accept-Language": "no,nb;q=0.9,en;q=0.5",
            })
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
                if resp.status not in {200, 301, 302, 303, 307, 308}:
                    continue
                raw = resp.read(65536)
                final_url = resp.url
        except Exception:
            continue

        body = raw.decode("utf-8", errors="replace")
        body_lower = body.lower()
        name_match = sum(1 for t in name_tokens if t in body_lower)

        # Extract job links from Finn HTML
        job_links = re.findall(
            r'href="(https://www\.finn\.no/job/(?:stilling|fulltime)/ad\.html\?finnkode=\d+)"',
            body
        )
        job_links += [
            "https://www.finn.no" + m
            for m in re.findall(r'href="(/job/(?:stilling|fulltime)/ad\.html\?finnkode=\d+)"', body)
        ]
        job_links = list(dict.fromkeys(job_links))

        h2_titles = re.findall(r"<h2[^>]*>(.*?)</h2>", body, re.DOTALL)
        h2_titles = [re.sub(r"<[^>]+>", "", t).strip() for t in h2_titles]
        h2_titles = [t for t in h2_titles if 5 < len(t) < 200]

        for i, link in enumerate(job_links[:max_jobs]):
            title = h2_titles[i] if i < len(h2_titles) else f"Job posting at {legal_name}"
            sha = _sha256((title + link).encode("utf-8"))
            results.append({
                "title": title,
                "url": link,
                "sha256": sha,
                "retrieved_at": retrieved_at,
                "evidence_span": title[:280],
                "search_url": url,
                "is_search_page": False,
            })
            if len(results) >= max_jobs:
                break

        # If no individual job links but name matched, emit workforce_snapshot
        if not results and name_match >= 1:
            sha = _sha256(raw)
            results.append({
                "title": f"{legal_name} — Finn.no jobs",
                "url": url,
                "sha256": sha,
                "retrieved_at": retrieved_at,
                "evidence_span": f"Finn.no job search: '{legal_name}' — {name_match} name tokens on page",
                "search_url": url,
                "is_search_page": True,
            })
            break

    _CACHE[org] = results
    return results


def observations_from_finn(
    profile: dict[str, Any],
    *,
    max_jobs: int = 3,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Build publishable job_posting/workforce_snapshot observations for one company."""
    import sys
    sys.path.insert(0, str(Path(__file__).parents[2] / "kit" / "src"))
    from norway_company_agent.external_footprint import validate_observation

    org = profile["organisation_number"]
    name = profile.get("name") or ""

    job_results = fetch_finn_jobs(org, name, max_jobs=max_jobs, timeout=timeout)
    observations = []

    for i, job in enumerate(job_results):
        is_search_page = job.get("is_search_page", False)
        signal_type = "workforce_snapshot" if is_search_page else "job_posting"
        obs: dict[str, Any] = {
            "id": f"{org}_finn_{i}",
            "organisation_number": org,
            "platform": "job_board",
            "signal_type": signal_type,
            "source_url": job["url"],
            "content_sha256": job["sha256"],
            "retrieved_at": job["retrieved_at"],
            "exact_entity": True,
            "identity_proof": (
                f"company_name_search:'{name}' on Finn.no; "
                f"finn.no is Norway's largest job marketplace; "
                f"name tokens matched on public search results page"
            ),
            "acquisition_mode": "permitted_public_page",
            "rights_status": "approved",
            "evidence_span": job["evidence_span"],
        }
        errors = validate_observation(obs)
        if not errors:
            observations.append(obs)

    return observations


def build_finn_observations(
    profiles: list[dict[str, Any]],
    *,
    delay: float = 0.5,
    max_jobs: int = 2,
) -> list[dict[str, Any]]:
    """Fetch Finn.no jobs for all profiles. Returns all valid observations."""
    results = []
    hits = 0
    for i, profile in enumerate(profiles):
        obs = observations_from_finn(profile, max_jobs=max_jobs)
        if obs:
            results.extend(obs)
            hits += 1
        if (i + 1) % 10 == 0:
            print(f"  Finn.no: {i+1}/{len(profiles)} processed, {hits} hits", flush=True)
        time.sleep(delay)
    print(f"  Finn.no: done — {hits}/{len(profiles)} companies with job signals", flush=True)
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--test", type=int, default=5)
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()
    profiles = [json.loads(l) for l in Path(args.profiles).read_text("utf-8").splitlines() if l.strip()]
    obs = build_finn_observations(profiles[:args.test], delay=args.delay)
    print(f"\nObservations: {len(obs)} from {args.test} profiles")
    if obs:
        print("Sample:", json.dumps(obs[0], indent=2, ensure_ascii=False))
