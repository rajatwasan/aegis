# SPEC.md: Aegis system specification and hardening plan

Status: normative. AGENTS.md states the rules every change obeys; this document states what the system is, module by module, and the ordered work items that bring the code up to it. Where the code and this document disagree, the code is wrong until a work item here is amended by the owner. Section 7 lists the work items; section 11 lists decisions already taken and the ones still open for the owner.

Revision: 2026-10-17, written against `main` at `4657e58` and branch `guardian-touch` at `df5e118`.

---

## 0. How to read this document

- Section 1 to 3 say what Aegis is and what it guarantees.
- Section 4 is the module contract list: for each module, its responsibility, public interface, invariants, failure behaviour, configuration and the tests that must exist. A module that does not meet its contract has an open work item in section 7.
- Section 5 is the configuration contract. Every environment variable the system reads is listed there and nowhere else.
- Section 6 is the error contract: the status codes and the "unreadable is an error" table.
- Section 7 is the ordered work item list with acceptance criteria and named tests.
- Section 8 is the test matrix and the local gate.
- Section 9 is the PR protocol and description template.
- Section 10 is the global definition of done.
- Section 11 records decisions.

Terms: "owner" is the repository owner. "principal" is an authenticated approver identity. "dev chain" is a chain whose `aegis.chains.ChainMeta.public` is false (anvil 31337, local 1337). "public chain" is any other chain id. "gated move" is any token operation that the plain path refuses with `GuardianRequired()`.

---

## 1. Purpose, scope, non goals

### 1.1 Purpose

Aegis makes the authority behind an AI agent's action provable. The agent proposes an operation. A deterministic policy engine allows, denies or escalates. An escalation waits for a human who proves who they are. Only then does a guardian key, which the agent never holds, sign an EIP 712 authorization for that exact operation. The token contract reverts without that signature. Every decision, every approval and every execution lands in an append only audit log that is hash chained, Ed25519 signed and Merkle anchored on chain, so a third party can verify after the fact that an action could not have happened without a human.

The claim Aegis makes is about impossibility, not good behaviour: the log does not say the agent behaved; it proves the agent could not have moved a gated asset without an authenticated human and a key it never had.

### 1.2 In scope

- ERC 20 and ERC 1155 tokens gated by threshold, compliance registry and freeze state, executed on any EVM chain.
- A policy engine over YAML rules with first match wins semantics.
- An approval service with authenticated principals (approver tokens and WebAuthn passkeys), TTL expiry, optional dual control, and guardian signing.
- A LangGraph reference agent with a typed tool registry, a scripted provider for tests and a real provider behind a flag.
- An MCP server exposing the same gate.
- An audit log with Merkle anchoring to a configured chain and a verify CLI.
- A browser console for approvers, with a mobile passkey screen.
- An adversarial evaluation harness proving bypass rate 0 with a fully compromised model.

### 1.3 Non goals (do not build, do not claim)

- Zero knowledge proofs, MPC or threshold signing, TEE attestation, formal verification. None exist here. AGENTS.md R46.
- Key custody hardening (HSM, KMS). The guardian key is a hex string in the approval service's environment; production custody is a deployment concern documented in `deploy/DEPLOY.md`.
- Multi tenant isolation. One deployment serves one operator, one token suite, one policy.
- A general purpose agent framework. The agent exists to exercise the gate.
- Non EVM chains.

---

## 2. System model

### 2.1 Actors and trust

| Actor | Trust | Holds | May do |
| --- | --- | --- | --- |
| LLM provider | Untrusted, assumed hostile | nothing | emit one proposed tool action per instruction |
| Agent runtime (`aegis.agent`) | Trusted host, no authority | operator key for plain transfers only | gate, execute ALLOW, submit ESCALATE, audit |
| MCP client | Untrusted | nothing | call the four MCP tools |
| Approval service (`aegis.approval`, `aegis.api`) | Trusted, key custodian | guardian key, approver token hashes, passkey public keys, admin token | verify principals, sign authorizations, write audit |
| Human approver | Trusted, the locus of control | an approver token or a paired passkey | approve or reject a pending proposal |
| Operator (deployer) | Trusted | operator key, admin token | deploy, seed, anchor, mint pairing codes |
| Chain | Trusted execution | nothing | enforce the gate deterministically |
| Contract admin | Trusted | DEFAULT_ADMIN_ROLE | rotate guardian, grant roles |

### 2.2 Components

```
LLM ──proposed action──► typed tools ──► policy engine ──► ALLOW ───► token.transfer()
 (untrusted)                (pydantic)    (pure fn)         DENY ────► stop, audit
                                                             ESCALATE ─► approval service
                                                                           │ authenticated human approves
                                                                           ▼ guardian EIP 712 sign
                                                                token.transferWithAuthorization(auth, sig)
every arrow on the right side appends to the audit log; `aegis anchor` seals batches on chain
```

- `contracts/`: `GuardianModule`, `GuardedToken`, `GuardedAsset1155`, `ComplianceRegistry`, `AuditAnchor`.
- `python/aegis/policy/`: `evaluate(proposal, context, policy) -> Decision`.
- `python/aegis/audit/`: `AuditLog`, `MerkleTree`, `AuditSigner`, canonical JSON.
- `python/aegis/approval/`: FastAPI approval service, `GuardianSigner`, store, principal auth (W3).
- `python/aegis/guardian_touch/`: WebAuthn pairing and decide routes (W4).
- `python/aegis/agent/`: `AegisRuntime`, LangGraph graph, tool registry, LLM providers, `ChainClient`.
- `python/aegis/api/`: console API over the approval service: SSE, read models, metrics, agent runs.
- `python/aegis/mcpserver/`: stdio MCP server over the same runtime.
- `python/aegis/anchoring.py`, `python/aegis/cli.py`: anchor and verify.
- `python/aegis/devchain.py` (W1): the only non test module that knows the anvil dev accounts.
- `frontend/`: Guardian Console (React, TanStack Query, typed OpenAPI client, SSE).
- `evals/`: injection corpus, harness, report.

### 2.3 Trust boundaries

| Boundary | Crossed by | Enforced by |
| --- | --- | --- |
| LLM to runtime | one JSON action | `aegis.agent.tools.validate_action` (unknown tool or bad args refused), then `evaluate` |
| Runtime to chain, plain path | `transfer` under threshold between compliant parties | contract `_requireCompliant`, threshold, `_requireNotFrozen` |
| Runtime to chain, gated path | consumed `Authorization` | `GuardianModule._consumeAuthorization`: signer is current guardian, single use `decisionId`, deadline, every field equal |
| Human to approval service | approve or reject | approver token (bearer) or passkey assertion over `sha256(decision_id || canonical_json(proposal))` |
| Approval service to chain | guardian signature | EIP 712 domain `AegisGuardian`/`1`/chainId/token over the exact struct |
| Audit to verifier | JSONL file plus `anchors.json` | hash chain, Ed25519 signature, Merkle proof against `AuditAnchor.rootOf(batchId)` |

