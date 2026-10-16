# PROMPT.md - Aegis mission spec

Read CLAUDE.md first. It overrides this file wherever they conflict.

## What you are building

Aegis: a reference implementation proving that human-in-the-loop control over
AI agents can be enforced cryptographically at the smart-contract layer rather
than promised at the application layer. An LLM agent proposes token operations;
a deterministic policy engine allows, denies, or escalates; escalations pause
the agent via LangGraph interrupt until a human approves; approved high-risk
operations execute on-chain ONLY with an EIP-712 authorization co-signed by a
guardian key held by the approval service. Every decision lands in a
hash-chained audit log whose Merkle roots are anchored on-chain, and a CLI can
prove any single decision's inclusion. The agent, even fully prompt-injected,
cannot move gated assets: the chain refuses without the guardian signature.

One repo. Fully local. Anvil as the chain. No external services. The only
optional external dependency is a real LLM key, and nothing in the test suite
or demo requires it.

## Repository layout (create in M0)

    aegis/
    ├── contracts/            # Foundry project (src/, test/, script/)
    ├── python/aegis/         # single installable package
    │   ├── policy/           # deterministic rules engine
    │   ├── audit/            # hash-chained log, merkle, signing
    │   ├── approval/         # FastAPI HITL service + guardian signer
    │   ├── agent/            # LangGraph graph, tools, llm providers
    │   └── mcpserver/        # MCP stdio server exposing the runtime
    ├── python/tests/
    ├── evals/                # injection corpus + harness + report
    ├── policies/default.yaml
    ├── scripts/demo.sh
    ├── docs/  (architecture.md, threat-model.md, adr/)
    ├── .github/workflows/ci.yml
    ├── Makefile  docker-compose.yml  .env.example
    ├── PROGRESS.md  BLOCKERS.md  README.md  LICENSE (MIT)

## Core protocol (implement exactly)

EIP-712 domain: name "AegisGuardian", version "1", chainId, verifyingContract.

    struct Authorization {
        bytes32 decisionId;   // links on-chain execution to audit record
        uint8   operation;    // 1 TRANSFER, 2 MINT, 3 BURN, 4 FREEZE
        address token;
        address from;
        address to;
        uint256 id;           // asset class; 0 for the ERC20 token
        uint256 amount;
        bytes32 policyHash;   // sha256 of the exact policy file version
        uint256 nonce;
        uint256 deadline;
    }

Rules: signer must be the current guardian; decisionId single-use; deadline
enforced; every struct field must match the actual call parameters; consuming
emits AuthorizationConsumed(decisionId, operation, from, to, id, amount).

## Milestones

### M0 - Scaffold
Layout above; Makefile targets `setup`, `fmt`, `lint`, `test`, `demo`;
`.venv` bootstrap; foundry init under contracts/; PROGRESS.md with this
milestone checklist; CI workflow (foundry-toolchain + pytest) authored, not run;
README skeleton. Accept: `make test` runs both suites (trivially green).

### M1 - Contracts core
`ComplianceRegistry` (AccessControl; set/get boolean claims with expiry per
address per bytes32 topic; `isCompliant(addr)` convenience).
`GuardianModule` (abstract: EIP712 setup, guardian rotation by admin,
consumed-decisionId set, `_consumeAuthorization(auth, sig, expectedFields...)`).
`GuardedToken` (ERC20 + GuardianModule): transfers where
`amount > threshold` OR either party non-compliant revert with
`GuardianRequired()`; `transferWithAuthorization(auth, sig)` executes after
consumption; `mintWithAuthorization`; `setFrozen` via authorization only.
`GuardedAsset1155` (ERC1155 + GuardianModule): per-id thresholds, same gates
on `safeTransferFrom`.
`AuditAnchor`: `anchor(bytes32 root, uint256 batchId)` by ANCHOR_ROLE, mapping
+ event.
Foundry tests: happy paths; reverts for wrong signer, expired deadline, replayed
decisionId, field mismatch; fuzz nonce/amount/deadline; invariant test that no
gated transfer ever succeeds without a consumed authorization.
Accept: `forge test` green, `forge fmt --check` clean.

