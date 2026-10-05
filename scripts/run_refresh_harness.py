"""Signalpost refresh harness — validates idempotent rerun and change detection.

Runs the pipeline twice on the same input and verifies zero spurious changes.

Usage:
    python scripts/run_refresh_harness.py \\
        --first-run out/final-profiles.jsonl \\
        --second-run out/final2-profiles.jsonl \\
        --output out/refresh-report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "kit/src")
sys.path.insert(0, "src")

from norway_company_agent.refresh import diff_profile


def _load_profiles(path: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            p = json.loads(line)
            index[p["organisation_number"]] = p
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-run", required=True)
    parser.add_argument("--second-run", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    first = _load_profiles(args.first_run)
    second = _load_profiles(args.second_run)
    common_orgs = set(first) & set(second)
    n = len(common_orgs)
    if n == 0:
        print("No common org numbers between runs", file=sys.stderr)
        sys.exit(1)

    # Fields that are legitimately volatile between runs (not meaningful data changes)
    VOLATILE_FIELDS = {
        "website.title",       # Dynamic page titles / A-B tests
        "website.description", # Dynamic meta descriptions
        "retrieved_at",        # Timestamp changes every run
        "run_metrics",         # Timing is never stable
        "_started_at",
        "_run_id",
        "content_sha256",      # May differ on dynamic pages
    }

    total_changes = 0
    false_changes = 0
    orgs_with_spurious: list[dict] = []

    for org in common_orgs:
        p1 = first[org]
        p2 = second[org]
        changes = diff_profile(p1, p2)
        real_changes = [c for c in changes if c.get("field") not in VOLATILE_FIELDS]
        total_changes += len(real_changes)
        if real_changes:
            false_changes += len(real_changes)
            orgs_with_spurious.append({
                "org": org,
                "changes": [c.get("field") for c in real_changes],
            })

    idempotent = false_changes == 0

    # Evidence completeness: all profiles have registry + financials
    evidence_ok = all(
        "registry" in (p.get("evidence") or {}) and
        "financials" in (p.get("evidence") or {})
        for p in second.values()
    )

    report = {
        "qualification_passed": idempotent and evidence_ok,
        "evidence_complete": evidence_ok,
        "idempotent_rerun": idempotent,
        "profiles_compared": n,
        "total_changes_detected": total_changes,
        "false_positive_changes": false_changes,
        "orgs_with_spurious_changes": orgs_with_spurious[:10],
        "volatile_fields_excluded": sorted(VOLATILE_FIELDS),
        "note": "Compared two sequential runs with the same inputs. Zero non-volatile changes = idempotent.",
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
