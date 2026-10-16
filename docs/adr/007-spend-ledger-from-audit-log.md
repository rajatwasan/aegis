# ADR 007: the daily limit is derived from the audit log over a rolling window

Date: 2026-10-16. Status: accepted. Spec: docs/specs/2026-10-hardening.md W4, decision D5.

## Context

`AegisRuntime.daily_spent` was a dict on the runtime object. It reset on every
restart and never rolled within a day, so the policy predicate
`within_daily_limit` was enforced against whatever one process had seen
(AGENTS.md C7: in memory counters are not policy state).

## Decision

`aegis.agent.spend.SpendLedger` reads the audit log and sums, per sender, the
amounts of records where the actor is `agent`, the effect was `allow`, the
status is `executed`, the proposal is a transfer from that sender, and the
timestamp is inside `(now - window, now]`. The runtime consults it when it
builds the policy context. The window comes from `AEGIS_DAILY_WINDOW_SECONDS`
(default 86400) and is shown on `/policy`.

Approved escalations are not charged to the automatic budget: they are
recorded as resumed executions without a proposal payload, and a human
reviewed them. Records the ledger cannot read (no timestamp, no integer
amount) raise instead of counting as zero (C1).

## Alternatives

- A sqlite counter table: a second source of truth that can drift from the
  log; the log already holds every execution, signed and chained.
- Keep the dict and persist it to disk: still a copy, still a window that
  never rolls without extra code.

## Consequences

Each policy evaluation reads the log. At demo and pilot scale that is
milliseconds; a long log would want an index or a periodic checkpoint, which
can be added behind the same interface. The injected clock makes the window
testable without waiting.