### M2 - Policy engine (python)
Pure function `evaluate(proposal, context) -> Decision` where Decision carries
effect (ALLOW | DENY | ESCALATE), matched rule ids, and policyHash. Rules from
policies/default.yaml: ordered list, each with match conditions (operation,
token, asset class) and predicates (amount ceiling, destination allowlist,
per-address daily rate limit, compliance required); first match wins; explicit
default. Ship a default policy: allow small compliant transfers, escalate above
10_000 units or unknown destinations, deny frozen addresses. Property tests for
determinism and rule ordering. Accept: pytest green, 100% branch coverage on
the evaluator.

### M3 - Audit log
Append-only JSONL; each record: decision_id (uuid4), ts, actor, proposal,
policy result, human action if any, prev_hash, record_hash =
sha256(canonical_json), Ed25519 signature (key generated into .env-ignored
local file; public key committed as fixture for tests). `MerkleTree` (sha256,
sorted pairs, duplicate-last for odd) with proof generation/verification.
Tamper test: mutate a middle record, chain verification fails. Accept: pytest
green.

### M4 - Approval service
FastAPI app: POST /proposals (from agent; idempotency-key header respected),
GET /proposals/{id}, POST /proposals/{id}/approve, /reject (approver id +
comment), TTL expiry sweep (default 15 min -> auto-reject), optional
dual-control mode (two distinct approvers) behind a config flag. SQLite via
stdlib. On approve: guardian signer (eth-account) produces the EIP-712
signature over the Authorization built from the proposal + current policyHash;
the signature and decisionId are returned to the agent and written to the audit
log. Minimal single-file HTML approval page listing pending items with
approve/reject buttons (no framework, fetch calls). Tests with httpx
TestClient, including idempotent resubmission and expiry. Accept: pytest green.

### M5 - Agent
LangGraph graph: supervisor -> policy gate -> (execute | interrupt -> resume).
Typed tool registry (pydantic schemas) with tools: propose_transfer,
propose_mint, check_compliance, get_balance. Execution tools use web3.py
against a local anvil spawned/torn down by a pytest fixture (subprocess, fixed
mnemonic, deployment via forge script broadcast or direct bytecode deploy).
LLM providers behind one interface: MockLLM (deterministic scripted responses,
used by ALL tests) and AnthropicLLM (only active when AEGIS_LLM=anthropic and a
key is present; never required). Integration test, end to end on anvil: batch
of 5 transfers -> 4 auto-allowed and executed, 1 escalated -> approve via API
-> guardian sig -> executed; then a 6th to a frozen address -> denied; audit
records written for every decision. Accept: pytest green including the
integration flow.

### M6 - Adversarial evals
evals/corpus.yaml: 50+ prompt-injection attempts targeting the agent
(instruction override, tool-schema smuggling, role confusion, social
engineering of the approver message, unicode obfuscation, many-shot). Harness
runs the corpus through the full stack with MockLLM in "gullible mode"
(the mock complies with injected instructions at the LLM layer) to prove the
guarantee holds BELOW the model: policy + contract still block. Metrics
emitted to evals/report.md: bypass rate (must be 0), escalation precision,
denial recall. Accept: harness runs via `make evals`, bypass rate 0.

### M7 - MCP server
python/aegis/mcpserver: stdio MCP server (official python sdk) exposing
propose_transfer, get_proposal_status, list_pending, get_audit_proof so any
MCP client can drive the runtime through the same gate. Smoke test that speaks
the protocol over stdio. Accept: pytest green.

### M8 - Verify CLI, demo, docs
`aegis verify <decision-id>`: recompute record hash, build Merkle proof,
compare against the root in AuditAnchor via RPC; prints PROOF OK/FAIL.
`aegis anchor`: batch unanchored records, anchor root on-chain.
scripts/demo.sh: headless end-to-end (spawn anvil, deploy, run the M5 scenario
with MockLLM, auto-approve via API call, anchor, verify) printing a narrative.
docs/architecture.md (mermaid sequence + component diagrams),
docs/threat-model.md (assets, trust boundaries, STRIDE table, residual risks,
explicitly including "malicious/compromised LLM" and "prompt injection"),
README (what/why, 90-second quickstart, demo, design highlights, eval results).
Accept: `make demo` exits 0; `make test` green; docs complete.

Then write ALL_MILESTONES_COMPLETE as the last line of PROGRESS.md and stop.

## Pinned stack
Solidity 0.8.26, OpenZeppelin v5.x, Foundry latest. Python: langgraph,
langchain-core, fastapi, uvicorn, pydantic>=2, web3>=7, eth-account, PyYAML,
cryptography, httpx, pytest, ruff, mcp. Freeze exact versions into
requirements.lock after first successful install.