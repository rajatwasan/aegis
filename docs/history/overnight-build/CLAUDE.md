# CLAUDE.md - Aegis build constitution

You are building Aegis: an open-source, cryptographically enforced human-in-the-loop
runtime for AI agents operating on tokenized assets. You are running UNATTENDED.
No human will answer questions until morning. These rules override everything else.

## Hard boundaries (never violate)

1. Operate ONLY inside this repository root. Never read, write, create, or delete
   any file outside it. Never `cd` above the repo root.
2. Never run commands with sudo. Never modify system state, shell rc files,
   global git config, cron, launchd, or environment outside this process.
3. Never install global packages. Python deps go in `.venv` only. If a required
   system tool (forge, anvil, python3, git) is missing, do NOT install it:
   record the gap in BLOCKERS.md and continue with milestones that do not need it.
4. Never use `rm -rf` with any argument containing `~`, `$HOME`, `/`, `..`, or a
   wildcard at directory scope. To clean generated files use `git clean -fdx`
   scoped to the repo, and only when necessary.
5. Never run `git push`, never add remotes, never touch credentials, keychains,
   SSH keys, or tokens. Local commits only.
6. Never write real secrets anywhere. `.env.example` with placeholder values only.
7. No interactive or long-foreground commands: no editors, no watch modes, no
   `docker compose up` in the foreground. Anything long-lived (anvil, uvicorn)
   is started in the background by test fixtures or scripts and ALWAYS terminated
   in teardown. If any single command exceeds 5 minutes, kill it and reassess.
8. Do not use any MCP tools or fetch any URLs except package registries needed
   by pip/forge for dependency installation.

## Clean-room IP rules (never violate)

- This is an original MIT-licensed work. Do not reference, name, quote, or imitate
  ERC-7518, DyCIST, Zoniqx, or any proprietary compliance-token design.
  These strings must never appear anywhere in the repo, including comments,
  docs, tests, and commit messages.
- Do not use the term "partition" for token classes. Multi-class assets are
  modeled as ERC-1155 token ids, called "asset classes".
- Contracts derive only from OpenZeppelin (ERC20, ERC1155, EIP712, ECDSA,
  Ownable/AccessControl) plus original code written here.

## Autonomy protocol

- Never wait for user input. When a decision is needed, choose the simplest
  option consistent with the acceptance criteria and record it as an ADR in
  `docs/adr/NNN-title.md` (context, decision, consequences).
- Work milestone by milestone in PROMPT.md order. Within a milestone: write
  tests with the code, run `make test`, commit only on green.
- If something fails after 3 genuinely different attempts: mark the test as
  expected-failure with a TODO, append a dated entry to BLOCKERS.md (symptom,
  attempts, hypothesis), and move on. Forward progress beats perfection.
- After completing each milestone: update PROGRESS.md (check the boxes, append
  a 2-3 line session note), then `git add -A && git commit` with a conventional
  message like `feat(contracts): guardian-gated ERC20 with EIP-712 auth (M1)`.
- On session start: read PROGRESS.md first. Resume from the first incomplete
  milestone. Do not redo completed work; trust green tests and git history.
- When every milestone is done and `make test` plus `scripts/demo.sh` pass,
  write `ALL_MILESTONES_COMPLETE` as the final line of PROGRESS.md and stop.

## Quality bar

- Solidity 0.8.26, via-ir off, forge fmt clean, NatSpec on public interfaces,
  custom errors not revert strings, events for every state transition.
- Python 3.11+, ruff clean, full type hints, pydantic v2 models at boundaries.
- Every module gets unit tests; the flows get integration tests. Determinism:
  no test may depend on network access or a real LLM key.
- Documentation is a deliverable, not a leftover: README quickstart must work
  by copy-paste.

  ## Frontend addendum

- Network: npm registry is now also permitted for dependency installation.
  Nothing else changes: no other URLs, no MCP tools.
- All Node dependencies are local to `frontend/` (package.json + lockfile).
  Never `npm install -g`. Use npm, not pnpm or yarn.
- Dev servers (vite, uvicorn) may run ONLY in the background inside test
  fixtures or scripts, always terminated in teardown. Never leave a server
  running at the end of a session.
- Do not modify contracts/ at all. Python changes are limited to the API
  additions listed in FRONTEND.md milestone F0. Every existing test must
  remain green after every commit; run the full `make test` before committing.
- Quality bar, frontend: TypeScript strict mode, ESLint clean, no `any` at
  module boundaries, every component with loading/empty/error states, all
  data-fetching through the generated API client, component tests via
  Vitest + Testing Library + MSW (no test may hit a real server or network).
- When frontend work is complete per FRONTEND.md, append FRONTEND_COMPLETE
  as the final line of PROGRESS.md and stop.