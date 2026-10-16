# Spec: October 2026 hardening (P0 to P2)

Status: ACTIVE. Owner: Rajat Wasan. Written 2026-10-16.
Governed by `AGENTS.md`. Every work item below cites the rule it satisfies.

---

## 1. Why this spec exists

An audit of `main` at `4657e58` (2026-07-25) found that the repository proves
less than its documentation and its author have claimed, and that several
shortcuts taken for the July hackathon are still load bearing. The first
reader with a reason to look closely is an investor who said he will read
the code. The failures to avoid are the ones already paid for elsewhere:
a missing value read as a normal value, a suite that was not run on the
commit under review, a committed artifact from a run that never happened, a
fix that covered one instance of a class, a claim the code does not back.

Three findings are P0:

1. The guardian signer falls back to a publicly known anvil key when
   `AEGIS_GUARDIAN_KEY` is unset. The hosted demo deployed with that key.
2. `POST /proposals/{id}/approve` and `/reject` take the approver's name
   from the request body. Any caller that can reach the API approves as
   anyone, which contradicts the README's claim of "a human it cannot
   impersonate".
3. Public claims (call, resume, prep docs) describe a zero knowledge proof
   and a 2 of 3 MPC signer. Neither exists anywhere in the repository, any
   branch, or any dangling commit on the author's machine.

The rest is P1 and P2: the console agent is hardwired to a scripted mock,
the daily limit lives in process memory, the default policy allowlists anvil
accounts, the dashboard shows a number read from a committed markdown file,
the hosted start script silently falls back to a throwaway chain, and the
overnight build harness and its logs are committed at the repository root.

## 2. Goals

- G1 After this spec, every sentence in `README.md` and `docs/threat-model.md`
  is backed by code and a test, and the claims register in section 4 is the
  only place a public claim is minted.
- G2 Invariants I1 to I5 in `AGENTS.md` hold on `main` with no dev path
  exception, and each has a failure injection test (rule T6).
- G3 A reader who clones the repository sees a product, not a hackathon
  workspace: no logs, no build loop scripts, no "Night Hack" documents at
  the root.
- G4 `make check` exists, is the single gate, and CI runs it in full
  including evals freshness and the browser smoke.

## 3. Non goals

- No new product surface. No new policy predicates, no new chains, no new
  agent tools.
- No zero knowledge proof and no MPC signer in this spec. See section 4 and
  W13 (NOT BUILT) for how they are handled.
- No change to the on chain contracts except where a test reveals a defect.
  The EIP 712 `Authorization` struct and domain are frozen.
- No rename of the project.

## 4. Claims register

The register is the source of truth for anything said about Aegis in the
README, the threat model, talks, applications and resumes (rule G7). Status
values: TRUE (code and test exist on `main`), PARTIAL (exists but not on
`main` or not tested), FALSE (claimed somewhere, not true today), NOT BUILT
(never claimed in the repository; recorded so nobody claims it by accident).

| # | Claim | Status at 4657e58 | Status after this spec | Evidence |
| --- | --- | --- | --- | --- |
| K1 | A gated transfer reverts on chain without a guardian EIP 712 signature over the exact operation | TRUE | TRUE | `contracts/test/GuardedToken.t.sol`, `Invariant.t.sol` |
| K2 | The guardian key is never in the agent process | TRUE in design, FALSE in config (default key in code) | TRUE | W1 |
| K3 | A compromised agent cannot approve its own proposal | FALSE (unauthenticated approve route) | TRUE | W2 |
| K4 | The approver of record is a human the agent cannot impersonate | FALSE | TRUE (token identity), stronger after W10 (passkey) | W2, W10 |
| K5 | Policy evaluation is deterministic and the policy hash is bound into each authorization | TRUE | TRUE | `test_policy_engine.py`, `test_policy_properties.py`, `signer.py` |
| K6 | Audit log is hash chained, Ed25519 signed, Merkle batched, tamper evident | TRUE | TRUE | `test_audit_log.py`, `test_merkle.py` |
| K7 | Anchors can land on a public chain and be checked without trusting the server | TRUE in code, hosted deployment unverified | TRUE in code, hosted deployment verified before it is cited | W8, W9 |
| K8 | 0% bypass across 49 injection attacks with a fully gullible model | TRUE (MockLLM gullible mode) | TRUE, stated with the mock qualifier | `evals/report.md`, W7 |
| K9 | The console runs a real LLM agent | FALSE (scripted MockLLM only) | TRUE when `AEGIS_LLM=anthropic`, labeled when mock | W3 |
| K10 | Daily limits are enforced | PARTIAL (per process memory, never rolls) | TRUE | W4 |
| K11 | Passkey (WebAuthn, Face ID) approvals with the assertion embedded in the signed audit record | PARTIAL (unmerged branch `guardian-touch`) | TRUE after PR 7: passkeys are bound to an approver id, the resolving assertion is in the signed record; under dual control only the resolving assertion is in the record (W14) | W10, W14 |
| K12 | Zero knowledge proof over approvals or compliance | NOT BUILT (said on a call and on a resume line) | NOT BUILT, recorded as future work W13 | none |
| K13 | 2 of 3 MPC guardian signer | NOT BUILT (said in interview prep) | NOT BUILT | none |
| K14 | Merkle commitment over the approval set | NOT BUILT (the Merkle tree is over audit records) | NOT BUILT | none |
| K15 | Open source, MIT | TRUE since 2026-10-11 | TRUE | `LICENSE` |
| K16 | Dual control (two distinct approvers) | TRUE in code, trivially defeated (names are free text) | TRUE | W2 |

