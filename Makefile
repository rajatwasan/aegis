SHELL := /bin/bash
VENV  := .venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip
RUFF  := $(VENV)/bin/ruff
PYTEST:= $(VENV)/bin/pytest

.PHONY: setup fmt lint test test-contracts test-python demo evals clean \
        frontend-setup frontend-dev frontend-build frontend-test dev

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.lock || $(PIP) install langgraph langchain-core fastapi uvicorn "pydantic>=2" "web3>=7" eth-account PyYAML cryptography httpx pytest pytest-cov ruff mcp
	$(PIP) install -e python/
	cd contracts && forge install

fmt:
	cd contracts && forge fmt
	$(RUFF) format python/

lint:
	cd contracts && forge fmt --check
	$(RUFF) check python/
	$(RUFF) format --check python/

test: test-contracts test-python frontend-test

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
