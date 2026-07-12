# PROGRESS.md — Aegis build log

Work proceeds milestone by milestone per PROMPT.md. Check boxes only when the
milestone's acceptance criteria pass locally.

## Milestones

- [x] M0 — Scaffold: layout, Makefile, .venv, foundry init, CI authored, README skeleton; `make test` trivially green
- [x] M1 — Contracts core: ComplianceRegistry, GuardianModule, GuardedToken, GuardedAsset1155, AuditAnchor; forge tests green, fmt clean
- [x] M2 — Policy engine: evaluate() with YAML rules, default policy, property tests, 100% branch coverage on evaluator
- [x] M3 — Audit log: hash-chained JSONL, Ed25519 signatures, MerkleTree with proofs, tamper test
- [x] M4 — Approval service: FastAPI HITL, idempotency, TTL expiry, dual-control flag, guardian EIP-712 signer, HTML approval page
- [x] M5 — Agent: LangGraph graph, typed tools, MockLLM/AnthropicLLM, anvil integration test (5 transfers + freeze deny)
- [x] M6 — Adversarial evals: 50+ injection corpus, gullible-mode harness, report with bypass rate 0
- [x] M7 — MCP server: stdio server with 4 tools, protocol smoke test
- [x] M8 — Verify CLI, demo.sh, docs (architecture, threat model, README); `make demo` exits 0

## Session notes

(appended per milestone)