Resume and talk line that is true today and stays true after this spec:
"HITL control plane for AI agents: deterministic policy gate, EIP 712 guardian
signed approvals, hash chained Ed25519 audit log with Merkle roots anchored on
chain, WebAuthn approver presence (after W10), 0% bypass across 49 injection
attacks with a fully compromised model." Do not say ZK, MPC or Groth16 until a
work item exists, is built and is tested.

## 5. Decisions

Each decision gets an ADR in `docs/adr/` when implemented. Alternatives are
listed so a reviewer can check the choice, not just the result.

### D1 Approver identity comes from a server held credential, not the request body

Chosen: bearer tokens per approver. An approver is created by an operator
command, receives a 256 bit random token once, and the server stores only
`sha256(token)`. Approve and reject require `Authorization: Bearer <token>`;
the identity written to approvals, resolutions and audit records is the
approver id resolved from the token. The body carries only `comment`.

Alternatives considered:

- A. EIP 712 signed approvals from a registered approver key (approver signs
  `ApprovalIntent{decisionId, action, commentHash, nonce, deadline}`). Strongest
  binding and replay safe, but the console has no signer today; it needs a
  wallet or an in browser key. Recorded as the next step after W10, not now.
- B. Passkey only (merge `guardian-touch`, delete the console path). Strong,
  but the desktop console loses its approve button on machines without a
  platform authenticator, and the branch currently routes into the open
  endpoint, so it does not fix the hole by itself.
- C. Keep the body field and add an allowlist of names. Rejected: a name is
  not a credential (rule C4).

Consequences: breaking API change on approve and reject (old clients get
`401`). A dev approver is created by the dev scripts and printed once. The
passkey path (W10) binds a credential to an approver id created this way.

### D2 The guardian key has no default and is checked against the chain at startup

