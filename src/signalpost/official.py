from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .models import Claim, CompanyEnvelope, Evidence, Operations, RunMetadata

BRREG_ENTITY = "https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
BRREG_ROLES = BRREG_ENTITY + "/roller"
BRREG_GROUP = "https://data.brreg.no/enhetsregisteret/api/konsernstruktur/{org}"
BRREG_SUBUNITS = "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=1000"
BRREG_ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap/{org}"
BRREG_ACCOUNT_YEARS = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/aar"
BRREG_ACCOUNT_PDF = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/{year}"

USER_AGENT = "signalpost/0.1 (+https://github.com/Nikil-logesh/HWR)"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RawResponse:
    status: int
    body: bytes
    headers: dict[str, str]
    retrieved_at: str
    error: str | None = None


@dataclass(frozen=True)
class CachedResponse:
    url: str
    status: int
    body: bytes
    headers: dict[str, str]
    retrieved_at: str
    content_sha256: str
    from_cache: bool
    revalidated: bool
    error: str | None = None


class SQLiteResponseCache:
    """Content-addressed response cache with HTTP validator metadata."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS http_cache (
                url TEXT PRIMARY KEY,
                status INTEGER NOT NULL,
                body BLOB NOT NULL,
                headers_json TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                etag TEXT,
                last_modified TEXT,
                updated_at TEXT,
                content_sha256 TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def get(self, url: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT status, body, headers_json, retrieved_at, etag, last_modified, updated_at, content_sha256 FROM http_cache WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None:
            return None
        return {
            "status": row[0],
            "body": bytes(row[1]),
            "headers": json.loads(row[2]),
            "retrieved_at": row[3],
            "etag": row[4],
            "last_modified": row[5],
            "updated_at": row[6],
            "content_sha256": row[7],
        }

    def put(self, url: str, response: RawResponse) -> None:
        digest = hashlib.sha256(response.body).hexdigest()
        headers = {key.lower(): value for key, value in response.headers.items()}
        updated_at = headers.get("last-modified") or headers.get("date") or response.retrieved_at
        self.connection.execute(
            """
            INSERT INTO http_cache(url, status, body, headers_json, retrieved_at, etag, last_modified, updated_at, content_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              status=excluded.status, body=excluded.body, headers_json=excluded.headers_json,
              retrieved_at=excluded.retrieved_at, etag=excluded.etag, last_modified=excluded.last_modified,
              updated_at=excluded.updated_at, content_sha256=excluded.content_sha256
            """,
            (
                url,
                response.status,
                response.body,
                json.dumps(headers, ensure_ascii=False, sort_keys=True),
                response.retrieved_at,
                headers.get("etag"),
                headers.get("last-modified"),
                updated_at,
                digest,
            ),
        )
        self.connection.commit()

    def delete(self, url: str) -> None:
        self.connection.execute("DELETE FROM http_cache WHERE url = ?", (url,))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


class OfficialClient:
    """Official registry/accounts client with conditional requests and provenance."""

    def __init__(
        self,
        cache: SQLiteResponseCache,
        *,
        timeout: float = 20.0,
        transport: Callable[[str, dict[str, str], float], RawResponse] | None = None,
    ):
        self.cache = cache
        self.timeout = timeout
        self.transport = transport or self._network_transport
        self.request_count = 0
        self.bytes_received = 0
        self.latencies_ms: list[int] = []

    @staticmethod
    def _network_transport(url: str, headers: dict[str, str], timeout: float) -> RawResponse:
        request = urllib.request.Request(url, headers=headers, method="GET")
        retrieved_at = utc_now()
        try:
            started = time.monotonic()
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                response_headers = {str(key): str(value) for key, value in response.headers.items()}
                return RawResponse(int(response.status), body, response_headers, retrieved_at)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            response_headers = {str(key): str(value) for key, value in exc.headers.items()}
            return RawResponse(int(exc.code), body, response_headers, retrieved_at, f"HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return RawResponse(0, b"", {}, retrieved_at, f"{type(exc).__name__}: {exc}")

    def get(self, url: str, *, revalidate: bool = True) -> CachedResponse:
        cached = self.cache.get(url)
        if cached and not revalidate:
            return CachedResponse(
                url,
                cached["status"],
                cached["body"],
                cached["headers"],
                cached["retrieved_at"],
                cached["content_sha256"],
                True,
                False,
            )
        headers = {
            "Accept": "application/json, application/hal+json",
            "User-Agent": USER_AGENT,
        }
        if cached:
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]
        started = time.monotonic()
        response = self.transport(url, headers, self.timeout)
        self.request_count += 1
        self.latencies_ms.append(int((time.monotonic() - started) * 1000))
        self.bytes_received += len(response.body)
        if response.status == 304 and cached:
            return CachedResponse(
                url,
                cached["status"],
                cached["body"],
                cached["headers"],
                response.retrieved_at,
                cached["content_sha256"],
                True,
                True,
            )
        if response.status == 410:
            self.cache.delete(url)
        elif response.status:
            self.cache.put(url, response)
        digest = hashlib.sha256(response.body).hexdigest()
        return CachedResponse(
            url,
            response.status,
            response.body,
            {key.lower(): value for key, value in response.headers.items()},
            response.retrieved_at,
            digest,
            False,
            False,
            response.error,
        )

    def get_json(self, url: str, *, revalidate: bool = True) -> tuple[CachedResponse, Any | None]:
        response = self.get(url, revalidate=revalidate)
        if response.status not in {200, 304}:
            return response, None
        try:
            return response, json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return CachedResponse(**{**response.__dict__, "error": "response is not valid JSON"}), None

    def fetch_modules(self, organisation_number: str, modules: set[str] | None = None) -> dict[str, CachedResponse]:
        modules = modules or {"registry", "roles", "group", "locations", "financials", "financial_history"}
        urls = {
            "registry": BRREG_ENTITY.format(org=organisation_number),
            "roles": BRREG_ROLES.format(org=organisation_number),
            "group": BRREG_GROUP.format(org=organisation_number),
            "locations": BRREG_SUBUNITS.format(org=organisation_number),
            "financials": BRREG_ACCOUNTS.format(org=organisation_number),
            "financial_history": BRREG_ACCOUNT_YEARS.format(org=organisation_number),
        }
        return {module: self.get(urls[module]) for module in modules if module in urls}


def _address(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result = dict(value)
    if isinstance(result.get("adresse"), list):
        result["adresse"] = ", ".join(str(item) for item in result["adresse"])
    return result


def normalize_entity(body: dict[str, Any]) -> dict[str, Any]:
    form = body.get("organisasjonsform") or {}
    industry = body.get("naeringskode1") or {}
    status = "adverse" if any(
        bool(body.get(field))
        for field in ("konkurs", "underAvvikling", "underTvangsavviklingEllerTvangsopplosning")
    ) else "active"
    return {
        "organisation_number": body.get("organisasjonsnummer"),
        "name": body.get("navn"),
        "legal_form": form.get("kode"),
        "legal_form_description": form.get("beskrivelse"),
        "employees": body.get("antallAnsatte"),
        "has_registered_employee_count": body.get("harRegistrertAntallAnsatte"),
        "bankrupt": body.get("konkurs"),
        "liquidating": body.get("underAvvikling"),
        "forced_liquidation": body.get("underTvangsavviklingEllerTvangsopplosning"),
        "status": status,
        "website": body.get("hjemmeside"),
        "industry_code": industry.get("kode"),
        "industry_label": industry.get("beskrivelse"),
        "business_address": _address(body.get("forretningsadresse")),
        "postal_address": _address(body.get("postadresse")),
        "municipality": (body.get("forretningsadresse") or {}).get("kommune"),
        "municipality_number": (body.get("forretningsadresse") or {}).get("kommunenummer"),
        "latest_submitted_accounts": body.get("sisteInnsendteAarsregnskap"),
        "founded_at": body.get("stiftelsesdato"),
        "registered_at": body.get("registreringsdatoEnhetsregisteret"),
        "phone": body.get("telefon"),
        "mobile": body.get("mobil"),
        "email": body.get("epostadresse"),
        "vat_registered": body.get("registrertIMvaregisteret"),
        "business_register_registered": body.get("registrertIForetaksregisteret"),
        "foundation_register_registered": body.get("registrertIStiftelsesregisteret"),
        "voluntary_register_registered": body.get("registrertIFrivillighetsregisteret"),
        "group_member": body.get("erIKonsern"),
        "raw": body,
    }


def normalize_financials(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, list):
        return []
    records = []
    for item in body[:10]:
        result = item.get("resultatregnskapResultat") or {}
        operating = result.get("driftsresultat") or {}
        income = operating.get("driftsinntekter") or {}
        equity_debt = item.get("egenkapitalGjeld") or {}
        equity = equity_debt.get("egenkapital") or {}
        debt = equity_debt.get("gjeldOversikt") or {}
        records.append({
            "record_id": item.get("id"),
            "account_type": item.get("regnskapstype"),
            "period": item.get("regnskapsperiode"),
            "currency": item.get("valuta"),
            "revenue": income.get("sumDriftsinntekter"),
            "operating_result": operating.get("driftsresultat"),
            "profit_before_tax": result.get("ordinaertResultatFoerSkattekostnad"),
            "annual_result": result.get("aarsresultat"),
            "assets": (item.get("eiendeler") or {}).get("sumEiendeler"),
            "equity": equity.get("sumEgenkapital"),
            "debt": debt.get("sumGjeld"),
        })
    return records


def _evidence_for(response: CachedResponse, source_class: str, *, claim_span: str | None = None, reporting_period: str | None = None) -> Evidence:
    return Evidence(
        id="ev-" + response.content_sha256[:20],
        source_url=response.url,
        source_class=source_class,
        retrieved_at=response.retrieved_at,
        content_sha256=response.content_sha256,
        claim_span=claim_span,
        reporting_period=reporting_period,
    )


def build_register_envelope(
    organisation_number: str,
    entity_response: CachedResponse,
    entity_body: dict[str, Any] | None,
    *,
    run_id: str = "register-local",
    started_at: str | None = None,
    completed_at: str | None = None,
    financial_response: CachedResponse | None = None,
    financial_body: Any | None = None,
) -> CompanyEnvelope:
    started_at = started_at or entity_response.retrieved_at
    completed_at = completed_at or utc_now()
    evidence: list[Evidence] = []
    claims: list[Claim] = []
    if entity_response.status == 200 and entity_body:
        normalized = normalize_entity(entity_body)
        snippet = json.dumps(entity_body, ensure_ascii=False, sort_keys=True)
        entity_evidence = _evidence_for(entity_response, "official_registry", claim_span=snippet[:4000])
        evidence.append(entity_evidence)
        for field, value in normalized.items():
            if field == "raw" or value is None or value == "":
                continue
            claims.append(Claim(field=f"registry.{field}", value=value, availability="available", confidence=1.0, evidence_ids=[entity_evidence.id]))
    else:
        error = "Official entity record was not returned"
        if entity_response.error:
            error += f": {entity_response.error}"
        return CompanyEnvelope(
            organisation_number=organisation_number,
            run=RunMetadata(run_id=run_id, started_at=started_at, completed_at=completed_at, terminal_status="completed"),
            errors=[{"source": "official_registry", "message": error, "availability": "not_available"}],
            operations=Operations(requests=1, runtime_ms=0),
        )

    if financial_response is not None:
        records = normalize_financials(financial_body)
        financial_evidence = _evidence_for(financial_response, "official_annual_accounts", claim_span=json.dumps(financial_body, ensure_ascii=False)[:4000])
        evidence.append(financial_evidence)
        if financial_response.status == 200 and records:
            for index, record in enumerate(records):
                period = (record.get("period") or {}).get("tilDato") if isinstance(record.get("period"), dict) else None
                for field, value in record.items():
                    if value is None or value == "":
                        continue
                    claims.append(Claim(field=f"financials.{index}.{field}", value=value, availability="available", confidence=1.0, evidence_ids=[financial_evidence.id]))
        elif financial_response.status in {404, 410}:
            claims.append(Claim(field="financials", value=None, availability="not_available", confidence=1.0, evidence_ids=[financial_evidence.id]))

    return CompanyEnvelope(
        organisation_number=organisation_number,
        run=RunMetadata(run_id=run_id, started_at=started_at, completed_at=completed_at, terminal_status="completed"),
        claims=claims,
        evidence=evidence,
        operations=Operations(requests=1 + (1 if financial_response else 0), runtime_ms=0),
    )
