PYTHON ?= python3

.PHONY: traces traces-check pages pages-check

traces:
	$(PYTHON) scripts/regen_traces.py

traces-check:
	$(PYTHON) scripts/regen_traces.py --check

pages:
	rm -rf site
	mkdir -p site
	PYTHONPATH=src $(PYTHON) -m funcviz.cli view traces/invocation-fail.json --html-out site/index.html
	touch site/.nojekyll

pages-check: pages
	test -s site/index.html
	test "$$(grep -c 'id="funcviz-default-trace"' site/index.html)" -eq 1
