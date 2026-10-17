# AGENTS.md: rules for anyone, human or agent, changing this repository

Aegis is an authority and evidence layer for AI agents that act on money. An agent proposes; a deterministic policy decides; a human approves through an authenticated channel; a guardian key the agent never holds signs; the chain reverts without that signature; every decision lands in a signed, hash chained, anchored audit log. Every rule below protects one of those properties. Rules are numbered and one per line so a review can cite `AGENTS.md:L<line>` or `R<n>`. SPEC.md holds the module contracts and the work items; this file holds the rules that apply to every change.

## A. Security invariants (a change that breaks one is wrong even if every test passes)

R1. The guardian key lives only in the approval service process. No agent, tool, MCP client, browser, log line, state file, API response, or test fixture outside `python/tests/` and `python/aegis/devchain.py` may hold or print it.
R2. There is no default secret anywhere. A missing `AEGIS_GUARDIAN_KEY`, `AEGIS_APPROVER_TOKENS`, `AEGIS_ADMIN_TOKEN`, `AEGIS_OPERATOR_KEY` or `AEGIS_POLICY_PATH` is a startup error with a message naming the variable, never a fallback to a built in value.
R3. The ten anvil dev mnemonic keys and addresses are dev chain only. Code that targets a chain whose `chains.ChainMeta.public` is true must refuse any of them as guardian, operator or deployer, and must refuse to seed them as compliant parties.
R4. Every approve or reject carries an authenticated principal: an approver token or a verified passkey assertion bound to the exact decision. The approver identity is derived from the credential, never read from a request body, query string or client side setting.
R5. Fail closed. No approval, an expired approval, a rejected approval, an unreachable chain, an unreadable state file, or an unverifiable proof all mean nothing moves and the caller is told why. Liveness never beats safety.
R6. The deterministic policy engine `aegis.policy.evaluate` is a pure function of (proposal, context, policy). It performs no I/O, consults no model, and has no clock other than values passed in the context.
R7. The on chain gate is the enforcement point. Any new gated operation goes through `GuardianModule._consumeAuthorization` with every struct field checked against the call parameters; no contract function may bypass it, and no Python path may execute a gated move except by submitting a consumed authorization.
R8. Audit records are append only and write once. A record, once hashed and signed, is never edited, reordered or deleted by code; corrections are new records that reference the old `decision_id`.
R9. Evidence that justified a decision is embedded in the audit record before hashing and signing (policy result, matched rules, policy hash, approver principal, auth method, passkey assertion). Evidence never lives only in a mutable table.
R10. The policy hash bound into an authorization is the sha256 of the exact policy file that produced the decision. Reloading a policy at runtime without re deriving the hash is forbidden.

## B. Correctness rules (the defect class that cost the ICME trial: unreadable treated as normal)

R11. A missing, malformed, unparseable or unreachable value is an error, never a zero, an empty list, `False`, `"unknown"` or a default. Readers return an explicit error type or raise; callers decide how to surface it.
R12. A financial or security figure that cannot be computed in full is not shown as a number. The console renders an explicit "unavailable" state with the reason; it never renders `0`, `0%` or an empty bar in place of a failed read.
R13. Derived statistics state their source and freshness. `/metrics.injections` names the report file and its generation time; the console labels it "last eval run", never as a live count.
R14. Every status code path is explicit. A handler that can return 400, 401, 403, 404, 409, 410 and 503 lists them in its docstring and has a test per code.
R15. Idempotency and single use are enforced in the store, not in the handler: `Idempotency-Key` on submit, single use `decisionId` on chain, single use pairing codes, nonce from the `counters` table.
R16. Time comes from one place per process (`time.time()` for TTLs, `block.timestamp` on chain). Tests control time by injecting it, never by sleeping past a TTL.
R17. Addresses are compared checksummed or casefolded, never raw. Hex payloads are `0x` prefixed at every boundary; `chains.hex0x` normalises legacy values.
R18. Fix the class, not the instance. When a review finds one occurrence of a defect, grep for the pattern across the repo and fix every occurrence in the same change, and say so in the PR.
R19. Never reintroduce a fixed defect. Before changing a reader, check `git log -S` for the symbol; a prior fix with a test is a constraint, not a suggestion.

## C. Verification protocol (output never outruns checking)

R20. Before any commit run the full local gate: `forge fmt --check && forge test`, `ruff check python/ && ruff format --check python/ && pytest python/tests -q`, `cd frontend && npm run lint && npm run typecheck && npm test`. All green or no commit.
R21. If CI is down, red for an unrelated reason, or not configured for a suite, run that suite locally and paste the command and the pass count into the PR. "CI will catch it" is never a reason to skip a suite.
R22. Every finding gets a failing test first. The test fails on the parent commit and passes on the fix; the PR names both commits.
R23. Changing an existing test's expectation is a behaviour change. It is called out by name in the PR under "Tests whose expectations changed", with the reason. Silently inverting, loosening or deleting an assertion is forbidden.
R24. Committed artifacts come from a run of the full suite on the committed code. Do not commit a screenshot, an `evals/report.md`, an `openapi.json`, a lockfile or a build output produced from a different revision.
R25. Generated files are regenerated, never hand edited: `frontend/openapi.json` and `frontend/src/api/schema.d.ts` via `scripts/gen_openapi.py` and `npm run gen:api`, `requirements.lock` via pip freeze, `evals/report.md` via `make evals`.
R26. Coverage floors: `aegis/policy/engine.py` 100% branch, `aegis/approval/`, `aegis/audit/`, `aegis/guardian_touch/` 95% line. A change that lowers a floor is rejected.
R27. Determinism: no test depends on network access, a real model key, wall clock ordering or a shared port. Anvil is spawned per session on a free port by the fixture that owns it and terminated in teardown.
R28. A PR that touches Solidity runs the fuzz and invariant suites, not only unit tests. A PR that touches the approval service or guardian_touch runs the anvil integration test, not only the TestClient tests.

