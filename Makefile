PYTHON ?= python3

.PHONY: traces traces-check

traces:
	$(PYTHON) scripts/regen_traces.py

traces-check:
	$(PYTHON) scripts/regen_traces.py --check