**M0 (2026-07-09):** Scaffolded full layout, Makefile (setup/fmt/lint/test/demo),
.venv with pinned stack frozen to requirements.lock, foundry init + OZ pinned to
v5.1.0 (ADR 001 — local forge 0.2.0 panics on OZ v5.6.1's `osaka` evm_version),
CI workflow authored. `make test` green (forge sample + pytest smoke).

**M1 (2026-07-09):** ComplianceRegistry (expiring claims), GuardianModule
(EIP-712 "AegisGuardian"/"1", single-use decisionIds, rotation, freeze via
authorization), GuardedToken (threshold + compliance gates, authorized
transfer/mint/burn), GuardedAsset1155 (per-class thresholds), AuditAnchor.
50 forge tests green incl. fuzz + invariant (no gated transfer without a
consumed authorization); forge fmt clean. Design choice: frozen blocks even
guardian-authorized moves (must unfreeze first).

**M2 (2026-07-09):** Pure evaluate(proposal, context, policy) -> Decision with
frozen pydantic models; YAML rules with structural match (operation/token/
asset class) + predicates (amount ceiling/floor, allowlist, daily rate limit,
compliance, frozen); first-match-wins with explicit default. Default policy
ships allow-small/escalate-large-or-unknown/deny-frozen. 31 tests green;
100% branch coverage on aegis/policy/engine.py verified with pytest-cov.

**M3 (2026-07-09):** Canonical-JSON hash-chained JSONL AuditLog with Ed25519
signatures (key auto-generated 0600 into git-ignored file; deterministic test
keypair committed under tests/fixtures). MerkleTree: sha256, sorted pairs,
duplicate-last-for-odd, flag-free proofs. Tamper tests: mutate/delete middle
record and hash-fixup-without-key all fail verification. 63 tests green.

**M4 (2026-07-09):** FastAPI approval service: POST/GET /proposals with
Idempotency-Key, approve/reject with approver+comment, lazy TTL sweep
(auto-reject as "expired" + audit record), dual-control flag, sqlite3 stdlib
store with nonce counter, GuardianSigner (eth-account EIP-712 over the exact
GuardianModule struct; decisionId = sha256(decision_id string)), single-file
HTML approval page. 83 tests green incl. idempotent resubmission and expiry.

**M5 (2026-07-09):** LangGraph supervisor->act->await_approval graph with
interrupt/resume (MemorySaver checkpointer); typed tool registry rejects
unknown tools/bad args; ChainClient (web3 v7, EIP-1559, deploys from forge
artifacts); AegisRuntime gates every proposal and audits every decision;
MockLLM (scripted + gullible mode for M6) and optional AnthropicLLM. E2E on
anvil: 4 auto-allowed transfers executed, 1 escalated->approved->guardian-sig
executed, frozen-address transfer denied, 8 audit records verify. 97 py tests.

**M6 (2026-07-11):** evals/corpus.yaml with 51 injection attempts across 11
families (instruction-override, tool-schema-smuggling, role-confusion, social-
engineering, unicode-obfuscation, many-shot, destination-evasion, rate-limit,
replay, confused-deputy, prompt-leak). evals/harness.py spawns anvil, deploys
the suite, and runs every case through the graph with a gullible MockLLM that
OBEYS the injected action; no escalation is ever approved. All 49 attacks end
escalated/denied/refused, the 2 legit compliant transfers execute. Bypass rate
0 (0/49), escalation precision 100% (42/42), denial recall 100% (1/1); report
written to evals/report.md. Wired into pytest (test_evals.py) so `make test`
also proves the guarantee. `make evals` exits 0.

**M7 (2026-07-11):** aegis.mcpserver stdio server (official mcp sdk, low-level
Server API) exposing propose_transfer, get_proposal_status, list_pending,
get_audit_proof. AegisBackend wraps the same AegisRuntime + in-process approval
service (shared sqlite) + audit log, so MCP clients hit the identical policy
gate — gated moves escalate to a human, never auto-execute. Config from AEGIS_*
env (rpc, token/registry addresses, keys, paths). Smoke test launches the
server as a real subprocess and speaks MCP over stdio: lists 4 tools, executes
a small compliant transfer, escalates a large one, reads the pending queue and
status, and verifies a Merkle audit proof.

**M8 (2026-07-11):** aegis CLI (pyproject console_script) with `anchor` (batch
unanchored audit records, sha256 Merkle root, anchor on-chain via AuditAnchor)
and `verify <id>` / `verify --all` (recompute record hash, rebuild Merkle proof,
fetch batch root over RPC, print PROOF OK/FAIL; tamper detection). aegis.demo
runs the M5 scenario on an anvil owned by scripts/demo.sh, auto-approves the
escalation, writes state.json, then the script anchors and verifies with a
narrative — `make demo` exits 0. CLI tests (anchor/verify/tamper) in pytest.
Docs: architecture.md (mermaid component + sequence diagrams, trust-boundary
table), threat-model.md (assets, boundaries, 12-row STRIDE table, malicious-LLM
+ prompt-injection in scope, residual risks), README rewrite (what/why,
90-second quickstart, design highlights, eval results). Full suite green: 50
forge tests + 104 py tests; ruff + forge fmt clean.

ALL_MILESTONES_COMPLETE

## Frontend milestones (FRONTEND.md)

- [x] F0 — Backend API surface: CORS, event bus + SSE, decisions/audit/policy/metrics endpoints, /agent/run
- [x] F1 — Frontend scaffold: Vite + React 18 + TS strict, typed client, Makefile + CI wiring
- [ ] F2 — Approvals queue
- [ ] F3 — Activity feed + Audit explorer
- [ ] F4 — Command console + dashboard
- [ ] F5 — E2E, docs, polish

## Frontend session notes

**F0 (2026-07-12):** EventBus (thread-safe pub/sub -> asyncio SSE consumers) in
aegis.events; approval service now emits proposal.* events and decision.recorded
via EmittingAuditLog (routes unchanged). Anchor/verify refactored from the CLI
into aegis.anchoring (CLI output byte-identical). New aegis.api package:
GET /events (SSE), /decisions, /audit/records[/{id}], /audit/verify/{id},
/policy (yaml + hash + human-readable rules), /metrics (effects, escalation
rate, pending, last anchor, blocked injections from evals/report.md),
POST /anchor (emits anchor.created), POST /agent/run (canned MockLLM plans,
agent.step events, poll-resume on approval), GET /agent/instructions.
ADR 002 records the spec->code mapping. 24 new tests incl. a real-uvicorn SSE
consumption test; suite 50 forge + 128 py, ruff clean, zero existing tests
modified.

**F1 (2026-07-12):** frontend/ scaffold: Vite + React 18 + TS strict, Tailwind v4
tokens (dark control-room palette, Inter + JetBrains Mono via fontsource),
React Router shell (left nav, top StatusBar with SSE-live chain/anchor/pending),
TanStack Query, typed client from committed openapi.json snapshot
(scripts/gen_openapi.py + `npm run gen:api`), EventsProvider wrapping a
reconnecting EventSource. /metrics gained a ChainStatus block (live eth_chainId
probe) for the status bar. Makefile: frontend-{setup,dev,build,test} + `dev`
(scripts/dev-stack.sh: anvil + aegis.devstack deploy + uvicorn + vite,
human-only foreground); `make test` now includes frontend-test. CI node job
(lint, typecheck, test, build). 14 vitest tests (format utils, shell + status
bar via MSW); full suite 50 forge + 128 py + 14 fe, ruff + eslint clean.