## D. Code rules

R29. Python 3.11+, full type hints, ruff clean with the repo config, pydantic v2 models at every process boundary (HTTP bodies, env config, state files). No `Any` on a public function signature unless the value is opaque JSON passed through unchanged.
R30. Configuration is read once, in `from_env()` classmethods, validated by pydantic, and passed down. No module reads `os.environ` at call time except those `from_env` functions and `chains.explorer_from_env`.
R31. Solidity 0.8.26, OpenZeppelin v5 only, `via_ir` off, custom errors not revert strings, an event for every state transition, NatSpec on every external function, `forge fmt` clean under the Foundry version CI installs.
R32. TypeScript strict, ESLint clean, no `any` at module boundaries, every data fetch through the generated typed client in `frontend/src/api/client.ts`, every screen with loading, empty, error and unavailable states, component tests with Vitest, Testing Library and MSW.
R33. Secrets in the browser are limited to the approver token the operator typed; it is stored in `localStorage` under one key, sent only as `Authorization: Bearer`, never logged, never put in a URL, never rendered after entry.
R34. Logging never prints a private key, a token, a passkey public key, a full RPC url with a path (`chains.redact_rpc_url`) or a user comment at INFO level.
R35. Dependencies are pinned: `requirements.lock`, `frontend/package-lock.json`, the OpenZeppelin submodule revision, `solc = "0.8.26"`. A version bump is its own commit with the reason.
R36. Dev conveniences are named as such: `policies/dev.yaml`, `aegis/devchain.py`, `scripts/dev-stack.sh`, `make dev`. Nothing named `default` may carry dev only data.

## E. Pull request protocol

R37. One concern per PR, under 400 changed lines excluding generated files and lockfiles. A refactor and a behaviour change never share a PR.
R38. The PR description uses the template in SPEC.md section 9: Why, What changed (by file), What was verified (commands and counts), Tests whose expectations changed, Not fixed and why, Decisions for the owner.
R39. A PR that leaves a known defect in place says so under "Not fixed" with the issue number; silence about a known gap is a defect in the PR.
R40. Commits are authored as the repository owner (`rajatwasan12@gmail.com`) with conventional messages (`feat(approval): ...`, `fix(api): ...`, `docs: ...`, `chore: ...`). No tool attribution trailers, no generated with lines, no session links.
R41. Never push to `main`. Work on a branch, open a PR, let CI run, merge only when green and reviewed.
R42. Never force push a shared branch, never rewrite history that CI has seen, never amend a pushed commit.

## F. Repository hygiene

R43. No logs, shell transcripts, session profiles, scratch scripts or build loop output are tracked. `.gitignore` is authoritative; a tracked file matching it is a defect.
R44. Build harness files for autonomous coding sessions (restart loops, mission prompts, progress checklists) do not live in the repository root. History goes under `docs/history/`.
R45. Deployment configuration carries no deployment specific origins, hostnames or app names in tracked files; those are set as platform secrets or env and documented in `deploy/DEPLOY.md`.
R46. Documentation states what exists. A claim in README, docs or a resume line about this repository must point at code and a test that exist on `main`. There is no zero knowledge proof, no MPC, no threshold signing and no formal verification in this repository; do not describe it as having any until the code and tests exist.
R47. Screenshots in `docs/screenshots/` are regenerated by `make e2e` from the committed revision when the UI they show changes.

## G. Clean room IP rules

R48. This is an original MIT licensed work. Do not reference, name, quote or imitate ERC-7518, DyCIST, Zoniqx or any proprietary compliance token design; these strings must not appear anywhere in the repository including comments, docs, tests and commit messages. `scripts/check_hygiene.sh` enforces this in CI.
R49. Do not use the term "partition" for token classes; multi class assets are ERC-1155 token ids, called "asset classes".
R50. Contracts derive only from OpenZeppelin plus code written here.

## H. Operating rules for coding agents working in this repository

R51. Start by reading `AGENTS.md`, then `SPEC.md`, then the work item you were assigned. Do not start a work item whose dependencies in SPEC.md section 7 are open.
R52. Operate only inside the repository root. Never run commands with sudo, never install global packages, never modify shell rc files, cron, keychains or credentials. Python deps go in `.venv`, Node deps in `frontend/node_modules`.
R53. Never run `git push`, add a remote, or publish anything unless the task you were given says so in writing. Local commits on a branch are the default output.
R54. Never write a real secret into a tracked file. `.env.example` carries placeholders that fail validation on purpose.
R55. Long lived processes (anvil, uvicorn, vite) start only inside test fixtures or scripts that terminate them in teardown. No process survives the session.
R56. When a decision is needed that SPEC.md does not settle, pick the option that fails closed, record it as `docs/adr/NNN-title.md` (context, decision, consequences), and list it under "Decisions for the owner" in the PR.
R57. When something fails after three genuinely different attempts, stop, write down the symptom, the attempts and the hypothesis in the PR, and leave the test failing and visible. Never mark it skipped or expected failure to make the suite green.
R58. Read the review comments on the previous PR before opening the next one; a class of defect flagged once is checked across the whole change before it is opened.
