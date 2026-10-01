from __future__ import annotations

import json
from pathlib import Path

from signalpost.sampling import build_samples, valid_organisation_number


def test_norwegian_mod11_validation() -> None:
    assert valid_organisation_number("810034882")
    assert not valid_organisation_number("810034883")
    assert not valid_organisation_number("123")


def test_sampling_is_reproducible_and_stratified(tmp_path: Path) -> None:
    rows = [
        {
            "organisation_number": "810034882",
            "name": "Active AS",
            "legal_form": "AS",
            "employees": 5,
            "bankrupt": False,
            "liquidating": False,
            "website": "",
        },
        {
            "organisation_number": "810034890",
            "name": "Large AS",
            "legal_form": "AS",
            "employees": 100,
            "bankrupt": False,
            "liquidating": False,
            "website": "large.no",
        },
        {
            "organisation_number": "810034904",
            "name": "Sole trader",
            "legal_form": "ENK",
            "employees": 0,
            "bankrupt": False,
            "liquidating": False,
            "website": "",
        },
        {
            "organisation_number": "810034912",
            "name": "Adverse AS",
            "legal_form": "AS",
            "employees": None,
            "bankrupt": True,
            "liquidating": False,
            "website": "",
        },
    ]
    source = tmp_path / "orgs.json"
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    first = build_samples(source, tmp_path / "one", profiles_count=3, daily_count=1, dev_count=4, seed=9)
    second = build_samples(source, tmp_path / "two", profiles_count=3, daily_count=1, dev_count=4, seed=9)
    assert first["scan"] == second["scan"]
    assert first["samples"] == second["samples"]
    assert first["samples"]["profile_daily_overlap"] == 0
