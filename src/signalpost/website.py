"""Signalpost website fetcher and identity gate.

Fetches a candidate website URL, applies the kit's identity gate, and
returns an evidence record. Never uses an LLM.

Identity gate (kit identity.py rules):
  score 1.0  → org number in page text
  score 0.95 → all name tokens in homepage identity text
  score 0.85 → ≥75% name tokens (review)
  score < 0.9 → not publishable (quarantine)
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

USER_AGENT = "signalpost/0.1 (+https://github.com/Nikil-logesh/HWR)"
MAX_BYTES = 512_000   # 512 KB per page
TIMEOUT = 12.0        # seconds per request
_ROBOTS_CACHE: dict[str, bool] = {}  # host → robots_allow_root


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_private_ip(hostname: str) -> bool:
    """Block private/loopback/link-local ranges."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return False  # hostname, not raw IP


def _safe_url(url: str) -> str | None:
    """Return url if safe, else None."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    host = parsed.hostname or ""
    if not host or _is_private_ip(host):
        return None
    return url


def _check_robots(base_url: str) -> bool:
    """Return True if root path is allowed by robots.txt (simple check, cached)."""
    try:
        parsed = urllib.parse.urlparse(base_url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host in _ROBOTS_CACHE:
            return _ROBOTS_CACHE[host]
        robots_url = f"{host}/robots.txt"
        req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT}, method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            text = resp.read(16_384).decode("utf-8", errors="replace")
        # Very basic check: look for Disallow: / for * or our agent
        disallow_root = bool(re.search(r"(?i)Disallow\s*:\s*/\s*$", text, re.MULTILINE))
        _ROBOTS_CACHE[host] = not disallow_root
        return not disallow_root
    except Exception:
        _ROBOTS_CACHE[base_url] = True  # allow on error
        return True


def _fetch_url(url: str) -> tuple[int, bytes, str, str, str]:
    """Fetch url → (status, body, final_url, retrieved_at, sha256)."""
    safe = _safe_url(url)
    if not safe:
        return 0, b"", url, _utc_now(), _sha256(b"")
    req = urllib.request.Request(safe, headers={"User-Agent": USER_AGENT}, method="GET")
    retrieved_at = _utc_now()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(MAX_BYTES)
            return resp.status, body, resp.url, retrieved_at, _sha256(body)
    except urllib.error.HTTPError as exc:
        body = exc.read(4096) if exc.readable() else b""
        return exc.code, body, url, retrieved_at, _sha256(body)
    except Exception:
        return 0, b"", url, retrieved_at, _sha256(b"")


def _extract_text(body: bytes) -> str:
    """Best-effort plain text extraction from HTML."""
    try:
        import trafilatura
        text = trafilatura.extract(body, include_links=False, include_images=False, include_tables=True)
        return text or ""
    except Exception:
        pass
    # Fallback: strip tags
    try:
        text = body.decode("utf-8", errors="replace")
        return re.sub(r"<[^>]+>", " ", text)[:8000]
    except Exception:
        return ""


def _extract_structured(body: bytes, base_url: str) -> list[dict]:
    """Extract JSON-LD / OpenGraph structured data."""
    try:
        import extruct
        data = extruct.extract(body, base_url=base_url, syntaxes=["json-ld", "opengraph"], uniform=True)
        return data.get("json-ld", []) + data.get("opengraph", [])
    except Exception:
        return []


def _score_identity(
    org_number: str,
    legal_name: str | None,
    page_text: str,
    structured: list[dict],
    final_url: str,
    *,
    brreg_registered: bool = False,
) -> tuple[float, list[str]]:
    """Deterministic identity scoring. Returns (score, reasons)."""
    import unicodedata

    def tokens(text: str) -> list[str]:
        SKIP = {"as", "asa", "ans", "da", "enk", "sa", "the", "og", "and", "b", "v"}
        text = text.translate(str.maketrans({"ø": "o", "Ø": "O", "å": "a", "Å": "A", "æ": "ae", "Æ": "AE"}))
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
        return [t for t in re.findall(r"[a-z0-9]+", text) if t not in SKIP and len(t) > 1]

    org_digits = re.sub(r"\D", "", org_number)
    compact_text = re.sub(r"\D", "", page_text + " ".join(str(s) for s in structured))
    text_lower = page_text.lower() + " " + final_url.lower()
    structured_text = " ".join(str(item) for item in structured)

    # Rule 0: BRREG-registered URL is authoritative (hjemmeside field = official company declaration)
    if brreg_registered:
        return 0.97, ["URL from BRREG official hjemmeside field — company self-declared, state-authoritative"]

    # Rule 1: org number present
    if org_digits and len(org_digits) == 9 and org_digits in compact_text:
        return 1.0, ["exact organisation number appears in page content"]

    if not legal_name:
        return 0.3, ["no legal name to match"]

    core = tokens(legal_name)
    candidate_tokens = set(tokens(text_lower + " " + structured_text))
    overlap = sorted(set(core) & candidate_tokens)
    ratio = len(overlap) / len(set(core)) if core else 0.0

    hostname = urllib.parse.urlparse(final_url).hostname or ""
    domain_tokens = set(tokens(hostname))
    domain_overlap = set(core) & domain_tokens

    # Rule 2: all name tokens in hostname
    if core and set(core).issubset(domain_tokens):
        return 0.95, ["all legal-name tokens appear in domain"]

    # Rule 3: all name tokens in text
    if len(core) >= 2 and set(core).issubset(candidate_tokens):
        return 0.95, ["all legal-name tokens appear in page text"]

    # Rule 4: single strong token + substantive content
    if len(core) == 1 and overlap and len(page_text.strip()) >= 100:
        return 0.95, ["single distinctive token in page with substantive content"]

    # Rule 5: partial overlap
    if ratio >= 0.75 and len(overlap) >= 2:
        return 0.85, [f"partial name overlap: {overlap}"]

    if ratio >= 0.5 and len(overlap) >= 2:
        return 0.65, [f"weak name overlap: {overlap}"]

    return 0.3, ["insufficient identity evidence"]


def fetch_and_gate_website(
    url: str | None,
    registry_profile: dict[str, Any],
    *,
    brreg_registered: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch a website candidate and apply the identity gate.

    brreg_registered=True when the URL came from the BRREG hjemmeside field;
    this makes the identity gate accept the page as authoritative (score=0.97).

    Returns:
        (evidence_record, metrics)
    """
    metrics: dict[str, Any] = {"requests": 0, "bytes": 0, "latencies_ms": []}

    def _not_available(reason: str) -> dict[str, Any]:
        return {
            "status": "not_available",
            "source_url": url or "",
            "source_class": "company_owned",
            "note": reason,
            "retrieved_at": _utc_now(),
            "content_sha256": _sha256(b""),
        }

    def _blocked(reason: str) -> dict[str, Any]:
        return {
            "status": "blocked",
            "source_url": url or "",
            "source_class": "company_owned",
            "note": reason,
            "retrieved_at": _utc_now(),
            "content_sha256": _sha256(b""),
        }

    if not url or not url.strip():
        return _not_available("no website URL registered"), metrics

    # Normalise URL
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    safe = _safe_url(url)
    if not safe:
        return _blocked("unsafe URL (private IP or unsupported scheme)"), metrics

    # Robots check
    if not _check_robots(url):
        return _blocked("robots.txt disallows crawling"), metrics

    # Fetch homepage
    t0 = time.monotonic()
    status, body, final_url, retrieved_at, sha256 = _fetch_url(url)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    metrics["requests"] += 1
    metrics["bytes"] += len(body)
    metrics["latencies_ms"].append(elapsed_ms)

    if status == 0:
        return _blocked("connection error or timeout"), metrics

    if status in {403, 429}:
        return _blocked(f"HTTP {status}"), metrics

    if status not in {200, 301, 302, 303, 307, 308}:
        return {
            "status": "source_error",
            "source_url": url,
            "source_class": "company_owned",
            "note": f"HTTP {status}",
            "retrieved_at": retrieved_at,
            "content_sha256": sha256,
        }, metrics

    # Extract content
    page_text = _extract_text(body)
    structured = _extract_structured(body, final_url)

    # Identity gate
    org_number = registry_profile.get("organisation_number", "")
    legal_name = registry_profile.get("name")
    score, reasons = _score_identity(
        org_number, legal_name, page_text, structured, final_url,
        brreg_registered=brreg_registered,
    )
    publishable = score >= 0.9

    identity_assessment = {
        "score": score,
        "publishable": publishable,
        "status": "exact" if score >= 0.9 else "review" if score >= 0.8 else "related_or_uncertain",
        "reasons": reasons,
        "method": "signalpost_deterministic_v1",
    }

    if not publishable:
        return {
            "status": "ambiguous",
            "source_url": url,
            "final_url": final_url,
            "source_class": "company_owned",
            "note": f"identity gate failed (score={score:.2f}): {'; '.join(reasons)}",
            "retrieved_at": retrieved_at,
            "content_sha256": sha256,
            "value": {
                "identity_assessment": identity_assessment,
                "title": page_text[:200] if page_text else None,
            },
        }, metrics

    # Extract additional pages (about, contact, careers)
    pages: list[dict] = []
    extra_paths = ["/om-oss", "/about", "/kontakt", "/contact", "/karriere", "/jobs", "/news", "/nyheter"]
    base = f"{urllib.parse.urlparse(final_url).scheme}://{urllib.parse.urlparse(final_url).netloc}"
    for path in extra_paths[:4]:  # limit extra pages to 4
        if metrics["requests"] >= 12:  # stay within budget
            break
        extra_url = base + path
        t1 = time.monotonic()
        s2, b2, fu2, ra2, sha2 = _fetch_url(extra_url)
        metrics["requests"] += 1
        metrics["bytes"] += len(b2)
        metrics["latencies_ms"].append(int((time.monotonic() - t1) * 1000))
        if s2 == 200 and b2:
            pages.append({
                "url": extra_url,
                "final_url": fu2,
                "path": path,
                "text": _extract_text(b2)[:2000],
                "retrieved_at": ra2,
                "content_sha256": sha2,
            })

    return {
        "status": "available",
        "source_url": url,
        "final_url": final_url,
        "source_class": "company_owned",
        "retrieved_at": retrieved_at,
        "content_sha256": sha256,
        "value": {
            "title": page_text[:200],
            "main_text_excerpt": page_text[:2000],
            "structured_data": structured[:5],
            "identity_assessment": identity_assessment,
            "pages": pages,
        },
    }, metrics