---

## 3. On chain protocol (implemented, do not change without an ADR)

EIP 712 domain: name `AegisGuardian`, version `1`, `chainId`, `verifyingContract` = the token.

```
struct Authorization {
    bytes32 decisionId;   // sha256(decision_id string); single use on chain
    uint8   operation;    // 1 TRANSFER, 2 MINT, 3 BURN, 4 FREEZE
    address token;        // must equal address(this)
    address from;
    address to;
    uint256 id;           // asset class; 0 for the ERC20 token
    uint256 amount;
    bytes32 policyHash;   // sha256 of the exact policy file that produced the decision
    uint256 nonce;        // approval service counter, informational on chain
    uint256 deadline;     // unix seconds; block.timestamp must not exceed it
}
```

Checks in `_consumeAuthorization`, in order: field equality (`FieldMismatch`), deadline (`AuthorizationExpired`), single use (`DecisionAlreadyConsumed`), signer recovery equals `guardian` (`InvalidGuardianSignature`). Then mark consumed and emit `AuthorizationConsumed`.

Gates: `GuardedToken.transfer` and `transferFrom` revert `GuardianRequired()` when `amount > threshold` or either party is not compliant; both paths revert `AddressFrozen` when either party is frozen, including the authorized path (frozen blocks everything; unfreeze first). `GuardedAsset1155` applies per id thresholds. `setFrozen` is authorization only. `AuditAnchor.anchor(root, batchId)` requires `ANCHOR_ROLE`, stores `rootOf[batchId]`, emits `Anchored`.

Verified by: 50 forge tests including fuzz (`nonce`, `amount`, `deadline`) and the invariant `Invariant.t.sol` (no gated transfer succeeds without a consumed authorization).

---

## 4. Module contracts

Each module lists: Responsibility, Interface, Invariants, Failure behaviour, Configuration, Tests that must exist. "Status" names the work item when the module does not meet its contract today.

### 4.1 `contracts/`

Responsibility: enforce the gate on chain. Interface: section 3. Invariants: R7; guardian is never `address(0)`; every state transition emits an event. Failure behaviour: revert with a custom error, never a string. Configuration: constructor arguments only (name, symbol, guardian, admin, registry, threshold). Tests: existing 50 forge tests; fmt clean under the CI Foundry version.

Status: formatting drift (W0). No functional change planned.

### 4.2 `aegis.policy`

Responsibility: pure decision function. Interface: `load_policy(path) -> Policy` (carries `policy_hash` = sha256 of the file bytes), `evaluate(proposal: Proposal, context: Context, policy: Policy) -> Decision(effect, matched_rules, policy_hash)`. Rules: ordered, `match` on operation/token/asset class, `when` predicates (`amount_at_most`, `amount_above`, `destination_known`, `compliant_parties`, `frozen_party`, `within_daily_limit`), first match wins, explicit `default`.

Invariants: R6 (no I/O, no clock, no model); same inputs give the same `Decision`; a policy file edit changes `policy_hash`. Failure behaviour: a malformed policy raises at `load_policy`, never at `evaluate`; an unknown predicate is a load error. Configuration: `AEGIS_POLICY_PATH`, required (W7). Tests: 100% branch coverage on `engine.py`, property tests for determinism and ordering, a test that two byte different files produce different hashes.

Status: `policies/default.yaml` carries anvil addresses in its allowlist and is loaded by default (W7).

### 4.3 `aegis.audit`

Responsibility: append only evidence. Interface: `AuditLog(path, signer).append(actor, proposal, policy_result, human_action=None, decision_id=None, ts=None, human_presence=None) -> record`, `.records()`, `.verify(public_key_hex)`, `verify_records(records, public_key_hex)`, `MerkleTree(leaves).root/proof/verify`, `AuditSigner.load_or_create(path)`.

Record shape (hashed fields, in canonical JSON order): `decision_id`, `ts`, `actor`, `proposal`, `policy_result`, `human_action`, `prev_hash`, and `human_presence` when present. Derived: `record_hash = sha256(canonical_json(hashed fields))`, `signature = Ed25519(record_hash)`.

Invariants: R8, R9; `prev_hash` of record 0 is 64 zeros; `records()` returns the file order; `human_action` for a human resolution carries `action`, `approver` (principal id), `auth` (`token` or `passkey`), `comment` (W3). Failure behaviour: a corrupt line raises `AuditVerificationError` in `verify`; `records()` raises on a line that is not JSON rather than skipping it (R11; today it raises, keep it). Configuration: `AEGIS_AUDIT_KEY_FILE`, `AEGIS_AUDIT_LOG_PATH`. Tests: tamper tests (mutate, delete, hash fixup without key), signature test, Merkle odd count test, `human_presence` covered by hash (branch test `test_guardian_audit.py`).

Status: `human_presence` exists only on `guardian-touch` (W4); `auth` field missing (W3).

### 4.4 `aegis.approval`

Responsibility: hold pending escalations, authenticate approvers, sign authorizations, write audit. Interface (HTTP, unchanged paths):

| Method and path | Auth | Body | Codes |
| --- | --- | --- | --- |
| `POST /proposals` | none (runtime is in process) | `ProposalIn` | 201 created, 200 idempotent replay, 422 |
| `GET /proposals?status=` | none | | 200 |
| `GET /proposals/{id}` | none | | 200, 404 |
| `POST /proposals/{id}/approve` | principal (W3) | `ActionIn{comment}` | 200, 401, 404, 409 not pending, 409 same principal twice, 422 extra field |
| `POST /proposals/{id}/reject` | principal (W3) | `ActionIn{comment}` | 200, 401, 404, 409, 422 |
| `GET /` | none | | 200 HTML approval page |

Python interface: `create_app(config: ApprovalConfig, bus: EventBus | None) -> FastAPI`; `GuardianSigner(private_key, chain_id).sign_authorization(auth) -> hex`; `build_authorization(...)`; `ProposalStore`.

Invariants: R2 (no default guardian key), R4 (principal from credential), R5 (TTL sweep auto rejects, writes an `expired` audit record, nothing signs), R15 (idempotency and nonce in the store). Dual control requires two distinct principal ids. The signed `Authorization.deadline` is `now + auth_deadline_seconds`. `approvals[]` entries carry `approver`, `auth`, `comment`, `ts`.

Failure behaviour: missing or invalid credential is 401 with `WWW-Authenticate: Bearer`; a body carrying `approver` is 422 (`extra = "forbid"`), so an old client fails loudly instead of being silently trusted; signer construction with a key that is not `0x` plus 64 hex fails at startup.

