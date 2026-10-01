from __future__ import annotations

import hashlib
import heapq
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator

NORWEGIAN_ORG_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)


def normalise_organisation_number(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def valid_organisation_number(value: Any) -> bool:
    number = normalise_organisation_number(value)
    if len(number) != 9:
        return False
    remainder = sum(int(digit) * weight for digit, weight in zip(number[:8], NORWEGIAN_ORG_WEIGHTS)) % 11
    check_digit = 11 - remainder
    if check_digit == 11:
        check_digit = 0
    return check_digit != 10 and int(number[-1]) == check_digit


def iter_jsonl_rows(path: str | Path) -> Iterator[dict[str, Any]]:
    """Stream the kit's newline-delimited JSON pool despite its .json suffix."""
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            yield row


def classify_row(row: dict[str, Any]) -> set[str]:
    form = str(row.get("legal_form") or "").upper()
    employees = row.get("employees")
    website = str(row.get("website") or "").strip()
    adverse = bool(row.get("bankrupt") or row.get("liquidating"))
    categories = {"adverse" if adverse else "active"}
    if adverse:
        categories.add("bankrupt_or_dissolved")
    if form == "ENK":
        categories.add("sole_proprietorship")
    if employees is not None and int(employees) >= 100:
        categories.add("large")
    if not website:
        categories.add("no_website")
    # The public pool has no explicit dormant flag. This conservative proxy
    # identifies entities with no reported workforce and no registered website;
    # it never turns the proxy into a published company-status claim.
    if employees in (None, 0) and not website and not adverse:
        categories.add("dormant_proxy")
    return categories


def _row_with_normalised_org(row: dict[str, Any]) -> dict[str, Any] | None:
    org = normalise_organisation_number(row.get("organisation_number"))
    if not valid_organisation_number(org):
        return None
    return {**row, "organisation_number": org}


def scan_pool(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return unique valid rows; only the deduplicated valid pool is retained."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = invalid = duplicates = 0
    for raw in iter_jsonl_rows(path):
        total += 1
        row = _row_with_normalised_org(raw)
        if row is None:
            invalid += 1
            continue
        org = row["organisation_number"]
        if org in seen:
            duplicates += 1
            continue
        seen.add(org)
        rows.append(row)
    return rows, {
        "input_rows": total,
        "invalid_mod11_or_shape": invalid,
        "duplicate_organisation_numbers": duplicates,
        "valid_deduplicated_rows": len(rows),
    }


def _reservoir(rows: Iterable[dict[str, Any]], count: int, rng: random.Random) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if index < count:
            selected.append(row)
            continue
        replacement = rng.randrange(index + 1)
        if replacement < count:
            selected[replacement] = row
    return selected


def _stable_order(rows: Iterable[dict[str, Any]], seed: int, purpose: str) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: hashlib.sha256(
            f"{seed}:{purpose}:{row['organisation_number']}".encode("utf-8")
        ).hexdigest(),
    )


def _rank(seed: int, purpose: str, organisation_number: str) -> int:
    return int(hashlib.sha256(f"{seed}:{purpose}:{organisation_number}".encode("utf-8")).hexdigest(), 16)


def _offer_top(
    heap: list[tuple[int, str, dict[str, Any]]],
    row: dict[str, Any],
    count: int,
    seed: int,
    purpose: str,
) -> None:
    if count <= 0:
        return
    rank = _rank(seed, purpose, row["organisation_number"])
    item = (-rank, row["organisation_number"], row)
    if len(heap) < count:
        heapq.heappush(heap, item)
    elif rank < -heap[0][0]:
        heapq.heapreplace(heap, item)


def _rows_from_heap(heap: list[tuple[int, str, dict[str, Any]]], seed: int, purpose: str) -> list[dict[str, Any]]:
    rows = [item[2] for item in heap]
    return sorted(rows, key=lambda row: (_rank(seed, purpose, row["organisation_number"]), row["organisation_number"]))


def _stream_select(
    path: str | Path,
    *,
    profiles_count: int,
    daily_count: int,
    dev_count: int,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Select all manifests using bounded heaps; no nationwide row list is retained."""
    profile_heap: list[tuple[int, str, dict[str, Any]]] = []
    seen: set[str] = set()
    stats = {"input_rows": 0, "invalid_mod11_or_shape": 0, "duplicate_organisation_numbers": 0}
    for raw in iter_jsonl_rows(path):
        stats["input_rows"] += 1
        row = _row_with_normalised_org(raw)
        if row is None:
            stats["invalid_mod11_or_shape"] += 1
            continue
        org = row["organisation_number"]
        if org in seen:
            stats["duplicate_organisation_numbers"] += 1
            continue
        seen.add(org)
        _offer_top(profile_heap, row, profiles_count, seed, "profiles")
    profiles = _rows_from_heap(profile_heap, seed, "profiles-order")
    profile_orgs = {row["organisation_number"] for row in profiles}

    daily_heap: list[tuple[int, str, dict[str, Any]]] = []
    dev_fill_heap: list[tuple[int, str, dict[str, Any]]] = []
    required = ("active", "bankrupt_or_dissolved", "sole_proprietorship", "dormant_proxy", "large", "no_website")
    per_category = max(1, dev_count // len(required))
    category_heaps: dict[str, list[tuple[int, str, dict[str, Any]]]] = {category: [] for category in required}
    seen_second: set[str] = set()
    for raw in iter_jsonl_rows(path):
        row = _row_with_normalised_org(raw)
        if row is None:
            continue
        org = row["organisation_number"]
        if org in seen_second:
            continue
        seen_second.add(org)
        if org not in profile_orgs:
            _offer_top(daily_heap, row, daily_count, seed + 1, "daily")
        _offer_top(dev_fill_heap, row, dev_count, seed + 2, "dev-fill")
        categories = classify_row(row)
        for category in required:
            if category in categories:
                _offer_top(category_heaps[category], row, per_category, seed + 2, f"dev-{category}")

    daily = _rows_from_heap(daily_heap, seed + 1, "daily-order")
    chosen: dict[str, dict[str, Any]] = {}
    category_examples: dict[str, list[str]] = {}
    for category in required:
        category_rows = _rows_from_heap(category_heaps[category], seed + 2, f"dev-{category}-order")
        category_examples[category] = [row["organisation_number"] for row in category_rows]
        for row in category_rows:
            chosen[row["organisation_number"]] = row
    for row in _rows_from_heap(dev_fill_heap, seed + 2, "dev-fill-order"):
        if len(chosen) >= dev_count:
            break
        chosen[row["organisation_number"]] = row
    development = _stable_order(list(chosen.values())[:dev_count], seed + 2, "dev-order")
    for row in development:
        row["sample_categories"] = sorted(classify_row(row) & set(required))
        row["sample_slice"] = "stratified_dev"
        row["evaluation_split"] = "development"
    stats["valid_deduplicated_rows"] = len(seen)
    stats["bounded_selection"] = True
    return profiles, daily, development, {
        **stats,
        "required_categories": list(required),
        "unavailable_required_categories": [category for category, examples in category_examples.items() if not examples],
        "category_examples": category_examples,
    }


def stratified_dev_sample(rows: list[dict[str, Any]], count: int, seed: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = (
        "active",
        "bankrupt_or_dissolved",
        "sole_proprietorship",
        "dormant_proxy",
        "large",
        "no_website",
    )
    by_category: dict[str, list[dict[str, Any]]] = {category: [] for category in required}
    for row in rows:
        for category in classify_row(row) & set(required):
            by_category[category].append(row)

    per_category = max(1, count // len(required))
    chosen: dict[str, dict[str, Any]] = {}
    category_selection: dict[str, list[str]] = {}
    for offset, category in enumerate(required):
        candidates = _stable_order(by_category[category], seed + offset, category)
        selected = candidates[:per_category]
        category_selection[category] = [row["organisation_number"] for row in selected]
        for row in selected:
            chosen[row["organisation_number"]] = row

    remaining = [row for row in _stable_order(rows, seed, "dev-fill") if row["organisation_number"] not in chosen]
    for row in remaining[: max(0, count - len(chosen))]:
        chosen[row["organisation_number"]] = row

    selected = list(chosen.values())[:count]
    selected = _stable_order(selected, seed, "dev-order")
    for row in selected:
        row["sample_categories"] = sorted(classify_row(row) & set(required))
        row["sample_slice"] = "stratified_dev"
        row["evaluation_split"] = "development"
    return selected, {
        "requested": count,
        "selected": len(selected),
        "required_categories": list(required),
        "category_counts": dict(sorted(Counter(category for row in selected for category in row["sample_categories"]).items())),
        "category_examples": category_selection,
    }


def build_samples(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    seed: int = 20261001,
    profiles_count: int = 1500,
    daily_count: int = 100,
    dev_count: int = 60,
    kit_metadata_path: str | Path | None = None,
) -> dict[str, Any]:
    profiles, daily, dev, selection_report = _stream_select(
        input_path,
        profiles_count=profiles_count,
        daily_count=daily_count,
        dev_count=dev_count,
        seed=seed,
    )
    profile_orgs = {row["organisation_number"] for row in profiles}
    daily_orgs = {row["organisation_number"] for row in daily}
    for row in profiles:
        row["sample_slice"] = "profile_submission"
        row["evaluation_split"] = "submission"
    for row in daily:
        row["sample_slice"] = "daily_smoke"
        row["evaluation_split"] = "daily"
    dev_report = {
        "requested": dev_count,
        "selected": len(dev),
        **selection_report,
        "category_counts": dict(sorted(Counter(category for row in dev for category in row["sample_categories"]).items())),
    }

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for filename, selected in (
        ("profiles-1500.jsonl", profiles),
        ("daily-100.jsonl", daily),
        ("dev-stratified.jsonl", dev),
    ):
        with (output / filename).open("w", encoding="utf-8") as handle:
            for row in selected:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    report: dict[str, Any] = {
        "input": str(input_path),
        "seed": seed,
        "scan": {
            "input_rows": selection_report.pop("input_rows", None),
            "invalid_mod11_or_shape": selection_report.pop("invalid_mod11_or_shape", None),
            "duplicate_organisation_numbers": selection_report.pop("duplicate_organisation_numbers", None),
            "valid_deduplicated_rows": selection_report.pop("valid_deduplicated_rows", None),
            "bounded_selection": selection_report.pop("bounded_selection", None),
        },
        "kit_metadata": {},
        "samples": {
            "profiles": len(profiles),
            "daily": len(daily),
            "development": len(dev),
            "profile_daily_overlap": len(profile_orgs & daily_orgs),
        },
        "development": dev_report,
        "paths": {
            "profiles": str(output / "profiles-1500.jsonl"),
            "daily": str(output / "daily-100.jsonl"),
            "development": str(output / "dev-stratified.jsonl"),
        },
        "claim_boundary": "Samples are reproducible input manifests; no external company API is called by this script.",
    }
    if kit_metadata_path and Path(kit_metadata_path).exists():
        metadata = json.loads(Path(kit_metadata_path).read_text(encoding="utf-8"))
        report["kit_metadata"] = {
            "master_rows": metadata.get("master_rows"),
            "latest_year": metadata.get("latest_year"),
            "master_content_sha256": metadata.get("master_content_sha256"),
            "matches_kit_master_rows": metadata.get("master_rows") == report["scan"]["valid_deduplicated_rows"],
        }
    (output / "sampling-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
