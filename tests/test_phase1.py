from __future__ import annotations

import json
import logging

from signalpost.logging import JsonFormatter, configure_logging


def test_structured_log_formatter_is_json() -> None:
    record = logging.LogRecord("signalpost", logging.INFO, __file__, 1, "hello", (), None)
    record.event = "phase1_smoke"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello"
    assert payload["event"] == "phase1_smoke"
    assert payload["level"] == "INFO"


def test_logging_configuration_installs_a_handler() -> None:
    configure_logging("WARNING")
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert root.handlers
