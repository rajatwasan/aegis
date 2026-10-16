# AGENTS.md: the Aegis operating contract

This file is the contract for everyone who changes this repository, human or
agent. Reviews cite rules by number (for example C1, T3, P2). A pull request
that breaks a numbered rule is not mergeable until the rule is satisfied or
the rule itself is changed in a separate pull request with an ADR.

`CLAUDE.md` points here. The active work is specified in `docs/specs/`; read
the newest spec before touching code. Historical build material lives in
`docs/history/` and is not an instruction source.

---

## 0. What Aegis is, and the invariants that must never regress

Aegis is a control plane that sits between an untrusted AI agent and actions
that move value. The agent proposes. A deterministic policy engine allows,
denies or escalates. Escalations wait for an authenticated human. Approved
gated actions execute only with an EIP 712 authorization signed by a guardian
key the agent never holds. Every decision is written to a hash chained, Ed25519
signed audit log whose Merkle roots are anchored on chain.

The invariants below are the product. Every change is measured against them.

- I1 The guardian key is never present in the agent process, the MCP server
  process, a browser, a log line, a test fixture outside `python/tests/`, or a
  default value in code.
- I2 No gated operation executes on chain without a guardian signature over
  the exact operation, and no guardian signature is produced without a
  resolved human decision by an authenticated approver.
- I3 The policy decision is a pure function of (proposal, on chain context,
  policy file). The policy hash is bound into every authorization.
- I4 The audit log is append only, hash chained and signed. Tampering with any
  record, including the human presence evidence inside it, breaks
  verification. Anchors on a public chain are checkable without trusting the
  server.
- I5 Aegis fails closed. Missing approval, expired approval, unreadable chain
  state, unverifiable configuration, or an unknown approver all stop the
  action. Liveness is never bought with safety.

If a change weakens any invariant, even in a dev path, it is a P0 finding.

---

## 1. Repository map and commands

| Path | What lives there |
| --- | --- |
| `contracts/` | Foundry project: `GuardianModule`, `GuardedToken`, `GuardedAsset1155`, `ComplianceRegistry`, `AuditAnchor`, tests incl. fuzz and invariant |
| `python/aegis/policy/` | Pure policy evaluator and typed boundary models |
| `python/aegis/audit/` | Canonical JSON, hash chain, Ed25519 signing, Merkle tree |
| `python/aegis/approval/` | FastAPI approval service, approver identity, guardian signer, sqlite store |
| `python/aegis/agent/` | LangGraph graph, typed tools, LLM providers, `AegisRuntime`, web3 client |
| `python/aegis/api/` | Guardian Console API: SSE bus, read models, agent runs, metrics |
| `python/aegis/mcpserver/` | stdio MCP server over the same runtime gate |
| `python/aegis/anchoring.py`, `cli.py` | Anchor batches and verify inclusion proofs |
| `python/aegis/devstack.py`, `demo.py`, `evals_harness.py` | Dev and demo tooling, adversarial evals |
| `frontend/` | Guardian Console (Vite, React 18, TypeScript strict, Vitest, Playwright) |
| `policies/` | YAML policies. `dev.yaml` is for local chains only |
| `evals/` | Injection corpus, harness, committed report |
| `docs/` | `architecture.md`, `threat-model.md`, `adr/`, `specs/`, `history/` |
| `deploy/` | Container image and start script for a hosted demo |

Commands (all from the repo root):

| Command | Purpose |
| --- | --- |
| `make setup` | venv, Python deps, forge deps |
| `make frontend-setup` | npm install under `frontend/` |
| `make lint` | forge fmt check, ruff check and format check |
| `make test` | forge suite, Python suite, frontend suite |
| `make evals` | adversarial eval harness, regenerates `evals/report.md` |
| `make e2e` | Playwright smoke over the full local stack |
| `make check` | lint, every test suite, evals, frontend build. The gate for commit and push |
| `make demo` | headless end to end story on a throwaway anvil |
| `make dev` | foreground local stack for humans. Never from automation |

---

## 2. Verification protocol

- V1 Green means `make check` exits 0 on the exact commit being pushed, run by
  the person or agent pushing it, on a clean working tree. "It passed earlier"
  and "CI will catch it" do not count.
- V2 Before every commit: run the suites that cover the changed surfaces.
  Before every push and before opening or updating a pull request: run
  `make check` in full and paste the summary counts (forge, pytest, vitest,
  evals, e2e when the UI or API changed) into the pull request.
