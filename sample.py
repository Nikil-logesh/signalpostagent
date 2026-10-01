#!/usr/bin/env python3
"""Build deterministic local manifests from data/orgs.json without network calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from signalpost.sampling import build_samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/orgs.json")
    parser.add_argument("--output-dir", default="out/samples")
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--profiles-count", type=int, default=1500)
    parser.add_argument("--daily-count", type=int, default=100)
    parser.add_argument("--dev-count", type=int, default=60)
    parser.add_argument("--kit-metadata", default="kit/data/universe-metadata.json")
    args = parser.parse_args()
    if args.profiles_count < 1000:
        parser.error("--profiles-count must be at least 1000")
    report = build_samples(
        args.input,
        args.output_dir,
        seed=args.seed,
        profiles_count=args.profiles_count,
        daily_count=args.daily_count,
        dev_count=args.dev_count,
        kit_metadata_path=args.kit_metadata,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
