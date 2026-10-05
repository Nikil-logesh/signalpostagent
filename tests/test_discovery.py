"""Tests for Phase 8 — candidate discovery and improved website coverage."""
from __future__ import annotations

import pytest

from signalpost.discovery import (
    _normalise_name_to_domain_guess,
    _google_news_rss_candidates,
    discover_candidates,
)


# ── name-to-domain heuristic ─────────────────────────────────────────────────

def test_name_heuristic_produces_no_domain() -> None:
    """Returns None for empty / single-char / skip-only names."""
    assert _normalise_name_to_domain_guess("") is None
    assert _normalise_name_to_domain_guess("AS") is None
    assert _normalise_name_to_domain_guess("ENK") is None


def test_name_heuristic_sandnes_elektriske() -> None:
    guess = _normalise_name_to_domain_guess("Sandnes Elektriske AS")
    assert guess is not None
    assert guess.startswith("https://")
    assert ".no" in guess
    assert "sandneselektriske" in guess or "sandnes" in guess


def test_name_heuristic_transliterates_norwegian_chars() -> None:
    guess = _normalise_name_to_domain_guess("Ørken Håndverk")
    assert guess is not None
    assert "8b" not in guess           # no raw bytes
    assert all(ord(c) < 128 for c in guess)  # ASCII only


def test_name_heuristic_long_slug_truncated() -> None:
    """A slug that would exceed 63 chars is suppressed (invalid hostname)."""
    long_name = "Superfantastisk og Ekstremt Lang Bedriftsnavn Ingeniørfirma AS"
    guess = _normalise_name_to_domain_guess(long_name)
    # Either None or has domain component ≤ 63 chars
    if guess is not None:
        label = guess.replace("https://", "").replace(".no", "")
        assert len(label) <= 63


# ── discover_candidates ───────────────────────────────────────────────────────

def test_discover_registered_url_is_first() -> None:
    """When a registered URL is provided it must be the first candidate."""
    candidates = discover_candidates(
        "810034882",
        "Sandnes Elektriske AS",
        registered_url="https://www.sandneselektriske.no",
        municipality="Sandnes",
        enable_news_rss=False,
    )
    assert candidates[0] == "https://www.sandneselektriske.no"


def test_discover_no_url_still_produces_candidates() -> None:
    """Even without a registered URL, the heuristic provides at least one candidate."""
    candidates = discover_candidates(
        "810034882",
        "Sandnes Elektriske AS",
        registered_url="",
        municipality="Sandnes",
        enable_news_rss=False,
    )
    assert len(candidates) >= 1


def test_discover_empty_name_with_no_url_returns_empty() -> None:
    """No name, no URL → empty candidate list (nothing to discover)."""
    from signalpost.discovery import _CANDIDATE_CACHE
    unique_org = "000000001"
    _CANDIDATE_CACHE.pop(unique_org, None)
    candidates = discover_candidates(
        unique_org,
        "",
        registered_url="",
        municipality="",
        enable_news_rss=False,
    )
    assert len(candidates) == 0


def test_discover_https_scheme_added_if_missing() -> None:
    """URL without scheme gets https:// prepended."""
    candidates = discover_candidates(
        "810034882",
        "Test AS",
        registered_url="www.test.no",
        municipality="",
        enable_news_rss=False,
    )
    assert candidates[0].startswith("https://")


def test_discover_caps_at_six_candidates() -> None:
    """At most 6 candidates are returned."""
    candidates = discover_candidates(
        "999999999",
        "Some Very Long Fancy Company Name Here Ltd AS",
        registered_url="https://example.no",
        municipality="Oslo",
        enable_news_rss=False,
    )
    assert len(candidates) <= 6


def test_discover_caches_results() -> None:
    """Repeated calls with same org return the exact same list object."""
    from signalpost.discovery import _CANDIDATE_CACHE
    org = "810034882"
    if org in _CANDIDATE_CACHE:
        del _CANDIDATE_CACHE[org]
    r1 = discover_candidates(org, "Sandnes Elektriske AS", registered_url="", enable_news_rss=False)
    r2 = discover_candidates(org, "Sandnes Elektriske AS", registered_url="", enable_news_rss=False)
    assert r1 is r2


# ── Google News RSS (network — skipped if no internet) ───────────────────────

def test_google_news_rss_returns_list() -> None:
    """Returns a list (may be empty if network unavailable); never raises."""
    result = _google_news_rss_candidates("Equinor ASA")
    assert isinstance(result, list)
    assert len(result) <= 5
