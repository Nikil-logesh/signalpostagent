"""Signalpost website candidate discovery.

Deterministic (no LLM) fallback for companies whose Brreg record has no
registered website URL.

Strategy (priority order):
1. Use registered URL from bulk/live registry (free, no requests)
2. Construct a candidate from company name → most likely .no domain
3. Brave Search API (quarantined — only active when BRAVE_SEARCH_API_KEY is set)
4. Google News RSS (candidate link extraction only, transient)

Every candidate found here is fed into the existing identity gate in
website.py before anything is published. Candidates are not evidence.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "signalpost/0.1 (+https://github.com/Nikil-logesh/HWR)"
BRAVE_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_CANDIDATE_CACHE: dict[str, list[str]] = {}  # org → [url, ...]


def _normalise_name_to_domain_guess(legal_name: str) -> str | None:
    """Best-effort heuristic: 'Sandnes Elektriske AS' → 'sandneselektriske.no'."""
    if not legal_name:
        return None
    SKIP = {
        "as", "asa", "ans", "da", "enk", "sa", "ba", "stb", "nuf", "fli",
        "iks", "brl", "orgl", "esek", "the", "og", "and", "b", "v"
    }
    # Transliterate Norwegian chars
    name = legal_name.translate(str.maketrans({
        "ø": "o", "Ø": "o", "å": "a", "Å": "a", "æ": "ae", "Æ": "ae"
    }))
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    tokens = [t for t in re.findall(r"[a-z0-9]+", name) if t not in SKIP and len(t) > 1]
    if not tokens:
        return None
    # Common patterns: first-token.no, concatenated.no
    slug = "".join(tokens[:3])
    if len(slug) < 3 or len(slug) > 63:
        return None
    return f"https://{slug}.no"


def _google_news_rss_candidates(legal_name: str) -> list[str]:
    """Query Google News RSS for company mentions; extract source domains as candidates."""
    try:
        query = urllib.parse.quote_plus(f'"{legal_name}" site:*.no')
        url = f"https://news.google.com/rss/search?q={query}&hl=no&gl=NO&ceid=NO:no"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            body = resp.read(65536).decode("utf-8", errors="replace")
        # Extract <link> and <source url="..."> entries
        links = re.findall(r'<link>([^<]+)</link>', body)
        sources = re.findall(r'<source url="([^"]+)"', body)
        candidates = []
        for raw in links + sources:
            parsed = urllib.parse.urlparse(raw)
            host = parsed.hostname or ""
            if host and ".no" in host and "google.com" not in host:
                base = f"https://{host}"
                if base not in candidates:
                    candidates.append(base)
        return candidates[:5]
    except Exception:
        return []


def _brave_search_candidates(legal_name: str, municipality: str | None) -> list[str]:
    """Query Brave Search API for candidate URLs. Quarantined — only runs with API key."""
    if not BRAVE_KEY:
        return []
    try:
        q = legal_name
        if municipality:
            q += f" {municipality}"
        params = urllib.parse.urlencode({"q": q, "count": 5, "country": "NO", "search_lang": "no"})
        req = urllib.request.Request(
            f"{BRAVE_ENDPOINT}?{params}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json", "X-Subscription-Token": BRAVE_KEY},
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            import json
            data = json.loads(resp.read(65536))
        results = data.get("web", {}).get("results", [])
        candidates = []
        for r in results[:5]:
            url = r.get("url", "")
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname or ""
            if host and ("google" not in host) and ("facebook" not in host):
                base = f"https://{parsed.scheme or 'https'}://{host}"
                # Normalise to origin
                base = f"{parsed.scheme or 'https'}://{parsed.netloc}"
                if base not in candidates:
                    candidates.append(base)
        return candidates[:5]
    except Exception:
        return []


def discover_candidates(
    organisation_number: str,
    legal_name: str | None,
    *,
    registered_url: str | None = None,
    municipality: str | None = None,
    enable_news_rss: bool = True,
) -> list[str]:
    """Return an ordered list of website candidates to try through the identity gate.

    Returns at most 6 candidates. The registered URL (if any) is always first.
    No candidate is evidence — all must pass the identity gate before publication.
    """
    cache_key = organisation_number
    if cache_key in _CANDIDATE_CACHE:
        return _CANDIDATE_CACHE[cache_key]

    candidates: list[str] = []

    # 1. Registered URL always first (highest confidence seed)
    if registered_url and registered_url.strip():
        url = registered_url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        candidates.append(url)

    if len(candidates) >= 6:
        _CANDIDATE_CACHE[cache_key] = candidates
        return candidates

    # 2. Brave Search (requires API key — quarantined by default)
    if BRAVE_KEY and legal_name:
        for c in _brave_search_candidates(legal_name, municipality):
            if c not in candidates:
                candidates.append(c)
        if len(candidates) >= 6:
            _CANDIDATE_CACHE[cache_key] = candidates
            return candidates

    # 3. Name-to-domain heuristic (deterministic, no network)
    if legal_name:
        guess = _normalise_name_to_domain_guess(legal_name)
        if guess and guess not in candidates:
            candidates.append(guess)

    # 4. Google News RSS (transient candidate discovery; retained evidence = fetched page only)
    if enable_news_rss and legal_name and len(candidates) < 4:
        for c in _google_news_rss_candidates(legal_name):
            if c not in candidates:
                candidates.append(c)
            if len(candidates) >= 6:
                break

    _CANDIDATE_CACHE[cache_key] = candidates[:6]
    return _CANDIDATE_CACHE[cache_key]