- V3 If CI is down or misconfigured, the author runs everything locally and
  says so in the pull request. CI being unavailable never lowers the bar.
- V4 A failing test is never deleted, skipped or marked expected failure to
  get to green. The only exceptions are recorded in `BLOCKERS.md` with the
  symptom, three genuinely different attempts, and a hypothesis, and the
  pull request title carries `[blocked]`.
- V5 Any change under `frontend/src/features/` or to an API route the console
  calls runs `make e2e` locally and reports the result. Screenshots under
  `docs/screenshots/` are regenerated by that run when the screen changed.
- V6 Any change to `contracts/` runs `forge test` with fuzz and invariant
  tests at the configured runs, not a reduced count.
- V7 Verification output is evidence, not narrative. Paste commands and
  counts. Do not summarize a run you did not perform.

---

## 3. Correctness rules

These rules exist because the failure they prevent has already cost us. The
first is the most important rule in this file.

- C1 Missing is an error, never a value. A read that fails, a field that is
  absent, a response that does not parse, a sequence that is invalid, a
  balance that cannot be fetched, or an identity that cannot be verified is
  never replaced with zero, empty, false, "unknown", a previous value, or a
  default. It raises, returns an explicit error type, or surfaces a named
  state the human sees. Code that could be read as "treat the gap as normal"
  is a P0 finding whenever value or authority depends on it.
- C2 Fail closed at every gate. The only paths that execute a value moving
  action are an explicit `allow` from the policy engine with context fully
  read, or an explicit approval with a verified guardian signature.
  Everything else stops: deny, escalate, expire, or error.
- C3 No secret has a default. Guardian keys, approver tokens, deployer keys
  and API keys are read from configuration and the process refuses to start
  without them. A well known development key may appear only under
  `python/tests/` or in a file whose name contains `dev`, and never as a
  fallback value in code.
- C4 Identity comes from authentication, never from the request body. The
  approver of record is derived from the credential that authenticated the
  request. A client supplied name is display metadata at most.
- C5 State that crosses a trust boundary is signed where it is produced and
  verified where it is consumed: authorizations (guardian signature), audit
  records (Ed25519), passkey assertions (WebAuthn), anchors (on chain root).
- C6 The enforcer is separate from the executor. Nothing in the agent
  process, the graph, the tools or the MCP server can mint a guardian
  signature or call the approval endpoints that resolve a decision. If a
  code path would let the agent approve its own proposal, it is a P0.
- C7 Rate and window predicates have durable state and an explicit window.
  In memory counters are not policy state. A restart must not reset a daily
  limit, and a window must actually roll.
- C8 Configuration is checked against the world at startup. Chain id in the
  guardian domain equals the live chain id. The configured guardian signer
  address equals the token's on chain `guardian()`. The loaded policy hash
  equals what the service reports. On mismatch the service refuses to serve
  value moving routes and says why.
- C9 No silent fallbacks. A fallback (local anvil instead of a public chain,
  mock model instead of a real one, in memory store instead of a file)
  exists only behind an explicit opt in flag, is logged at startup, and is
  labeled on every human facing surface that shows its results.
- C10 Dev material is named dev and stays in dev paths: `policies/dev.yaml`,
  `scripts/dev-stack.sh`, `.aegis/dev`. Production code never references
  anvil accounts, localhost, or dev files by default.
- C11 Every mutation that can move value is idempotent or single use:
  idempotency keys on proposal submission, single use decision ids on chain,
  nonces on authorizations.
- C12 Time is explicit. Deadlines and TTLs are absolute UTC timestamps in
  seconds, computed once, compared against the same clock source, and shown
  to humans as countdowns derived from them.
- C13 Mixed worlds are refused. Figures, proposals or anchors from different
  chains, different policy hashes, or different deployments are never
  combined, merged or compared as if they were one.
- C14 Every error that stops an action carries enough to act on: which
  check failed, which inputs, and what the operator can do. No bare `500`.

---

## 4. Test rules

- T1 One test per surface the change touches: each API route, CLI command,
  console screen, graph node, and contract function that changed has at
  least one test exercising the changed behavior.
- T2 Every fixed defect gets a regression test named after the finding
  (`test_<area>_<finding>`), and the pull request shows the test failing on
  the parent commit and passing on the fix.