Configuration: `AEGIS_GUARDIAN_KEY` (required), `AEGIS_CHAIN_ID`, `AEGIS_APPROVER_TOKENS` (required unless the deployment is passkey only, see W3), `AEGIS_ADMIN_TOKEN` (required when guardian_touch is mounted), `AEGIS_APPROVAL_TTL_SECONDS`, `AEGIS_DUAL_CONTROL`, `AEGIS_DB_PATH`, `AEGIS_AUDIT_LOG_PATH`, `AEGIS_AUDIT_KEY_FILE`, `AEGIS_POLICY_PATH` (required).

Tests that must exist: all current `test_approval_service.py` cases, plus `test_approval_auth.py` (W3) and `test_config.py` (W1).

Status: W1, W3.

### 4.5 `aegis.approval.auth` (new, W3)

Responsibility: turn a request into a `Principal` or a 401. Interface:

```python
@dataclass(frozen=True)
class Principal:
    id: str              # "ops-1" for tokens, "passkey:<credential_id[:8]>" for passkeys
    auth: Literal["token", "passkey"]

class ApproverRegistry:
    @classmethod
    def from_env(cls) -> ApproverRegistry   # parses AEGIS_APPROVER_TOKENS
    def lookup(self, token: str) -> Principal | None   # constant time over every entry
    def __len__(self) -> int

def require_approver(request) -> Principal        # FastAPI dependency; 401 on missing or unknown
def require_admin(request) -> None                # FastAPI dependency; 401 on missing or unknown AEGIS_ADMIN_TOKEN
```

`AEGIS_APPROVER_TOKENS` format: comma separated `id:token` pairs, `id` matches `[a-z0-9][a-z0-9._-]{0,63}`, `token` is at least 24 characters, no `:` or `,`. Parse errors raise `ConfigError` naming the variable and the offending entry index, never the token value. Lookup compares every stored token with `hmac.compare_digest` and does not short circuit on the first match. Tokens are never logged.

Invariants: R4, R33, R34. Tests: `test_approval_auth.py::test_registry_parses_pairs`, `::test_registry_rejects_short_token`, `::test_registry_rejects_duplicate_id`, `::test_lookup_constant_shape` (every entry compared), `::test_missing_header_401_with_challenge`, `::test_unknown_token_401`, `::test_body_approver_field_422`, `::test_principal_recorded_in_approvals_and_audit`, `::test_dual_control_same_principal_409`, `::test_dual_control_two_principals_approves`, `::test_passkey_and_token_count_as_distinct`.

### 4.6 `aegis.guardian_touch` (on branch `guardian-touch`, W4)

Responsibility: proof of human presence via WebAuthn. Interface:

| Method and path | Auth | Codes |
| --- | --- | --- |
| `POST /guardian/pair/start` | admin token (W4 change; today open) | 200 `{code}`, 401, 500 |
| `POST /guardian/pair/options` | live pairing code in body | 200 registration options, 404, 409 used, 410 expired |
| `POST /guardian/pair/complete` | live pairing code in body | 200 `{credential_id, sign_count}`, 400 verification failed |
| `POST /guardian/auth-options/{id}` | none | 200 authentication options, 404 unknown decision, 409 no passkey paired |
| `POST /guardian/decide/{id}` | passkey assertion in body | 200 (approve or reject result plus `passkey_assertion`), 400 assertion failed, 404 unknown credential or decision, 409 not pending |

Challenge: `sha256(decision_id || canonical_json(proposal))`, so the assertion is bound to the exact payload. The verified assertion is stashed on the proposal row before routing into the approve or reject handler, which embeds it as `human_presence` in the audit record before hashing (R9). Principal: `Principal(id=f"passkey:{credential_id[:8]}", auth="passkey")`.

Invariants: pairing codes are single use with a 5 minute TTL; sign counts are monotonic and persisted; `rp_id` and `expected_origin` describe the frontend domain. Failure behaviour: a WebAuthn verification failure is 400 with the library message, never a silent approve. Configuration: `AEGIS_RP_ID`, `AEGIS_EXPECTED_ORIGIN`, `AEGIS_ADMIN_TOKEN`. CLI: `aegis guardian pair-code` mints a code directly in the store for operators without the admin token on hand (W4).

Tests: branch tests `test_guardian_touch.py`, `test_guardian_audit.py`, plus `::test_pair_start_requires_admin_token`, `::test_decide_records_auth_passkey`.

Status: unmerged and one commit behind `main` (W4).

### 4.7 `aegis.agent`

Responsibility: the reference agent. Interface: `build_graph(llm, runtime)`; `AegisRuntime(policy, audit, chain, token, registry, approval_client)` with `handle(proposal) -> result` and `resume(decision_id) -> result`; `validate_action(action) -> (tool, args)`; providers `MockLLM(script, gullible)`, `AnthropicLLM(model, api_key)`, `provider_from_env()`; `ChainClient(rpc_url, operator_key)`.

Invariants: R1 (the runtime never sees the guardian key; it submits `row["authorization"]` and `row["signature"]` returned by the approval service); `handle` writes exactly one audit record per proposal; `resume` writes exactly one; the daily spend counter is in process only (documented limitation). `AnthropicLLM` is used only when `AEGIS_LLM=anthropic` and `ANTHROPIC_API_KEY` is set; the model string comes from `AEGIS_LLM_MODEL` (W5); a reply that is not one JSON object with a `tool` key becomes `{"tool": "malformed", "args": {"reason": ...}}`, which the registry refuses (R11; never a default action).

Failure behaviour: an RPC failure during `handle` raises and the graph run fails visibly; a 4xx from the approval service raises. Configuration: `AEGIS_LLM`, `AEGIS_LLM_MODEL`, `ANTHROPIC_API_KEY`, `AEGIS_OPERATOR_KEY` (W2). Tests: `test_agent_tools.py`, `test_integration_anvil.py`, plus `test_llm_provider.py` (W5).

Status: W2, W5.

### 4.8 `aegis.api`

Responsibility: the console's one origin. Interface: the approval service routes plus `GET /events` (SSE), `GET /decisions`, `GET /audit/records`, `GET /audit/records/{id}`, `GET /audit/verify/{id}`, `GET /policy`, `GET /metrics`, `GET /compliance/{address}`, `POST /anchor`, `POST /agent/run`, `GET /agent/instructions`, and the `/guardian/*` routes after W4.

Invariants: one process owns one store, one audit log, one policy (ADR 002); `/metrics.chain.rpc_url` is redacted; `/agent/run` serializes runs (shared operator nonce); the runner refuses to start when the configured guardian signer address differs from the token's on chain `guardian()` (W1); `/metrics.injections` carries `source` and `generated_at` (W7); `/agent/instructions` carries `provider` (W5).

