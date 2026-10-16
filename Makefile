SHELL := /bin/bash
VENV  := .venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip
RUFF  := $(VENV)/bin/ruff
PYTEST:= $(VENV)/bin/pytest

.PHONY: setup fmt lint test test-contracts test-python demo evals evals-check check clean \
        frontend-setup frontend-dev frontend-build frontend-lint frontend-test e2e dev

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.lock || $(PIP) install langgraph langchain-core fastapi uvicorn "pydantic>=2" "web3>=7" eth-account PyYAML cryptography httpx pytest pytest-cov ruff mcp webauthn
	$(PIP) install -e python/
	cd contracts && forge install

fmt:
	cd contracts && forge fmt
	$(RUFF) format python/

lint: frontend/node_modules
	cd contracts && forge fmt --check
	$(RUFF) check python/
	$(RUFF) format --check python/
	cd frontend && npm run lint && npm run typecheck

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

frontend-build: frontend/node_modules
	cd frontend && npm run build

frontend-lint: frontend/node_modules
	cd frontend && npm run lint && npm run typecheck

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

# The committed report must be what the harness produces on this commit
# (AGENTS.md T5): regenerate, then fail if anything but the run timestamp
# changed. When only the timestamp moved, the committed line is restored so a
# green check leaves the tree clean.
evals-check: evals
	git diff -I '^generated_at: ' --exit-code -- evals/report.md
	git checkout -- evals/report.md

# The single gate before every commit, push and pull request (AGENTS.md V1,
# appendix B). Stops at the first failure. `make e2e` runs separately when the
# console or an API route it calls changed (V5), because it needs a browser.
check: lint test-contracts test-python frontend-test frontend-build evals-check
	@echo "make check: green"

clean:
	rm -rf contracts/out contracts/cache .pytest_cache
	find python -name __pycache__ -type d -prune -exec rm -rf {} +