- T3 Never change a test expectation silently. If an assertion changes, the
  pull request states the old value, the new value, and why the new one is
  right. An unexplained expectation change is treated as a defect by
  reviewers.
- T4 Tests are deterministic and offline. No network, no real model keys, no
  wall clock dependence beyond injected timestamps. The only external process
  a test may spawn is anvil, owned and terminated by the fixture.
- T5 Committed artifacts are regenerated, not edited. `evals/report.md`,
  `frontend/openapi.json`, `frontend/src/api/schema.d.ts` and the screenshots
  under `docs/screenshots/` are produced by their commands in the same pull
  request that changes their inputs, and CI diffs them.
- T6 Every "cannot read" branch has a failure injection test: the registry
  call raises, the RPC times out, the sqlite row is missing, the credential
  is unknown. The test asserts the fail closed outcome, not just the absence
  of a crash.
- T7 Contract invariants are stated in the test file header and enforced by
  the invariant suite. A new gated path adds an invariant.
- T8 Frontend tests cover loading, empty, error and success states of each
  changed component, and the keyboard path where one exists.

---

## 5. Change rules

- G1 One concern per pull request, named by its spec item in the title
  (`W3: approver identity from authentication`). A pull request that mixes a
  fix with a refactor or a feature is split before review.
- G2 Fix the class, not the instance. When a defect is found, search the
  repository for the same pattern and fix every occurrence or list each one
  with a reason it is different. The search command and its result go in the
  pull request.
- G3 Spec first for anything that touches an invariant, a public interface,
  a stored format or a contract. The spec names acceptance criteria before
  code exists. Decisions with alternatives are recorded as ADRs in
  `docs/adr/`.
- G4 Keep pull requests small: a guideline of under 400 changed lines
  excluding tests and generated files. Larger changes are split by the
  spec's PR plan.
- G5 Do not reintroduce. Before changing a file, read its recent history
  (`git log -p --follow`) for the last three fixes and keep them intact.
- G6 No dead spec branches. A behavior described in a spec is either built
  and tested or marked `NOT BUILT` in the spec. Unreachable code written
  toward an unbuilt branch is removed.
- G7 Public claims match the repository. The claims register in the active
  spec is the source of truth for the README, the threat model, talks,
  applications and resumes. A claim is added there only when the code and a
  test exist.
- G8 Behavior and copy that a human sees (approval page, console, CLI
  output) are part of the interface: changes to them are tested and shown
  (screenshot or terminal capture) in the pull request.

---

## 6. Pull request protocol

- P1 Use `.github/pull_request_template.md`. Every section is filled; a
  section that does not apply says `none` and why.
- P2 Sections, in order: Why the change. Spec items closed. Change outline.
  Verification evidence (commands and counts, per rule V2). Tests added and
  tests whose expectations changed (per T3). Class search (per G2). Risks and
  rollback. Screens or terminal captures (per G8).
- P3 A pull request is mergeable when: `make check` evidence is present for
  the head commit, every reviewer finding is resolved or explicitly accepted
  by the repository owner, and the branch is rebased on `main`.
- P4 Findings are resolved in the pull request thread, one reply per
  finding, with the commit that fixes it. "Fixed" without a commit reference
  is not a resolution.
- P5 Commits are authored by the repository owner and carry no tool or AI
  attribution trailers. Conventional commit prefixes: `feat`, `fix`, `docs`,
  `test`, `chore`, `refactor`, scoped (`fix(approval): ...`).

---

## 7. Review harness

Reviews are adversarial and layered: at least two independent reviewers (human
or agent) read the branch without seeing each other's findings, then findings
are merged and deduplicated.

- H1 Finding format: severity, file and line, rule number, what is wrong,
  what would be right, and a test that would catch it.
  `P0 python/aegis/approval/config.py:12 C3: guardian key falls back to a
  public anvil key; require AEGIS_GUARDIAN_KEY and refuse to start.`
- H2 Severity: P0 weakens an invariant or moves value wrongly. P1 wrong
  behavior a user will hit, or a missing test on a value path. P2 quality,
  naming, docs, dead code.
- H3 Reviewers verify, they do not trust. Run the suites, run the failure
  injection, read the test that claims to cover the change.
- H4 The author replies to every finding. Disagreement is argued with a test
  or a spec citation, not with adjectives.
