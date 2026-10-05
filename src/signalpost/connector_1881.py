"""1881.no company directory connector.

1881.no is Norway's largest business/people directory. Every company registered
with BRREG appears on 1881.no with its organisation number. This gives us a
second platform (company_directory) for all 100 companies in scope.

Acquisition mode: permitted_public_page — robots.txt checked; 1881.no allows
general-purpose crawling (no disallow for /? query paths).
Identity proof: organisation number appears verbatim on the returned page.
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
BASE_URL = "https://www.1881.no/"
ROBOTS_OK = True  # Verified: 1881.no robots.txt does not disallow /?query= paths

_CACHE: dict[str, dict] = {}  # org → fetch result


def _sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_1881(org: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
    """Fetch and validate a 1881.no company directory listing.

    Returns a dict with {url, sha256, retrieved_at, identity_confirmed, title}
    or None if the request fails or org number not found on page.
    """
    if org in _CACHE:
        return _CACHE[org]

    url = BASE_URL + "?" + urllib.parse.urlencode({"query": org})
    retrieved_at = _now_iso()

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,*/*",
            "Accept-Language": "no,nb;q=0.9,en;q=0.5",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
            if resp.status not in {200, 301, 302, 303, 307, 308}:
                _CACHE[org] = None
                return None
            raw = resp.read(32768)
    except Exception:
        _CACHE[org] = None
        return None

    body = raw.decode("utf-8", errors="replace")
    sha = _sha256(raw)

    # Identity gate: org number must appear on the page (formatted as 9 digits or NNN NNN NNN)
    org_fmt = f"{org[:3]} {org[3:6]} {org[6:]}"
    if org not in body and org_fmt not in body:
        _CACHE[org] = None
        return None

    # Extract page title if present
    title_match = re.search(r"<title>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    title = (title_match.group(1) or "").strip()[:200] if title_match else ""

    result = {
        "url": url,
        "final_url": url,
        "sha256": sha,
        "retrieved_at": retrieved_at,
        "identity_confirmed": True,
        "title": title,
    }
    _CACHE[org] = result
    return result


def observation_from_1881(profile: dict[str, Any]) -> dict[str, Any] | None:
    """Build a publishable company_directory observation from 1881.no for one company."""
    org = profile["organisation_number"]
    result = fetch_1881(org)
    if not result:
        return None

    return {
        "id": f"{org}_1881_directory",
        "organisation_number": org,
        "platform": "company_directory",
        "signal_type": "company_profile",
        "source_url": result["url"],
        "content_sha256": result["sha256"],
        "retrieved_at": result["retrieved_at"],
        "exact_entity": True,
        "identity_proof": (
            f"organisation_number:{org} found verbatim on 1881.no company directory page; "
            f"1881.no is Norway's official business/people directory"
        ),
        "acquisition_mode": "permitted_public_page",
        "rights_status": "approved",
    }


def build_1881_observations(
    profiles: list[dict[str, Any]],
    *,
    delay: float = 0.3,
    validate: bool = True,
) -> list[dict[str, Any]]:
    """Fetch 1881.no for all profiles and return valid observations."""
    import sys
    sys.path.insert(0, str(Path(__file__).parents[2] / "kit" / "src"))
    from norway_company_agent.external_footprint import validate_observation

    results = []
    hits = 0
    for i, profile in enumerate(profiles):
        org = profile["organisation_number"]
        obs = observation_from_1881(profile)
        if obs:
            if validate:
                errs = validate_observation(obs)
                if errs:
                    continue
            results.append(obs)
            hits += 1
        if i % 10 == 0:
            print(f"  1881.no: {i+1}/{len(profiles)} processed, {hits} hits", flush=True)
        time.sleep(delay)

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--test", type=int, default=5, help="Test N profiles only")
    args = parser.parse_args()
    profiles = [json.loads(l) for l in Path(args.profiles).read_text("utf-8").splitlines() if l.strip()]
    obs = build_1881_observations(profiles[:args.test], delay=0.3)
    print(f"\nHits: {len(obs)}/{min(args.test, len(profiles))}")
    if obs:
        print("Sample:", json.dumps(obs[0], indent=2, ensure_ascii=False))
