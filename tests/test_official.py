from __future__ import annotations

import json
from pathlib import Path

from signalpost.models import CompanyEnvelope
from signalpost.official import (
    BRREG_ENTITY,
    CachedResponse,
    OfficialClient,
    RawResponse,
    SQLiteResponseCache,
    build_register_envelope,
    normalize_entity,
    normalize_financials,
)


FIXTURE = Path(__file__).parent / "fixtures" / "official-entities-10.json"


def test_recorded_register_fixture_covers_ten_profiles() -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(rows) == 10
    for row in rows:
        normalized = normalize_entity(row)
        envelope = build_register_envelope(
            normalized["organisation_number"],
            CachedResponse(
                url=BRREG_ENTITY.format(org=normalized["organisation_number"]),
                status=200,
                body=json.dumps(row, ensure_ascii=False).encode(),
                headers={"etag": '"fixture"'},
                retrieved_at="2026-10-01T00:00:00Z",
                content_sha256="a" * 64,
                from_cache=False,
                revalidated=False,
            ),
            row,
        )
        assert isinstance(envelope, CompanyEnvelope)
        assert envelope.organisation_number == normalized["organisation_number"]
        assert any(claim.field == "registry.name" for claim in envelope.claims)
        assert envelope.evidence[0].source_url.endswith(normalized["organisation_number"])


def test_financial_normalizer_preserves_zero_and_period() -> None:
    records = normalize_financials([
        {
            "id": 1,
            "regnskapstype": "SELSKAP",
            "valuta": "NOK",
            "regnskapsperiode": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"},
            "resultatregnskapResultat": {
                "driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 0}, "driftsresultat": 0},
                "aarsresultat": 0,
            },
            "eiendeler": {"sumEiendeler": 0},
            "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": 0}, "gjeldOversikt": {"sumGjeld": 0}},
        }
    ])
    assert records[0]["revenue"] == 0
    assert records[0]["operating_result"] == 0
    assert records[0]["period"]["tilDato"] == "2025-12-31"


def test_conditional_cache_uses_etag_and_reuses_304_body(tmp_path: Path) -> None:
    calls: list[dict[str, str]] = []

    def transport(url: str, headers: dict[str, str], timeout: float) -> RawResponse:
        calls.append(headers)
        if len(calls) == 1:
            return RawResponse(200, b'{"value": 1}', {"ETag": '"v1"'}, "2026-10-01T00:00:00Z")
        return RawResponse(304, b"", {}, "2026-10-02T00:00:00Z")

    cache = SQLiteResponseCache(tmp_path / "cache.sqlite3")
    client = OfficialClient(cache, transport=transport)
    first = client.get("https://data.brreg.no/example")
    second = client.get("https://data.brreg.no/example")
    assert first.status == 200
    assert second.status == 200
    assert second.body == first.body
    assert second.revalidated is True
    assert calls[1]["If-None-Match"] == '"v1"'
    assert client.request_count == 2
    cache.close()