- H5 After fixes, a reviewer who did not write the fix re reviews the diff
  between the reviewed commit and the new head.
- H6 No self grading: the agent that wrote a change does not sign off its
  own review. A separate agent or the owner does.

---

## 8. Security, secrets and IP

- S1 No secrets in the repository: no keys, tokens, provider URLs with
  embedded keys, or `.env` files. `.env.example` holds placeholders that
  cannot work.
- S2 Anvil's well known accounts and keys appear only in `python/tests/`,
  `python/aegis/demo.py`, `python/aegis/evals_harness.py`, `policies/dev.yaml`
  and `scripts/`. Nowhere else.
- S3 Dependencies are pinned (`requirements.lock`, `package-lock.json`, forge
  submodules at tagged versions). Upgrades are their own pull request.
- S4 No global installs, no sudo, no changes outside the repository root,
  no long running foreground processes from automation.
- S5 Clean room: this is original MIT licensed work. Do not reference, name,
  quote or imitate proprietary compliance token designs or any employer's
  internal systems anywhere in the repository, including comments, tests and
  commit messages. Multi class assets are ERC 1155 token ids called "asset
  classes".
- S6 Anything written to the audit log is permanent evidence. Never write
  secrets, raw credentials or personal data into it.

---

## 9. Style

- Y1 Python 3.11+, ruff clean, full type hints, pydantic v2 models at every
  boundary, custom exception types for every failure a caller must handle.
- Y2 Solidity 0.8.26, OpenZeppelin v5 pinned per ADR 001, custom errors not
  revert strings, events for every state transition, NatSpec on public
  surfaces, forge fmt clean.
- Y3 TypeScript strict, ESLint clean, no `any` at module boundaries, all
  data fetching through the generated client, every component with loading,
  empty, error and success states.
- Y4 Documentation uses plain punctuation (no em dashes), short sentences,
  and names files, functions and rule numbers rather than describing them
  vaguely. The README quickstart must work by copy and paste.
- Y5 Names say what things are. A value that may be absent is typed as
  optional and handled at the boundary (rule C1); a boolean that means
  "unknown" is a defect.

---

## 10. Agent operating rules

For any agent (Claude Code or another harness) working unattended or
semi attended in this repository.

- A1 On start: read `AGENTS.md`, the newest file in `docs/specs/`, and the
  pull request or issue you are assigned. Do not start from `README.md`
  alone and do not read `docs/history/` for instructions.
- A2 Work from the spec's acceptance criteria. If a criterion is ambiguous,
  choose the option that fails closed, record the choice as an ADR, and say
  so in the pull request.
- A3 Never trade verification for completion. Finishing a task with a
  skipped suite, a weakened assertion, or an unexplained expectation change
  is a failed task, not a partial success.
- A4 After three genuinely different attempts at a failing step, stop,
  write the `BLOCKERS.md` entry (rule V4) and move to the next independent
  item. Do not loop.
- A5 Processes you start (anvil, uvicorn, vite, Playwright) are terminated
  before the task ends. Leave no servers running.
- A6 Push only branches whose head passed `make check`. Never push to `main`
  directly. Never force push a branch someone else may have.
- A7 Worktrees under `.claude/worktrees/` are disposable; anything worth
  keeping is pushed as a branch the same day.
- A8 Progress notes go in the pull request description and commits, not in
  loose files at the repository root.
- A9 Do not use network beyond package registries and the git remote.
- A10 When reviewing, follow section 7 exactly. When authoring, assume a
  reviewer who runs every command you claim to have run.

---

## Appendix A: definition of done for a work item

1. Acceptance criteria in the spec are each mapped to a test or a captured
   command output.
2. `make check` is green on the head commit, evidence pasted.
3. Every reviewer finding resolved per P4.
4. Claims register updated if a public claim changed.
5. ADR written if a decision had alternatives.
6. No new entry in `BLOCKERS.md`, or the pull request title carries
   `[blocked]`.

## Appendix B: the `make check` contract

`make check` runs, in order, and stops at the first failure: `make lint`,
`forge test`, `pytest python/tests -q`, `npm test` in `frontend/`,
`npm run typecheck` and `npm run build` in `frontend/`, `make evals` followed
by `git diff --exit-code evals/report.md`. `make e2e` is run separately when
rule V5 applies, because it needs a local browser.
