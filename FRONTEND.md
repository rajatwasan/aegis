# FRONTEND.md - Guardian Console mission spec

Read CLAUDE.md first, including the frontend addendum. Clean-room rules from
CLAUDE.md apply unchanged to all frontend code, copy, and docs.

## What you are building

The Guardian Console: the human control surface for the Aegis HITL runtime.
A reviewer must be able to see WHY something was escalated (which policy rules
matched), act on it (approve/reject with comment, dual-control aware), watch
the agent's activity live, and cryptographically verify any past decision
against the on-chain anchor with one click. It must read as a control room,
not a CRUD admin panel.

## Ground rule: discover before you build

Before F0, read the existing code: the approval service routes and models,
the audit module, the policy engine result shapes, scripts/demo.sh, and the
Makefile. Conform to what exists. Where this spec names an endpoint that
already exists under a different path or shape, adapt the spec to the code,
not the code to the spec, and record the mapping in an ADR.

## Stack (pinned)

Vite + React 18 + TypeScript strict. Tailwind CSS v4. TanStack Query for all
server state. React Router. openapi-typescript + openapi-fetch generating a
typed client from the FastAPI openapi.json (script: `npm run gen:api`; the
generated file is committed). Vitest + @testing-library/react + MSW for tests.
No component library: hand-rolled components on Tailwind. viem is permitted
only if a read-only chain call is genuinely needed client-side; default to
letting the backend do all RPC.

## Design system (non-negotiable)

Dark control-room aesthetic. Near-black slate background, one restrained
accent. Status is a color LANGUAGE used consistently everywhere:
allow/executed = green, escalated/pending = amber, denied/frozen = red,
info/anchored = blue. Inter (or system-ui) for text, JetBrains Mono for every
hash, address, amount, and id. Addresses truncate middle (0x1234...abcd) with
click-to-copy and a full-value tooltip. Dense tables, generous line-height,
skeleton loaders, no layout shift. Every timestamp shows relative time with
absolute on hover. TTLs render as live countdowns. It should look designed,
not templated: no default-Tailwind-blue buttons, no card soup.

## Milestones

### F0 - Backend API surface (python only, additive)
CORS middleware (localhost dev origins, configurable). An in-process event
bus; SSE endpoint `GET /events` streaming JSON events for: proposal.created,
proposal.approved, proposal.rejected, proposal.expired, decision.recorded,
anchor.created, agent.step. Emit events from the existing code paths.
REST additions (paginated where lists): GET /decisions, GET /audit/records,
GET /audit/records/{id}, GET /audit/verify/{decision_id} (returns record,
merkle path, on-chain root, PROOF_OK boolean; reuse the verify CLI logic as a
library function), GET /policy (raw yaml + policyHash + parsed rules),
GET /metrics (counts by effect, escalation rate, pending count, last anchor).
POST /agent/run accepting {instruction: str}: executes the LangGraph agent as
a background task using the configured LLM provider (MockLLM default; the
mock maps a small set of canned instructions to scripted tool plans so the
demo works keyless), emitting agent.step events as it goes.
Pytest for every new endpoint including an SSE consumption test.
Accept: full `make test` green, zero existing tests modified except imports.

### F1 - Frontend scaffold
`frontend/` per the stack above. Layout shell: left nav (Approvals, Activity,
Audit, Policy, Console), top status bar showing chain connection, last anchor,
pending count (live via SSE). Typed client generation wired
(`npm run gen:api` against a running dev API or a committed openapi.json
snapshot). Root Makefile gains: `frontend-dev`, `frontend-build`,
`frontend-test`, and `dev` (runs uvicorn + vite concurrently, foreground,
documented as human-only). Root `make test` now includes `frontend-test`.
CI workflow extended with a node job (install, lint, typecheck, test, build).
Accept: `make frontend-build` and `make test` green.

### F2 - Approvals queue (the core screen)
Pending proposals list, newest first, live-updating via SSE with TanStack
Query cache invalidation. Each row: operation badge, from -> to, amount +
asset class, live TTL countdown, dual-control progress if enabled. Detail
drawer: full proposal, the policy Decision (every matched rule id with its
human-readable condition, and the policyHash), compliance status of both
parties, and the approve / reject actions with required comment. Optimistic
updates with rollback on failure; expired items visibly decay out. Approver
identity from a simple local setting (name stored client-side, sent as a
header) since guardian signing stays server-side by design.
Component tests (MSW): render, countdown behavior, approve flow, reject flow,
dual-control state, error rollback.
Accept: tests green; screen fully usable against `make dev`.

### F3 - Activity feed + Audit explorer
Activity: live event stream (decisions + agent.step) as a chronological feed
with effect-colored markers, filterable by effect and operation.
Audit explorer: paginated record table; record detail view showing canonical
JSON, prev_hash -> record_hash chain link (with a visual chain of the
surrounding records), signature, and a Verify button calling
/audit/verify/{decision_id}, rendering each Merkle path step, the on-chain
root, anchor batch id, and a large PROOF OK / PROOF FAIL badge.
Component tests for the feed reducer and the verify rendering (both outcomes).
Accept: tests green; verifying a decision from the demo run shows PROOF OK.

### F4 - Command console + dashboard
Console: instruction input posting to /agent/run, then a live split view:
left, the agent's steps streaming in (tool calls, policy results) as they
happen; right, any resulting escalations appearing with inline approve
controls, so the full loop is visible on one screen. Ship 3 canned
instructions as one-click chips matching the MockLLM's scripted plans.
Dashboard (landing page): stat cards (total decisions, escalation rate,
denials, pending, last anchor with tx link), a 24h decisions-by-effect bar,
and blocked-injection count sourced from evals/report.md via /metrics.
Accept: with `make dev` + anvil running, a canned instruction produces
visible steps, an escalation, an approval, and an executed transfer without
touching a terminal.

### F5 - E2E, docs, polish
Playwright: one smoke spec that boots the demo stack (reuse scripts/demo.sh
plumbing or a scripts/dev-stack.sh), runs the canned-instruction flow,
approves, and asserts PROOF OK appears. Keyboard support: j/k row navigation,
a/r approve-reject on the focused proposal, all actionable elements
focus-visible. README gains a Guardian Console section with screenshots
(capture via Playwright) and the quickstart updated to `make dev`.
docs/architecture.md updated with the frontend + SSE component.
Accept: `make test` green, e2e passes locally, screenshots committed.

Then append FRONTEND_COMPLETE as the final line of PROGRESS.md and stop.