Chosen: `AEGIS_GUARDIAN_KEY` is required by `ApprovalConfig.from_env` and
`ApiConfig.from_env`; the process exits with a one line reason if it is
absent. Known development keys (anvil's ten default accounts) are refused
unless `AEGIS_ALLOW_DEV_KEYS=true`, which only the dev scripts set. When chain
state exists (`state.json`), the API verifies at startup that
`GuardedToken.guardian()` equals the signer address and refuses to start on
mismatch.

Alternatives: auto generate a key on first start like the audit key.
Rejected: the guardian address is a constructor argument of the token, so a
generated key silently creates a signer the chain will reject (rule C8).

### D3 There is no implicit policy file

Chosen: `policies/default.yaml` becomes `policies/dev.yaml` with a header
stating it allowlists anvil accounts and is for local chains only.
`ApprovalConfig.policy_path` has no default; `from_env` requires
`AEGIS_POLICY_PATH`; every dev and demo script passes `policies/dev.yaml`
explicitly.

Alternative: keep the default and add a warning. Rejected under C9 and C10.

### D4 The console agent uses the configured provider

Chosen: `POST /agent/run` builds the graph with `provider_from_env()`. In mock
mode the three canned instructions remain and anything else returns `400`
with the list. In `anthropic` mode any instruction is sent to the model, the
chips are examples, and the console labels the mode in the status bar.
`AnthropicLLM` gets a configurable model id, a system prompt that states the
JSON contract, strict parsing with one retry on malformed output, and a
timeout. Tests use an `httpx.MockTransport`; no network (rule T4).

### D5 The daily limit is derived from the audit log over a rolling window

Chosen: a `SpendLedger` reads executed transfers (actor `agent`, status
`executed`, operation transfer) from the audit log and sums amounts per
sender inside a trailing window (`AEGIS_DAILY_WINDOW_SECONDS`, default 86400).
`AegisRuntime.build_context` consults the ledger; the in memory dict is
removed. A restart cannot reset the limit because the log is the state.

Alternative: a sqlite counter table. Rejected: a second source of truth that
can drift from the log; the log already records every execution.

### D6 Dashboard numbers carry their provenance

Chosen: `/metrics.injections` includes `source` (the report path), the
report's generation timestamp parsed from a header line the harness writes,
and the mode (`gullible MockLLM`). The dashboard card reads "last eval run,
<date>". CI regenerates the report and fails on diff (rule T5).

### D7 Local chain fallback is explicit

Chosen: `deploy/start.sh` exits non zero when `AEGIS_RPC_URL` and
`AEGIS_DEPLOYER_KEY` are set but the public deploy fails, unless
`AEGIS_ALLOW_LOCAL_FALLBACK=true`. With no RPC configured at all, local anvil
is the documented development mode and is logged as such.

### D8 The overnight build harness is history, not instructions

Chosen: `claude.md`, `PROMPT.md`, `FRONTEND.md`, `PROGRESS.md`, `run.sh` and
`run-frontend.sh` move to `docs/history/overnight-build/` with a README
explaining what they were. `CLAUDE.md` at the root is a three line pointer to
`AGENTS.md`. Logs and the self score artifacts are deleted. `BLOCKERS.md`
stays at the root because `AGENTS.md` V4 uses it.

Alternative: delete the harness entirely. Rejected: it is provenance, and the
owner decides what to publish about how the repository was built; moving it
keeps the choice open.

### D9 The passkey branch merges after the identity change, not before

Chosen: rebase `guardian-touch` onto `main` after W2 lands, route
`/guardian/decide` through the same internal resolver as the token path with
`auth_method="passkey"`, and bind pairing to an existing approver id (pairing
requires that approver's bearer token). The branch's own fly.toml edits are
dropped in favor of W9's.

### D10 Demo destinations come from the deployment state

Chosen: `devstack` and `demo.deploy` write `parties` (compliant list, frozen
list) into `state.json`; `agent_runner.canned_plans` reads them. If the state
lacks `parties`, agent runs return `503` with the reason (rule C1), never a
built in address.

### D11 Ownership of commits

Chosen: all commits authored by the repository owner, no tool attribution
trailers (AGENTS.md P5). Already the case on `main`; the dropped pre amend
commits that carried trailers are unreachable and stay that way.

## 6. Work items

Each item: priority, the problem with file references, required behavior,
acceptance criteria (AC), tests, and the PR that carries it. Acceptance
criteria are written so a reviewer can check each with one command or one
test name.

### W0 Operating contract and spec (this document)

Priority P0. PR 1.

- AC0.1 `AGENTS.md` exists at the root with numbered rules in sections 0 to
  10 and appendices A and B.
- AC0.2 `CLAUDE.md` at the root points to `AGENTS.md` and nothing else.
- AC0.3 `.github/pull_request_template.md` exists with the sections of
  AGENTS.md P2.
- AC0.4 `docs/history/overnight-build/` holds the former `claude.md`,
  `PROMPT.md`, `FRONTEND.md`, `PROGRESS.md`, `run.sh`, `run-frontend.sh` and
  a `README.md` describing them. The root holds none of them.
- AC0.5 `run.log`, `loop.out`, `nohup.out`, `aegis_profile.json`,
  `selfscore.py` are removed from the tree and `.gitignore` covers
  `nohup.out` and `aegis_profile.json`.
- AC0.6 `git grep -l "Night Hack"` returns nothing outside `docs/history/`
  and `deploy/DEPLOY.md`, which W9 rewrites.

### W1 Guardian key: no default, dev key guard, on chain binding check

Priority P0. Rules C3, C8, C10, I1. PR 2. Decision D2.

Problem:

- `python/aegis/approval/config.py` line 11 defines `DEFAULT_GUARDIAN_KEY`
  as anvil account 9's private key and line 18 uses it as the field default.
- `python/aegis/api/config.py` line 18 imports it and line 48 falls back to
  it when `AEGIS_GUARDIAN_KEY` is unset.
- `.env.example` line 28 ships the same key as the working value.
- `python/aegis/devstack.py` line 125 writes `"guardian": ACCOUNTS[9]` into
  `state.json` regardless of configuration, so a hosted deployment's token is
  constructed with anvil account 9 as guardian.
- No code compares the signer address with `GuardedToken.guardian()`.

Required behavior:

- `ApprovalConfig.guardian_key` has no default. `ApprovalConfig.from_env` and
  `ApiConfig.from_env` raise `ConfigError("AEGIS_GUARDIAN_KEY is required")`
  when the variable is absent or empty; `python -m aegis.api` prints that one
  line to stderr and exits 2.
- A new module `python/aegis/devkeys.py` holds the ten anvil default private
  keys and addresses (the only place outside tests they appear, rule S2) and
  `is_dev_key(key) -> bool`. `from_env` refuses a dev key unless
  `AEGIS_ALLOW_DEV_KEYS=true`.
- `devstack.run` takes the guardian address from the configured key
  (`AEGIS_GUARDIAN_KEY`, required) and passes it to `demo.deploy`; `state.json`
  records the derived address.
- `create_api_app` calls `verify_guardian_binding(state, signer)` when
  `state.json` exists: reads `token.guardian()` over the state's RPC and
  raises `GuardianMismatch(expected, actual)` on inequality. The message names
  both addresses. If the RPC is unreachable the API still refuses to start
  with `GuardianUnverified(reason)`; the operator fixes the chain, not the
  check (rule I5).
- `/metrics.chain` gains `guardian_address` and `guardian_verified: true`
  so the console can show the binding.
- `scripts/dev-stack.sh`, `scripts/demo.sh`, `deploy/start.sh`,
  `docker-compose.yml` set the key explicitly and, for the dev scripts,
  `AEGIS_ALLOW_DEV_KEYS=true`. `deploy/DEPLOY.md` instructs generating a fresh
  guardian key as a secret, separate from the deployer key.

Acceptance criteria:

- AC1.1 `grep -rn "2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6" --include=*.py python/aegis` matches only `python/aegis/devkeys.py`.
- AC1.2 `AEGIS_GUARDIAN_KEY= python -m aegis.api` exits 2 with the one line
  message (captured in the PR).
- AC1.3 `test_config_guardian_key_required` passes: `from_env` without the
  variable raises `ConfigError`.
- AC1.4 `test_config_dev_key_refused_without_opt_in` and
  `test_config_dev_key_allowed_with_opt_in` pass.
- AC1.5 `test_api_refuses_start_on_guardian_mismatch` passes: a `state.json`
  pointing at the anvil fixture token with a different signer raises
  `GuardianMismatch` from `create_api_app`.
- AC1.6 `test_api_starts_when_guardian_matches` passes and `/metrics.chain`
  shows `guardian_verified: true` and the matching address.
- AC1.7 `test_api_refuses_start_when_chain_unreachable` passes (RPC URL to a
  closed port, `GuardianUnverified`).
- AC1.8 `make demo` and `make e2e` still exit 0 with the explicit dev key.
- AC1.9 `.env.example` contains no working private key; the guardian line
  reads `AEGIS_GUARDIAN_KEY=0xreplace-with-a-key-only-the-approval-service-holds`.
- AC1.10 Class search (rule G2) for other secrets with defaults is pasted in
  the PR: `grep -rn "os.environ.get(\"AEGIS_.*KEY\"" python/aegis` with each
  hit resolved.

### W2 Authenticated approvers on approve and reject

Priority P0. Rules C1, C4, C6, I2, K3, K4, K16. PR 3. Decision D1.

Problem:

- `python/aegis/approval/app.py` lines 40 to 42 define `ActionIn(approver,
  comment)`; lines 125 to 164 (`approve`) and 166 to 174 (`reject`) record
  `body.approver` as the identity. No authentication exists.
- `frontend/src/lib/approver.ts` stores a free text name in localStorage and
  `frontend/src/api/queries.ts` lines 173 to 182 send it in the body.
- Dual control (line 134, `required = 2`) compares these free text names, so
  one person typing two names satisfies it.
- The threat model row 6 admits "depends on approver auth in a real
  deployment" while the README's second paragraph claims impersonation is
  impossible.

Required behavior:

- New table `approvers(id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE, created_at REAL NOT NULL, revoked_at REAL)`
  in the approval sqlite database. Token generation:
  `secrets.token_urlsafe(32)`; stored as `sha256` hex; compared with
  `hmac.compare_digest`.
- CLI (`python/aegis/cli.py`): `aegis approver add <id> --name "<display>"`
  prints the token exactly once and exits; `aegis approver revoke <id>`;
  `aegis approver list` (ids, names, created, revoked; never hashes). The CLI
  uses the same db path resolution as the API (`AEGIS_DB_PATH` or
  `AEGIS_STATE_DIR/approvals.db`).
- `python/aegis/approval/identity.py`: `resolve_approver(store, authorization
  header) -> Approver` raising `Unauthenticated` (`401`) for a missing or
  malformed header, an unknown token, or a revoked approver. No distinction in
  the response body between unknown and revoked beyond a log line.
- `ActionIn` becomes `{comment: str}` with `extra="forbid"`, so a stale client
  sending `approver` gets `422` with the field named.
- Internal resolver `resolve_decision(decision_id, approver: Approver,
  action: "approve" | "reject", comment, evidence: dict | None)` is the only
  code path that writes an approval, signs an authorization or writes the
  resolution audit record. Both HTTP routes call it; W10's passkey route will
  too. Approvals store `{"approver": approver.id, "display_name": ...,
  "auth_method": "token", "comment": ..., "ts": ...}`. Audit `human_action`
  carries `approver` and `auth_method`.
- Dual control compares `approver.id`; a second approval by the same id
  returns `409` as today.
- `GET /approvers/me` returns the authenticated approver's `id` and
  `display_name` (for the console header), `401` otherwise.
- Console: `ApproverIdentity` becomes an "Approver token" input (type
  password) stored in localStorage under `aegis.approver_token` (per viewer
  convenience, wrapped in try/catch as before). `client.ts` attaches
  `Authorization: Bearer` through an openapi fetch middleware. The header
  shows the resolved display name from `/approvers/me`, or "not signed in"
  with the approve controls disabled. A `401` on approve surfaces as "token
  rejected" and clears nothing automatically.
- Dev bootstrap: `scripts/dev-stack.sh` and `scripts/demo.sh` create approver
  `dev` on a fresh database and print the token once; `demo.py` approves
  through the resolver with that identity. Playwright reads the token from
  the dev stack's printed output file (`.aegis/dev/dev-approver.token`,
  gitignored) and sets localStorage before the run.
- `python/aegis/approval/page.py` (single file HTML approval page) gets a
  token field and sends the header; it is a dev convenience and says so in
  its title.
- README and threat model updated in the same PR: row 6 residual becomes
  "approver credential theft; mitigated by revocation and, after W10, by
  passkey presence".

Acceptance criteria:

- AC2.1 `test_approve_without_token_401`, `test_approve_with_unknown_token_401`,
  `test_approve_with_revoked_token_401` pass and assert that no approval row,
  no signature and no audit record were written (fail closed, rule T6).
- AC2.2 `test_approve_identity_comes_from_token` passes: the approval row and
  the audit record carry the approver id from the token; a body `approver`
  field yields `422`.
- AC2.3 `test_dual_control_requires_two_distinct_identities` passes: the same
  token twice is `409`; two tokens resolve and sign.
- AC2.4 `test_reject_requires_token` passes.
- AC2.5 `test_cli_approver_add_prints_token_once_and_stores_hash` passes:
  the db holds a 64 hex char hash, not the token; `list` never prints hashes.
- AC2.6 `test_mcp_server_has_no_approve_tool` passes (asserts the tool list
  is exactly the four read or propose tools) and
  `test_runtime_cannot_resolve_decisions` passes (the runtime's approval
  client has no bearer token and `approve` through it is `401`), proving C6.
- AC2.7 Frontend: `ApprovalsPage.test.tsx` and `ConsolePage.test.tsx` updated
  with the token flow; expectations that changed are listed in the PR with
  old and new values (rule T3). New tests: token missing disables approve;
  `401` shows "token rejected" and restores the row.
- AC2.8 `make e2e` passes with the dev approver token flow and the
  screenshots under `docs/screenshots/` are regenerated (rule V5).
- AC2.9 `grep -rn "approver" python/aegis | grep -i "body\." ` returns
  nothing: no route reads an approver from a body.
- AC2.10 README second paragraph and `docs/threat-model.md` row 6 match the
  claims register K3 and K4.

### W3 Console agent runs the configured provider

Priority P1. Rules C9, K9. PR 4. Decision D4.

Problem:

- `python/aegis/api/agent_runner.py` line 189 constructs `MockLLM(script=plan)`
  unconditionally; lines 145 to 151 reject any instruction outside the three
  canned ones. `provider_from_env` in `python/aegis/agent/llm.py` line 94 is
  never called by the API.
- `AnthropicLLM` (lines 55 to 91) hardcodes a model id, has no system prompt,
  no JSON error handling, and no test.

Required behavior:

- `AgentRunner.start` selects the provider with `provider_from_env()`. Mock
  mode keeps the canned plans and the `400` for unknown instructions, with
  the message naming mock mode. Anthropic mode accepts any instruction and
  builds the graph with the real provider.
- `AnthropicLLM`: model from `AEGIS_ANTHROPIC_MODEL` (no silent default to an
  unknown id; required when `AEGIS_LLM=anthropic`), a system prompt stating
  the exact JSON contract and the tool names from the registry, `max_tokens`
  and timeout from config, strict parsing (`json.loads` of the first text
  block; on failure one retry with the parse error appended; on second
  failure raise `ProviderError`, which the runner surfaces as a `failed` step
  with the reason, rule C1). `httpx.Client` injected for tests.
- `GET /agent/instructions` returns `mode` (`mock` or `anthropic`) and the
  chips; the console status bar shows the mode.

Acceptance criteria:

- AC3.1 `test_runner_mock_mode_rejects_unknown_instruction` passes (existing
  behavior, message updated).
- AC3.2 `test_runner_anthropic_mode_uses_provider` passes: with
  `AEGIS_LLM=anthropic` and a `MockTransport` returning a scripted sequence,
  a free text instruction drives the graph to an escalation.
- AC3.3 `test_anthropic_llm_rejects_malformed_json_after_retry` and
  `test_anthropic_llm_requires_model_and_key` pass.
- AC3.4 `test_instructions_endpoint_reports_mode` passes.
- AC3.5 Console: `ConsolePage.test.tsx` covers the mode badge for both
  values.

### W4 Durable, windowed daily spend ledger

Priority P1. Rules C7, K10. PR 5. Decision D5.

Problem: `python/aegis/agent/runtime.py` line 37 `self.daily_spent: dict`
grows forever within a process and resets on restart; `build_context` (line
58) and `handle` (lines 77 to 79) use it. The policy predicate
`within_daily_limit` therefore holds against whatever a process has seen.

Required behavior:

- `python/aegis/agent/spend.py`: `SpendLedger(audit: AuditLog, window_seconds:
  int, clock: Callable[[], float])` with `spent_by(sender: str, at: float)
  -> int` summing `amount` over audit records where `actor == "agent"`,
  `policy_result.status == "executed"`, `proposal.operation == TRANSFER`,
  `proposal.from == sender`, and `at - window < ts <= at`. Reads are over the
  log file, which is the single source of truth.
- `AegisRuntime` takes a `SpendLedger` (constructed by callers from the same
  audit log) and `build_context` fills `daily_spent` from it for the parties
  of the proposal. The dict attribute is removed.
- Window from `AEGIS_DAILY_WINDOW_SECONDS` (default 86400), surfaced in
  `/policy` so the console can show "per 24h".

Acceptance criteria:

- AC4.1 `test_spend_ledger_sums_only_executed_transfers_in_window` passes
  with an injected clock (records at window edge included and excluded
  correctly).
- AC4.2 `test_runtime_limit_survives_restart` passes: a runtime executes
  transfers, a new runtime over the same log sees the spend and the policy
  escalates the next one.
- AC4.3 `test_runtime_limit_rolls_after_window` passes.
- AC4.4 Existing anvil integration test counts unchanged, or changes listed
  per T3.

### W5 Explicit policy file, dev policy named dev

Priority P2. Rules C9, C10. PR 8. Decision D3.

- AC5.1 `policies/default.yaml` no longer exists; `policies/dev.yaml` exists
  with a header comment naming it dev only and listing why each allowlisted
  address is an anvil account.
- AC5.2 `ApprovalConfig.from_env` raises `ConfigError("AEGIS_POLICY_PATH is
  required")` when unset; test exists.
- AC5.3 Every script and test passes the path explicitly; `grep -rn
  "default.yaml"` returns nothing.

### W6 Demo destinations from deployment state

Priority P2. Rules C1, C10, S2. PR 8. Decision D10.

- AC6.1 `state.json` written by `devstack` contains `parties.compliant` and
  `parties.frozen`.
- AC6.2 `python/aegis/api/agent_runner.py` contains no literal address;
  `grep -n "0x[0-9a-fA-F]\{40\}" python/aegis/api/agent_runner.py` is empty.
- AC6.3 `test_runner_without_parties_in_state_returns_503` passes.
- AC6.4 A `state.json` without `parties` is not reused by `devstack --reuse`;
  the world is redeployed so the record and the chain agree.

### W7 Metrics provenance for the eval number

Priority P2. Rules C9, T5. PR 4 (AC7.3) and PR 8. Decision D6.

- AC7.1 The harness writes `generated_at` and `mode: gullible MockLLM` to
  the report header; `parse_eval_report` returns them; `/metrics.injections`
  carries `source`, `generated_at`, `mode`.
- AC7.2 Dashboard card label reads "injections blocked, last eval run
  <date>"; `DashboardPage.test.tsx` asserts the label.
- AC7.3 CI step `make evals && git diff --exit-code evals/report.md` exists
  (PR 4); after AC7.1 the diff ignores the `generated_at` line
  (`git diff -I '^generated_at: '`) and `make evals-check` restores the
  committed line when nothing else changed, so a green check leaves the tree
  clean.

### W8 Explicit local chain fallback in the hosted start script

Priority P2. Rule C9. PR 9. Decision D7.

- AC8.1 With `AEGIS_RPC_URL` and `AEGIS_DEPLOYER_KEY` set and the deploy
  failing, `deploy/start.sh` exits 1 unless `AEGIS_ALLOW_LOCAL_FALLBACK=true`;
  a shell test under `python/tests/test_start_script.py` runs the script with
  a stub `python` on `PATH` and asserts both outcomes.
- AC8.2 Startup log names the mode in one line: `public base-sepolia` or
  `local anvil (dev)` or `local anvil (FALLBACK, opted in)`.

### W9 Hosted deployment documents and configuration

Priority P2. Rules C3, G7, Y4. PR 9. Decision D8.

- AC9.1 `deploy/DEPLOY.md` is a deployment guide with no event references,
  covering: generate a guardian key as a secret, generate a deployer key,
  fund it, set `AEGIS_POLICY_PATH`, create the first approver with the CLI
  inside the machine, verify `/metrics.chain.guardian_verified`.
- AC9.2 `fly.toml` carries no personal preview URLs; CORS origins are
  documented as a secret or env set at deploy time.
- AC9.3 `docker-compose.yml` either runs the real API entrypoint with the
  required env (`python -m aegis.api`) or is removed; today it references
  `aegis.approval.app:app`, which is a factory, not an app.
- AC9.4 The hosted demo is redeployed with a fresh guardian key and the
  approver flow before any public link to it is shared again; until then the
  README does not link it.

### W10 Merge the passkey path

Priority P1. Rules C4, C5, K11. PR 7. Decision D9.

- AC10.1 `guardian-touch` replayed on top of PR 6 (its three commits cherry
  picked); conflicts in `fly.toml` (dropped, W9), `frontend/openapi.json`
  and `schema.d.ts` resolved by regeneration (rule T5), not by hand edits.
  `npm run gen:api` now formats its output so the snapshot regenerates
  byte for byte.
- AC10.2 `/guardian/pair/start` requires a bearer token; the code it mints
  and the credential enrolled with it are bound to that approver id
  (`pairing_codes.approver_id`, `guardian_credentials.approver_id`).
  `/guardian/decide` resolves the bound approver (revoked approvers are
  refused with 401 and nothing changes), then calls
  `resolve_decision(..., Approver(auth_method="passkey"), evidence=assertion)`.
  Nothing else in `/guardian` carries a bearer token: there the passkey is
  the credential.
- AC10.3 `test_guardian_touch.py` and `test_guardian_audit.py` pass with
  their intent unchanged. Expectation changes, listed per T3: the console
  path in the audit test authenticates with a bearer token (it sent
  `approver` in the body, the pre W2 shape); pairing in both files runs the
  real flow (`pair/start` with a token, `pair/complete` with a registration
  the library verifies) instead of inserting a credential row; the stubbed
  `verify_authentication_response` is gone, every assertion is produced by a
  software authenticator (`tests/passkeys.py`) and verified for real.
- AC10.4 `docs/adr/004-passkey-pairing-challenge.md` lands with the merge;
  `docs/adr/008-passkeys-are-approver-credentials.md` records the binding
  and where the evidence lives.
- AC10.5 README "Guardian Console" section documents the phone flow with
  `docs/screenshots/guardian.png`, captured by `make e2e` from a second
  Playwright spec (`e2e/guardian.spec.ts`) that runs the whole phone flow
  with Chromium's virtual authenticator, so the server verifies a real
  WebAuthn registration and assertion in CI.
- AC10.6 Evidence placement: the proposal row keeps the assertion with the
  approval it belongs to (`approvals[i].evidence`) and, for the action that
  resolved the decision, in `proposals.evidence`; the audit record embeds
  that resolving assertion as `human_presence` before hashing. Passkey
  tables that predate the approver binding make the service refuse to start
  with the fix named (C9); the dev stack recreates its database anyway.

### W11 README, threat model and architecture match the register

Priority P1. Rule G7. PR 9 (final pass; PR 2 and PR 3 make their own
edits as they land).

- AC11.1 Every claim in `README.md` maps to a row in section 4 with status
  TRUE.
- AC11.2 `README.md` gains a section "What Aegis does not do" listing K12,
  K13, K14 as not built, so the absence is a statement, not a discovery.
- AC11.3 `docs/threat-model.md` rows 6 and 8 updated; residual risks list
  approver credential theft and guardian key custody.
- AC11.4 `docs/architecture.md` sequence diagram shows the authenticated
  approver and the guardian binding check.

### W12 `make check`, CI parity, browser smoke in CI

Priority P1. Rules V1, V2, T5. PR 8.

- AC12.1 `make check` exists per AGENTS.md appendix B and exits non zero on
  the first failure.
- AC12.2 CI runs `make check` (contracts, python, frontend, evals freshness)
  and a separate `e2e` job that installs Playwright chromium, boots the stack
  through Playwright's webServer and runs the smoke.
- AC12.3 CI runs on pull requests and on `main`; both are required checks
  (documented in the PR; branch protection is set by the owner).
- AC12.4 The PR template is used by the PRs of this spec.

### W14 Every assertion in the signed record under dual control

Priority P2. Rules I4, C9. Not scheduled; recorded by PR 7.

With `dual_control`, two approvals resolve a decision. Each approval's
assertion is kept on the proposal row, but the audit record's
`human_presence` is one object: the assertion of the approval that completed
the quorum. The first approver's assertion is therefore in the store, not in
the signed record. The record still names both approvers and both auth
methods (`human_action.approvers`, `human_action.auth_methods`), so it is not
misleading, only incomplete.

- AC14.1 `human_presence` becomes a list aligned with `human_action.approvers`
  (one entry per approval, `null` for token approvals), or the record gains a
  per approval evidence list; the console's audit view and
  `anchoring.verify_decision` tests cover both shapes.
- AC14.2 Failure injection: tampering with the first approver's assertion in
  a dual control record breaks the proof.

### W13 Approval set proof (NOT BUILT)

Recorded so the claim has a home. A Groth16 (snarkjs) or Noir circuit proving
"the approval set is a subset of registered approver credentials and meets
quorum" with the approval set commitment as public input, a generated
Solidity verifier, and `aegis verify` checking the proof. Estimated two to
three working days including tests. Not scheduled. Nobody says ZK until this
item is TRUE in the register.

## 7. PR plan and order

| PR | Branch | Items | Depends on | Size guideline |
| --- | --- | --- | --- | --- |
| 1 | `hardening/01-agents-spec` | W0 | none | docs only |
| 2 | `hardening/02-guardian-key` | W1 | 1 | small |
| 3 | `hardening/03-approver-identity` | W2 | 2 | medium (API, CLI, console) |
| 4 | `hardening/04-make-check-ci` | W12, AC7.3 | 1 | small |
| 5 | `hardening/05-console-provider` | W3 | 3 | small |
| 6 | `hardening/06-spend-ledger` | W4 | 3 | small |
| 7 | `hardening/07-passkey-merge` | W10 | 6 | medium (mostly existing code) |
| 8 | `hardening/08-p2-cleanup` | W5, W6, W7 | 7 | medium |
| 9 | `hardening/09-deploy-docs` | W8, W9, W11 | 8 | medium (mostly docs) |

Each PR carries its own `make check` evidence. PR 4 lands early so later PRs
are gated by the full check in CI.

## 8. Verification matrix

| Invariant | Positive test | Failure injection test |
| --- | --- | --- |
| I1 guardian key isolation | AC1.1, AC2.6 | AC1.4 (dev key refused) |
| I2 no signature without authenticated decision | AC2.2, AC2.3 | AC2.1, AC2.4 |
| I3 deterministic policy, hash bound | existing `test_policy_*` | AC5.2 (no implicit policy) |
| I4 tamper evident log | existing `test_audit_log` tamper tests, W10 evidence tamper test (`test_guardian_audit.py`) | AC4.1 (ledger reads only signed records), W10 bad signature, wrong challenge, replayed counter, revoked approver (`test_guardian_touch.py`) |
| I5 fail closed | AC1.5, AC1.7, AC6.3, AC8.1 | AC3.3 (provider error becomes failed step) |

## 9. Rollback

Every PR is independently revertable. PR 3 changes the approve API shape;
rolling it back restores the unauthenticated route, so if PR 3 must be
reverted the hosted demo is taken down first (AC9.4 holds until it is
redeployed). Database migrations (approvers table) are additive and need no
reversal.

## 10. Open questions for the owner

1. D1: bearer tokens now, signed approvals (alternative A) after W10. Confirm,
   or ask for A now and accept the console signer work.
2. D8: keep the overnight harness under `docs/history/` or delete it.
3. The hosted Fly machine is running with anvil account 9 as guardian. Take
   it down now and redeploy after PR 2 and PR 3, or leave it up unlinked.
4. Naming in the console: "approver" (current) or "guardian" for the human.
   The contract calls the key the guardian; the human is the approver. Keep
   both words with that meaning unless you object.
5. W13: schedule or leave recorded.
6. W14: schedule the dual control evidence shape, or leave recorded.

## 11. Lessons encoded, with the rule that carries each

| What happened elsewhere | Rule here |
| --- | --- |
| A missing or unreadable value treated as zero, empty or "no account" | C1, T6 |
| Six of the PR's own tests failing on the reviewed commit; CI not running the suite | V1, V2, V3 |
| A test expectation inverted without a note | T3 |
| A committed audit record from a run that skipped the browser suite | T5, V5 |
| A fix that covered the instance, not the class, across five PRs | G2 |
| A fixed bug reintroduced | G5, T2 |
| Spec branches left as dead code | G6 |
| One PR carrying eight concerns | G1, G4 |
| Claims ahead of code | G7, section 4 |
