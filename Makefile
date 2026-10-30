# Pareeksha: `make demo` (start, seed, run a 10-call demo) and `make verify` (GOAL.md acceptance V1..V11).
# Behind a TLS-intercepting proxy: COMPOSE="docker compose -f docker-compose.yml -f docker-compose.proxy.yml" CA_BUNDLE=...
SHELL := /bin/bash
export COMPOSE ?= docker compose

.PHONY: demo verify verify-step lint test

demo:
	scripts/demo.sh

# Runs V1..V11 in order, writes proof/FINAL_REPORT.md, exits non-zero unless every step PASSes.
# One step: make verify-step N=4
verify:
	scripts/verify/run_all.sh

verify-step:
	scripts/verify/run_all.sh $(N)

lint:
	cd backend && ruff check . && ruff format --check . && mypy
	cd web && npm run lint && npx tsc --noEmit

test:
	cd backend && python3 -m pytest tests/unit tests/evaluation tests/judge tests/contract -q