Failure behaviour: chain not configured or unreachable is 503 with the reason on `/audit/verify`, `/anchor`, `/agent/run`; `/compliance/{address}` returns `known: false` with a `reason` string when the chain is unavailable (R11, W7) rather than a bare unknown; unknown canned instruction in mock mode is 400 naming the set.

Configuration: `AEGIS_STATE_DIR`, `AEGIS_CORS_ORIGINS`, `AEGIS_API_HOST`, `AEGIS_API_PORT`, `AEGIS_EVALS_REPORT`, `AEGIS_OPERATOR_KEY`, plus everything in 4.4. Tests: `test_api.py`, `test_api_chain.py`, SSE consumption test, plus W1, W2, W5, W7 tests.

### 4.9 `aegis.mcpserver`

Responsibility: same gate for MCP clients. Interface: stdio tools `propose_transfer`, `get_proposal_status`, `list_pending`, `get_audit_proof`. Invariants: no approve tool is exposed over MCP (approval is a human act); the backend shares the runtime and store. Configuration: `AEGIS_*` as the backend reads them. Tests: `test_mcp_server.py` subprocess smoke test.

Status: inherits W1 (config construction) and W2 (operator key).

### 4.10 `aegis.anchoring` and `aegis.cli`

Responsibility: seal and prove. Interface: `anchor_unanchored(state_dir) -> batch | None`, `verify_decision(...)`, `verify_decision_in_dir(state_dir, decision_id)`, `batch_view(state, batch)`; CLI `aegis anchor`, `aegis verify <id>`, `aegis verify --all`, `aegis guardian pair-code` (W4).

Invariants: `PROOF OK` requires the recomputed record hash to equal the stored one, the Merkle path to reproduce the batch root, and that root to equal `AuditAnchor.rootOf(batchId)` fetched over RPC; anything else is `PROOF FAIL` with a reason (R5). The operator key is read from configuration, not from `state.json` (W2). Tests: `test_cli.py` anchor, verify, tamper.

### 4.11 `aegis.devchain` (new, W1)

Responsibility: be the only non test module that knows the anvil dev accounts. Interface: `ACCOUNTS: dict[int, str]`, `KEYS: dict[int, str]` (indices 0 and 9 only), `DEV_CHAIN_IDS = frozenset({31337, 1337})`, `is_dev_chain(chain_id) -> bool`, `is_dev_key(hex_key) -> bool`, `is_dev_address(address) -> bool`, `dev_guardian_key() -> str`, `dev_operator_key() -> str`, `require_not_dev_key(hex_key, role: str, chain_id: int) -> None` (raises `ConfigError` on a public chain). Invariants: R3. Tests: `test_devchain.py`.

### 4.12 `frontend/` Guardian Console

Responsibility: the human control surface. Invariants: R32, R33; the approver token input is a password field stored under `aegis.approver_token`; every approve or reject sends `Authorization: Bearer <token>` and no `approver` body field (W3); a 401 surfaces as an error on the row and the row is restored (existing rollback path); the dashboard's injections card is labelled "last eval run" with the report's timestamp and renders "no eval report" when `injections` is null (W7); the console labels the agent provider (`scripted demo` or the model name) from `/agent/instructions.provider` (W5); the `/guardian` mobile screen pairs and decides with a passkey (W4).

Tests: Vitest with MSW: token gate, header sent, 401 rollback, injections null state, provider badge, plus the existing 52 and the branch's `GuardianPage.test.tsx`. Playwright `make e2e` drives the full loop with the dev token printed by the dev stack.

### 4.13 `evals/`

Responsibility: prove bypass rate 0 with a gullible model. Invariants: the harness builds its own approval app with an explicit dev guardian key and never approves; `evals/report.md` carries a `generated_at` line (W7) and is regenerated by `make evals` from the committed revision (R24). Tests: `test_evals.py` runs the corpus inside pytest.

---

## 5. Configuration contract

Every environment variable the system reads. "Required" means `from_env` raises `ConfigError` naming the variable when it is missing; there is no built in fallback (R2). "Dev default" means a value is substituted only when the target chain is a dev chain, and the substitution is printed once at startup.

| Variable | Read by | Required | Dev default | Validation |
| --- | --- | --- | --- | --- |
| `AEGIS_GUARDIAN_KEY` | approval, api, demo, devstack, evals | yes | anvil key 9 | `0x` + 64 hex; refused on a public chain if it is a dev key |
| `AEGIS_OPERATOR_KEY` | api, anchoring, demo, devstack, mcpserver | yes when a chain is configured | anvil key 0 | `0x` + 64 hex; refused on a public chain if it is a dev key; must derive to `state.json.operator_address` |
| `AEGIS_DEPLOYER_KEY` | devstack, start.sh | alias accepted for `AEGIS_OPERATOR_KEY` | | same |
| `AEGIS_APPROVER_TOKENS` | approval | yes unless `AEGIS_APPROVALS=passkey` | dev stack generates one and prints it | `id:token,...`, token >= 24 chars |
| `AEGIS_APPROVALS` | approval | no, default `token,passkey` | | subset of `token`, `passkey`; at least one |
| `AEGIS_ADMIN_TOKEN` | guardian_touch pair start | yes when `passkey` is enabled | dev stack generates one and prints it | >= 24 chars |
| `AEGIS_POLICY_PATH` | approval, api, demo, devstack, mcpserver | yes | `policies/dev.yaml` | file exists and loads |
| `AEGIS_CHAIN_ID` | approval | yes when no `state.json` | 31337 | int |
| `AEGIS_RPC_URL` | demo, devstack, start.sh | no, default `http://127.0.0.1:8545` | | url |
| `AEGIS_STATE_DIR` | api, cli, demo, devstack | no, default `.aegis/demo` | | path |
| `AEGIS_DB_PATH` | api | no, default `<state_dir>/approvals.db` | | path |
| `AEGIS_AUDIT_LOG_PATH` | api | no, default `<state_dir>/audit.jsonl` | | path |
| `AEGIS_AUDIT_KEY_FILE` | api, approval | no, default `<state_dir>/audit.key` | | path, created 0600 |
| `AEGIS_APPROVAL_TTL_SECONDS` | approval | no, default 900 | | float > 0 |
| `AEGIS_DUAL_CONTROL` | approval | no, default false | | `true`/`false` |
| `AEGIS_CORS_ORIGINS` | api | no, default localhost:5173 origins | | comma separated origins |
| `AEGIS_API_HOST`, `AEGIS_API_PORT` | api `__main__` | no, default `127.0.0.1`, `8000` | | |
| `AEGIS_EVALS_REPORT` | api | no, default `evals/report.md` | | path |
| `AEGIS_EXPLORER_URL` | chains | no | | url |
| `AEGIS_RP_ID`, `AEGIS_EXPECTED_ORIGIN` | guardian_touch | yes when `passkey` is enabled | `localhost`, `http://localhost:5173` | |
| `AEGIS_LLM` | agent | no, default `mock` | | `mock` or `anthropic` |
| `AEGIS_LLM_MODEL` | agent | no, default `claude-sonnet-5-5` | | non empty |
| `ANTHROPIC_API_KEY` | agent | yes when `AEGIS_LLM=anthropic` | | non empty |
| `AEGIS_ALLOW_LOCAL_FALLBACK` | start.sh | no, default false | | `true` to permit the anvil fallback |
| `VITE_API_URL` | frontend build | no, default `http://127.0.0.1:8000` | | url |

