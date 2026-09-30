from __future__ import annotations

import argparse

from .logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Signalpost Norwegian company profile agent")
    parser.add_argument("--input", required=True, help="JSONL, JSON, or text organisation-number batch")
    parser.add_argument("--output", required=True, help="Output directory or JSONL path")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(args.log_level)
    # Phase 1 intentionally exposes the stable command shape before the
    # register pipeline is connected. Later phases replace this message with
    # terminal envelopes while retaining the same arguments.
    raise SystemExit("Signalpost pipeline is not implemented yet; Phase 1 shell only")


if __name__ == "__main__":
    main()
