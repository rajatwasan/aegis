SHELL := /bin/bash
VENV  := .venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip
RUFF  := $(VENV)/bin/ruff
PYTEST:= $(VENV)/bin/pytest

.PHONY: setup fmt lint test test-contracts test-python test-scripts demo evals clean \
        frontend-setup frontend-dev frontend-build frontend-test e2e dev

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.lock || $(PIP) install langgraph langchain-core fastapi uvicorn "pydantic>=2" "web3>=7" eth-account PyYAML cryptography httpx pytest pytest-cov ruff mcp webauthn
	$(PIP) install -e python/
	cd contracts && forge install

fmt:
	cd contracts && forge fmt
	$(RUFF) format python/

lint:
	cd contracts && forge fmt --check
	$(RUFF) check python/
	$(RUFF) format --check python/

test: test-contracts test-python frontend-test test-scripts

test-scripts:
	bash scripts/check_hygiene.sh
	bash scripts/tests/test_start_fallback.sh

coverage:
	$(PYTEST) python/tests -q --cov=aegis --cov-branch --cov-report=json:coverage.json
	$(PY) scripts/check_coverage.py coverage.json

test-contracts:
	cd contracts && forge test

test-python:
	$(PYTEST) python/tests -q

# ------------------------------------------------------------------ frontend

frontend-setup:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run lint && npm run build

frontend-test: frontend/node_modules
	cd frontend && npm test

frontend/node_modules:
	cd frontend && npm install

# Boots the full dev stack (anvil + API + vite) via Playwright's webServer,
# drives the HITL loop in a real Chrome, and tears everything down.
e2e: frontend/node_modules
	cd frontend && npm run e2e

# Runs the API and the vite dev server together in the FOREGROUND.
# Human-only convenience: never invoke from tests, CI, or automation.
dev:
	bash scripts/dev-stack.sh

demo:
	bash scripts/demo.sh

evals:
	$(PY) -m aegis.evals_harness || $(PY) evals/harness.py

clean:
	rm -rf contracts/out contracts/cache .pytest_cache
	find python -name __pycache__ -type d -prune -exec rm -rf {} +