`state.json` (written by demo and devstack, read by api, anchoring, cli) carries: `rpc_url`, `chain_id`, `chain_name`, `explorer_url`, `public`, `operator_address`, `guardian` (address), `anchor_address`, `token_address`, `registry_address`, `deployed_block`, `audit_log_path`, `audit_key_file`, `parties: {compliant: [...], frozen: [...]}` (W7). It never carries a private key (W2).

---

## 6. Error contract

### 6.1 HTTP status codes

| Code | Meaning here | Where |
| --- | --- | --- |
| 400 | request understood, refused on content | bad address format, unknown canned instruction, WebAuthn verification failed |
| 401 | no or invalid credential | approve, reject, pair start; header `WWW-Authenticate: Bearer` |
| 404 | unknown id | decision, credential, pairing code, audit record |
| 409 | state conflict | not pending, same principal twice, pairing code used, no passkey paired |
| 410 | expired | pairing code |
| 422 | body shape rejected | pydantic validation, including a forbidden `approver` field |
| 503 | dependency unavailable | no chain state, RPC unreachable, during verify, anchor, agent run |

### 6.2 Unreadable is an error (R11, R12)

| Read | Today | Required |
| --- | --- | --- |
| `evals/report.md` missing or unparseable | `/metrics.injections` is `null`, console shows "run make evals" | keep `null`; console shows "no eval report" and never a 0; when present carry `source` and `generated_at` and label "last eval run" |
| `state.json` missing | `StateError` to 503 | keep; message names the path |
| RPC unreachable in `/compliance/{address}` | `known: false` | `known: false` plus `reason` string; drawer shows "standing unavailable: <reason>" |
| `eth_chainId` fails in `/metrics.chain` | `connected: false`, `chain_id` from state | keep; console shows "chain unreachable" badge, not a green dot |
| token `guardian()` differs from configured signer | silent (approvals would revert on chain later) | startup refusal with both addresses in the message (W1) |
| `AEGIS_GUARDIAN_KEY` unset | anvil key 9 | `ConfigError` (W1) |
| `AEGIS_APPROVER_TOKENS` unset | no auth at all | `ConfigError` unless passkey only (W3) |
| audit log line not JSON | raises | keep raising; `/audit/records` returns 500 with "audit log unreadable at line N" rather than a partial list |
| `anchors.json` batch without `tx_hash` | links omitted | keep; verify reports `anchor_tx: null` and the console says "unanchored", never "PROOF OK" |
| LLM reply not JSON | `json.loads` raises, run fails | `malformed` action refused with reason, run continues to the next instruction (W5) |

---

## 7. Work items

Status at revision 2026-10-17 (stacked branches `hardening/00` to `hardening/09`):

| Item | Branch | State |
| --- | --- | --- |
| W0 formatting | `hardening/00-forge-fmt` | done |
| W6 residue (merged first, no code paths) | `hardening/01-residue` | done |
| W1 guardian key | `hardening/02-guardian-key` | done |
| W2 operator key | `hardening/03-operator-key` | done |
| W3 approver auth | `hardening/04-approver-auth` | done |
| W4 passkeys merged | `hardening/05-passkeys` | done |
| W5 real model | `hardening/06-real-llm` | done |
| W7 dev defaults | `hardening/07-dev-defaults` | done |
| W8 hygiene and CI | `hardening/08-hygiene-ci` | done |
| W9 docs | `hardening/09-docs-truth` | done |
| W10 public chain verified | none (owner action) | open |

Ordered. Each item is one branch and one PR (R37). "Depends on" must be merged first. Every item ends with the full local gate green (R20) and the PR template (section 9) filled.

### W0. Formatting under current Foundry (P1, no behaviour change)

Why: CI has been red on every push to `main` since July because `forge fmt --check` under current stable Foundry rejects code formatted with forge 0.2.0 (`contracts/src/GuardedToken.sol` and `GuardedAsset1155.sol` long signatures). A red CI hid every later regression.

Change: run `forge fmt` with the Foundry version CI installs; commit the result; no other edits.

Accept: `forge fmt --check` and `forge test` green locally with the same Foundry version as CI; CI `contracts` job green on the PR.

### W1. Guardian key: no default, deploy and verify against the configured key (P0)

Why: `python/aegis/approval/config.py` defines `DEFAULT_GUARDIAN_KEY` (anvil dev key 9) and both `ApprovalConfig` and `ApiConfig.from_env` fall back to it; `python/aegis/demo.py` `deploy()` hardcodes `GUARDIAN = ACCOUNTS[9]` into the token constructor and signs the seed mint and freeze with `KEYS[9]`; `python/aegis/devstack.py` writes `"guardian": ACCOUNTS[9]` for every deployment including Base Sepolia. The whole product claim is a signature the agent cannot forge; today the default signer is a key everyone has, and the public testnet deployment is gated by it.

Change:
1. Add `python/aegis/devchain.py` per 4.11. Move `ACCOUNTS`/`KEYS` out of `demo.py`, `evals_harness.py`, `agent_runner.py`; those import from `devchain` (demo, evals) or stop needing them (runner, W7).
2. `ApprovalConfig.guardian_key: str` with no default; `field_validator` for hex shape; model validator calling `devchain.require_not_dev_key(key, "guardian", chain_id)`. `ApprovalConfig.from_env` and `ApiConfig.from_env` raise `aegis.config.ConfigError` (new tiny module) naming `AEGIS_GUARDIAN_KEY` when unset. On a dev chain only, `from_env` may substitute `devchain.dev_guardian_key()` when `AEGIS_GUARDIAN_KEY` is unset and print `using anvil dev guardian key (dev chain 31337)` once.
3. `demo.deploy(chain, *, guardian: GuardianSigner, operator: str | None = None, chain_id: int = 31337)`: constructor receives `guardian.address`; seed mint and freeze are signed by `guardian`. `demo.run` and `devstack.run` build the signer from `AEGIS_GUARDIAN_KEY` (dev default on a dev chain, refusal on a public chain). `state.json.guardian` is `guardian.address`.
4. Startup integrity: `AgentRunner._ensure_runtime` reads `token.functions.guardian().call()` and raises `StateError("guardian key mismatch: configured signer 0x.. is not the token guardian 0x..")` when they differ; `python -m aegis.api` performs the same check eagerly when `state.json` exists and exits 1 with that message.
5. `.env.example`: `AEGIS_GUARDIAN_KEY=0xREPLACE_WITH_A_KEY_YOU_GENERATED` (fails hex validation on purpose) with a comment on how to generate one.
6. `conftest.py` and every test that builds an `ApprovalConfig` pass `guardian_key=KEYS[9]` and `policy_path` explicitly through one helper `dev_approval_config(tmp_path, **overrides)` in `python/tests/helpers.py`.

