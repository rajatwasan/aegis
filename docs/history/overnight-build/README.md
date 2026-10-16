# Overnight build harness (July 2026), kept for provenance

These files drove the first build of Aegis between 2026-07-06 and 2026-07-25.
They are not instructions for current work. `AGENTS.md` at the repository root
and the newest spec in `docs/specs/` replace them.

| File | What it was |
| --- | --- |
| `CLAUDE.md` | The build constitution for unattended coding sessions: hard boundaries, clean room IP rules, autonomy protocol, quality bar |
| `PROMPT.md` | The mission spec: milestones M0 to M8 with acceptance criteria and the frozen EIP 712 protocol |
| `FRONTEND.md` | The Guardian Console milestones F0 to F5 |
| `PROGRESS.md` | The milestone log, one note per milestone, through the public chain anchoring work of 2026-07-25 |
| `run.sh`, `run-frontend.sh` | The restart loops that relaunched the coding session until `PROGRESS.md` reported completion |

Two parts of this material still apply and were carried into `AGENTS.md`: the
clean room IP rules (S5) and the no secrets, no global installs, no servers
left running rules (S1, S4, A5). The EIP 712 `Authorization` struct and domain
in `PROMPT.md` remain the frozen protocol and are documented in
`docs/architecture.md`.
