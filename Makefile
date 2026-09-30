.PHONY: test lint run

PYTHON ?= python

# The kit remains the authoritative evaluator interface. This target is the
# local project entry point and delegates to the Signalpost CLI.
test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check src tests

run:
	$(PYTHON) -m signalpost.cli --input "$(INPUT)" --output "$(OUT)"