Accept and tests:
- `test_config.py::test_guardian_key_required_names_variable`
- `test_config.py::test_guardian_key_hex_shape`
- `test_config.py::test_dev_guardian_key_refused_on_public_chain` (chain_id 84532)
- `test_config.py::test_dev_guardian_key_allowed_on_dev_chain`
- `test_devchain.py::test_is_dev_key_and_address`, `::test_require_not_dev_key_messages`
- `test_integration_anvil.py::test_deploy_uses_configured_guardian`: deploy with a freshly generated key; `token.guardian()` equals the signer address; an authorization signed by anvil key 9 reverts `InvalidGuardianSignature`; one signed by the configured key executes.
- `test_api_chain.py::test_runtime_refuses_guardian_mismatch`
- `scripts/check_hygiene.sh` (W8) fails if the anvil key 9 hex appears outside `python/tests/` and `python/aegis/devchain.py`.
- `make demo` exits 0 with no env set (dev defaults) and prints the dev key notice once.

### W2. Operator key out of `state.json` (P1, security)

Why: `demo.py` writes `"operator_key": KEYS[0]` and `devstack.py` writes the funded deployer key into `state.json`; on the hosted deployment that file lives at `/data/aegis/state.json` and holds a funded testnet key in plaintext. `agent_runner.py` and `anchoring.anchor_contract` read it from there.

Change: `AEGIS_OPERATOR_KEY` (alias `AEGIS_DEPLOYER_KEY`) is the only source of the operator key; `ApiConfig.operator_key` (required when `state.json` exists; dev default anvil key 0 on a dev chain). `state.json` stores `operator_address` only. `anchoring.anchor_contract(state, operator_key)` takes the key as an argument; `cli.py` reads it from `ApiConfig.from_env()`. `AgentRunner._ensure_runtime` verifies `ChainClient(key).operator_address == state["operator_address"]` and raises `StateError` otherwise. A migration note in `deploy/DEPLOY.md`: existing deployments set the secret and remove the field; the loader refuses a `state.json` that still contains `operator_key` with "state.json contains a private key; remove it and set AEGIS_OPERATOR_KEY".

Accept and tests: `test_api_chain.py::test_state_json_contains_no_private_key`, `::test_operator_key_mismatch_refused`, `test_cli.py::test_anchor_reads_operator_key_from_env`, `test_devstack.py::test_devstack_state_has_no_private_key`, `test_config.py::test_state_with_operator_key_refused`.

Depends on: W1.

### W3. Authenticated approvals (P0)

Why: `POST /proposals/{id}/approve` and `/reject` take `approver` as free text in the body; the console fills it from a `localStorage` field labelled "your name". Anyone who can reach the API approves as anyone. README line 15 says "a human it cannot impersonate"; today it can.

Change:
1. Add `python/aegis/approval/auth.py` per 4.5.
2. `ActionIn` becomes `{comment: str}` with `extra = "forbid"`. `approve` and `reject` take `principal: Principal = Depends(require_approver)`. `approvals[]` entries gain `auth`. `resolution` and the audit `human_action` carry `approver` (principal id) and `auth`. Dual control compares principal ids.
3. `ApprovalConfig` gains `approvals: frozenset[str]` (from `AEGIS_APPROVALS`, default `{"token", "passkey"}`), `approver_tokens: ApproverRegistry` (required when `token` is enabled), `admin_token: str | None` (required when `passkey` is enabled).
4. `python/aegis/approval/page.py`: the single file approval page gets a token field (password input) and sends the bearer header; the approver field is removed.
5. Frontend: `lib/approver.ts` becomes `lib/approverToken.ts` (`useApproverToken`, key `aegis.approver_token`); `queries.ts` `useProposalAction` sends `Authorization: Bearer` and no `approver` field; `ApproverIdentity` becomes a password input labelled "approver token"; the drawer shows the principal ids returned by the server; MSW handlers return 401 without the header. Regenerate `openapi.json` and `schema.d.ts` (R25).
6. `scripts/dev-stack.sh` and `scripts/demo.sh`: generate `AEGIS_APPROVER_TOKENS=dev:<random 32 hex>` and `AEGIS_ADMIN_TOKEN=<random>` when unset, export them to the API process, and print the dev approver token once with the console URL. `demo.py` approves through the TestClient with the header.
7. `evals_harness.py`: configure a registry (never used; the harness never approves).
8. Playwright `e2e/smoke.spec.ts`: enter the dev token in the console before approving.

Accept and tests: 4.5 list; `test_api_chain.py::test_console_approve_requires_token`; frontend `ApprovalsPage.test.tsx` token gate, header sent, 401 rollback; `ConsolePage.test.tsx` inline approve sends header; `make e2e` green; `make demo` exits 0.

Depends on: W1.

### W4. Merge `guardian-touch` and harden pairing (P1)

Why: the passkey work (three commits, `14949c2`, `7fa4b22`, `df5e118`) is the strongest evidence Aegis produces (a Face ID assertion embedded in the signed record) and it is unmerged, one commit behind `main`. On the branch `POST /guardian/pair/start` is open, so anyone can pair a passkey and then approve.

Change: rebase the branch onto `main`; resolve `python/aegis/api/app.py` and `python/aegis/api/models.py` in favour of `main`'s `AnchorInfo`, `ChainStatus` and explorer fields while adding `mount_guardian_touch(app)` and `human_presence`; keep `main`'s `.env.example` public chain block and add the RP variables. Then: `pair_start` depends on `require_admin`; `decide` builds `Principal(auth="passkey")` and routes into the W3 handlers with that principal (no `ActionIn.approver`); add `aegis guardian pair-code` CLI; `GuardianTouchConfig.from_env` requires `AEGIS_RP_ID` and `AEGIS_EXPECTED_ORIGIN` on a public chain (dev defaults on a dev chain). Regenerate `openapi.json`, `schema.d.ts`. Update `docs/adr/004-passkey-pairing-challenge.md` (exists on the branch) with the admin gate.

Accept and tests: branch tests green on top of `main`; `test_guardian_touch.py::test_pair_start_requires_admin_token`; `test_guardian_audit.py::test_decide_records_auth_passkey`; `GuardianPage.test.tsx` green; frontend `npm test` count equals 52 + branch tests.

Depends on: W3.

### W5. Real model in the console behind the flag (P1)

Why: `api/agent_runner.py` hardwires `MockLLM(script=plan)` with three canned plans and answers "the keyless MockLLM only understands the canned instructions" to anything else. `provider_from_env()` and `AnthropicLLM` exist but nothing calls them, so the live console never runs a model. `AnthropicLLM` hardcodes `claude-sonnet-5` and `json.loads` the reply with no handling.

Change: `AgentRunner.start(instruction)`: if `provider_from_env()` is an `AnthropicLLM`, run the graph with it on `[instruction]`; in mock mode keep the canned map and the 400. `GET /agent/instructions` returns `{provider: "mock" | "anthropic", model: str | null, instructions: [...]}`. `AnthropicLLM(model=os.environ AEGIS_LLM_MODEL default "claude-sonnet-5-5")`; the system prompt lists the tools and the operator context; the reply is parsed by extracting the first `{...}` block; a parse failure or a reply without `tool` yields `{"tool": "malformed", "args": {"reason": "..."}}`; HTTP errors raise with the status. The console shows a provider badge from the response.

Accept and tests: `test_llm_provider.py::test_valid_json_action`, `::test_json_wrapped_in_prose`, `::test_non_json_becomes_malformed`, `::test_http_error_raises` (httpx `MockTransport`); `test_api_chain.py::test_runner_uses_env_provider` (monkeypatch `provider_from_env`); `test_api.py::test_instructions_carry_provider`; frontend badge test. No test requires a key (R27).

Depends on: W1 (config), W3 (approvals in the console path).

### W6. Remove hackathon residue, keep history (P1)

Why: tracked files `run.log`, `loop.out`, `nohup.out`, `aegis_profile.json`, `selfscore.py`, `run.sh`, `run-frontend.sh`, `claude.md`, `PROMPT.md`, `FRONTEND.md`, `PROGRESS.md`, `BLOCKERS.md` are the overnight build harness and its output; `deploy/DEPLOY.md` is titled "Night Hack prep" with a "Hackathon disclosure" section; `fly.toml` on the branch carries Vercel preview origins. A reader opens the repo and sees how it was produced before what it does.

Change: delete `run.log`, `loop.out`, `nohup.out`, `aegis_profile.json`, `selfscore.py`, `run.sh`, `run-frontend.sh`, `BLOCKERS.md`; move `PROMPT.md` to `docs/history/2026-07-mission-spec.md`, `FRONTEND.md` to `docs/history/2026-07-frontend-spec.md`, `PROGRESS.md` to `docs/history/2026-07-build-log.md`; replace `claude.md` with `AGENTS.md` (this repository's rules) and a one line `CLAUDE.md` pointing at it; add `SPEC.md`; rewrite `deploy/DEPLOY.md` as an operations runbook (prerequisites, secrets, deploy, verify, rotate, roll back, migration note from W2) with no event framing; strip deployment specific origins and app names from `fly.toml` into documented secrets; `.gitignore` gains `nohup.out`, `aegis_profile.json`; `.dockerignore` loses the log entries it no longer needs.

Accept: `git ls-files | grep -E '\.(log|out)$'` is empty; `scripts/check_hygiene.sh` (W8) passes; `make demo`, `make test` unchanged.

Depends on: none (merge first; it touches no code paths).

### W7. Fence dev defaults (P2)

Why: `policies/default.yaml` allowlists anvil accounts 1 to 3 and is the policy every config loads unless told otherwise; `api/agent_runner.py` hardcodes anvil addresses in `_ACCOUNTS`; `deploy/start.sh` falls back to a local anvil when the public RPC or key fails, so a hosted demo can silently run on a disposable chain; the dashboard's "injections blocked" number is read from the committed `evals/report.md` and presented as live.

Change: rename `policies/default.yaml` to `policies/dev.yaml` with a header comment "DEV CHAIN ONLY: allowlist is anvil accounts"; `AEGIS_POLICY_PATH` required with the dev default rule of section 5; `deploy()` writes `state.json.parties` and `agent_runner.canned_plans` reads destinations from it; `start.sh` exits 1 on public deploy failure unless `AEGIS_ALLOW_LOCAL_FALLBACK=true`; `parse_eval_report` returns `source` and `generated_at` (from a `generated_at:` line the harness writes; file mtime if absent) and the dashboard labels the card "injections blocked, last eval run <time>" and renders "no eval report" for null; `/compliance/{address}` returns `reason` when unavailable and the drawer renders it.

Accept and tests: `test_config.py::test_policy_path_required`; `test_api_chain.py::test_canned_plans_use_state_parties`; `test_api.py::test_metrics_injections_carry_source_and_time`, `::test_compliance_unavailable_has_reason`; `test_evals.py::test_report_has_generated_at`; frontend `DashboardPage.test.tsx` null state and label; a shell test for `start.sh` (bats or a bash function under `scripts/tests/`) asserting exit 1 without the flag.

Depends on: W1, W3.

### W8. Hygiene script and CI (P1)

Why: nothing in CI enforces R1, R3, R43 or R48; the clean room check in the original kit was a one off grep.

Change: `scripts/check_hygiene.sh`: fails on (a) any anvil dev private key hex outside `python/tests/` and `python/aegis/devchain.py`; (b) the strings in R48 anywhere (case insensitive); (c) any tracked file matching `.gitignore`; (d) `operator_key` or `guardian_key` as a JSON key in any tracked `.json`; (e) `0xac0974...`, `0x2a871d...` in `.env.example`. CI gains a `hygiene` job running it, and the `python` job runs `pytest --cov` with the floors of R26 enforced by `--cov-fail-under` per package via `python/.coveragerc`.

Accept: the script fails on the parent of W1 and passes on `main` after W1 to W7; CI green on the PR.

Depends on: W1, W6.

### W9. Documentation states what exists (P0 for the README, P1 for the rest)

Why: README line 15 claims a human the agent "cannot impersonate" (false before W3); nothing states what the proofs are and are not; the owner has described the proofs as zero knowledge in conversation and on a resume line, and a reader who searches the repo for it finds nothing (R46).

Change: README gains "What this is", "What this is not" (no ZK, no MPC, no custody, not audited, prototype), "Status" (tests counts, deployments, known gaps with links to open items), "The guarantee, precisely" (the four on chain checks plus the two approval channels), "Evidence" (what a record contains, how to verify, what `PROOF OK` means and does not mean). `docs/architecture.md` adds the principal auth and passkey path; `docs/threat-model.md` row 6 is rewritten for principals and gains rows for approver token theft, pairing code leak and `state.json` disclosure; the architecture diagram shows the browser holding only a token.

Accept: every sentence in README that makes a technical claim names a module or a test; `rg -i 'zero.knowledge|zk|snark|mpc|threshold' README.md docs/` returns only the "What this is not" section.

Depends on: W3, W4 (so the docs describe merged code).

### W10. Base Sepolia anchoring verified end to end (P2, operational)

Why: `docs/history/2026-07-build-log.md` ends with "Base Sepolia deploy pending a funded key"; the hosted demo may be on the anvil fallback.

Change: with a funded operator key and a generated guardian key set as platform secrets, deploy per `deploy/DEPLOY.md`, anchor one batch, record the anchor transaction link in `deploy/DEPLOY.md` under "Verified deployments" with the date. Owner action; not a code change.

Depends on: W1, W2, W7.

---

## 8. Test matrix and the local gate

| Suite | Command | Count at revision `4657e58` | Owner of failures |
| --- | --- | --- | --- |
| Contracts | `cd contracts && forge fmt --check && forge test` | 50 (unchanged at 2026-10-17) | contracts changes |
| Python | `.venv/bin/ruff check python/ && .venv/bin/ruff format --check python/ && .venv/bin/pytest python/tests -q` | 154 (245 at 2026-10-17) | all Python changes; anvil must be on `PATH` |
| Frontend | `cd frontend && npm run lint && npm run typecheck && npm test` | 52 (64 at 2026-10-17) | frontend changes |
| Hygiene and scripts | `make test-scripts` | added 2026-10-17 | any change |
| Coverage floors | `make coverage` | added 2026-10-17 | Python changes |
| Evals | `make evals` | 51 cases, bypass 0 | policy, tools, contracts |
| Demo | `make demo` | exit 0 | end to end |
| E2E | `make e2e` | 1 | console changes (local Chrome) |

The local gate is all six for a change touching more than one layer, and at least the first three for any change (R20). Counts are expected to rise with every work item; a PR states the new counts.

CI parity: the GitHub workflow runs contracts, python and frontend. Until `make evals`, `make demo` and `make e2e` run in CI, their local run is pasted into the PR (R21).

Tooling notes: forge needs `solc 0.8.26`; when the binaries host is unreachable, place the static binary at `~/.svm/0.8.26/solc-0.8.26` and run with `--offline`. Python integration tests spawn anvil on a free port per session.

---

## 9. PR protocol and template

One concern per PR, under 400 changed lines excluding generated files and lockfiles (R37). Stacked PRs target the previous branch; GitHub retargets them to `main` as the stack merges. Description template, every heading present even when the answer is "none":

```
## Why
One paragraph: the defect or gap, with file:line on the parent commit.

## What changed
By file. Generated files listed separately.

## What was verified
Each command run, the pass count, the Foundry/Python/Node versions. Which suites CI ran, which were run locally and why.

## Tests whose expectations changed
Test name, old expectation, new expectation, reason. "None" if none.

## Not fixed
Known defects left in place, with the SPEC.md item or issue that owns them.

## Decisions for the owner
Anything chosen that SPEC.md did not settle, with the ADR number.
```

---

## 10. Definition of done (global)

A work item is done when all of the following hold:
1. Every acceptance criterion in its section 7 entry is met and each named test exists, failed on the parent commit, and passes.
2. The full local gate is green and the counts are recorded in the PR.
3. No AGENTS.md rule is violated; `scripts/check_hygiene.sh` passes.
4. Generated files were regenerated, not edited.
5. Documentation touched by the change describes the new behaviour; README, `docs/`, `.env.example` and `deploy/DEPLOY.md` agree with the code.
6. The PR follows section 9 and lists any decision taken in section 11 form.
7. CI on the PR is green, or the red job is explained under "What was verified" with the local run pasted.

---

## 11. Decisions

### 11.1 Taken (this revision)

- D1. No unauthenticated approval mode exists, not even for development. The dev stack generates and prints a dev token; the hosted demo uses passkeys with admin minted pairing codes. Rationale: an "open mode" flag is the first thing a demo leaves on.
- D2. Approver tokens are static bearer secrets configured in the environment, compared in constant time; no session, no JWT, no OAuth. Rationale: the operator population is a handful of named humans; a secret per human is auditable and revocable by redeploy. Sessions are a later item.
- D3. Passkey principals are identified as `passkey:<credential_id[:8]>`; a human name for a credential is a later item (store a label at pairing time).
- D4. The policy engine stays in process and file based; no policy service.
- D5. `state.json` carries addresses only; private keys come from the environment.
- D6. The anvil dev accounts remain usable on dev chains without configuration so `make demo` and the test suite stay zero config; they are refused on public chains by code, not by documentation.
- D7. The Vercel and Fly identifiers leave the tracked files; `fly.toml` keeps the structure with `app` set by `fly deploy --app`.
- D8. History files move to `docs/history/`; nothing is deleted from git history.
- D9. The three canned console instructions stay as the mock mode and as suggestions in anthropic mode.
- D10. `forge fmt` output of the Foundry version CI installs is the canonical format; local developers pin the same version via `foundryup --install <version>` noted in README.

### 11.2 Open for the owner

- O1. Public repository visibility. The owner said on 2026-10-16 he may take the repository private. MIT clones already exist; the decision does not retract them. Decide before sharing the link further.
- O2. Should the hosted demo expose any approval channel to anonymous visitors? Recommendation: no; a visitor sees the queue and the audit explorer, approving requires a pairing code from the owner.
- O3. Resume and conversation claims: the line "HITL API with ZK signing" and any mention of Groth16, MPC or threshold signing must be corrected to "signed approvals with Merkle anchored audit proofs" or the code must be built. Not a repository change; recorded here because R46 depends on it.
- O4. GitHub Actions versions: `actions/checkout@v4`, `setup-node@v4`, `setup-python@v5` are flagged for Node 20 deprecation; bump when the CI is green and observable.
- O5. Whether to merge the stacked PRs as one or in order; the recommendation is in order, so each one's CI run is attributable.

---

## 12. Glossary

- Authorization: the EIP 712 struct the guardian signs; consumed once on chain.
- Decision: the policy engine's verdict (`allow`, `deny`, `escalate`) with matched rules and the policy hash.
- Decision id: a uuid4 string assigned by the approval store; `sha256` of it is the on chain `decisionId`.
- Escalation: a proposal the policy routes to a human; a pending row in the approval store.
- Gated move: a token operation the plain path refuses with `GuardianRequired()`.
- Guardian: the key whose signature the contract requires for gated moves; held by the approval service.
- Principal: an authenticated approver (`token` or `passkey`).
- Proof: a Merkle inclusion proof of an audit record against a root stored in `AuditAnchor`; `PROOF OK` means untampered and included under an anchored root. It is not a zero knowledge proof.
- Human presence: the verified WebAuthn assertion embedded in an audit record.
