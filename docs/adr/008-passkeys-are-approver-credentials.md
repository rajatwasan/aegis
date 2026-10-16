# ADR 008: a passkey is a credential of an approver, not an approver

Date: 2026-10-16. Status: accepted. Spec: docs/specs/2026-10-hardening.md W10, decision D9.

## Context

The `guardian-touch` branch (ADR 004) let a phone pair a passkey against a
short code anyone could mint, and a decision made with it was recorded as
`passkey:<credential prefix>`. That is presence without identity: the audit
record proved a human touched a paired device but not which approver, pairing
was open to whoever reached the API, revoking an approver did not revoke their
phone, and the route bypassed `resolve_decision` by building the old request
body by hand (AGENTS.md C4, C6, I2).

## Decision

Pairing starts from an authenticated approver. `POST /guardian/pair/start`
requires the approver's bearer token (ADR 006) and mints a code bound to that
approver id; the credential enrolled with the code inherits the binding
(`guardian_credentials.approver_id`). `POST /guardian/decide` looks the
credential up, refuses a revoked or unknown approver before verifying anything,
verifies the assertion, and calls `resolve_decision` with
`Approver(id, display_name, auth_method="passkey")` and the assertion as
evidence. The approval, the resolution and the audit record therefore name the
same approver id a token decision would, with `auth_method` saying how presence
was proven. One human with a token and a passkey is one approver: under dual
control the passkey cannot be the second vote.

Evidence lives in two places with one meaning each. The proposal row keeps every
assertion with the approval it belongs to (`approvals[i].evidence`) and the
resolving action's assertion in `proposals.evidence`. The audit record embeds
that resolving assertion as `human_presence` before hashing and signing, so the
chain, the Ed25519 signature and the Merkle proof cover it; `human_action`
never duplicates it. Token decisions carry no `human_presence` at all.

No other `/guardian` route takes a bearer token: on the phone the passkey is
the credential. Passkey tables created before the binding existed make the
service refuse to start and name the fix; nothing is silently re-enrolled.

## Alternatives

- Treat the credential as its own approver (`passkey:<id>`): what the branch
  did; it is a device, not a person, and revocation does not reach it.
- Pair with an operator entered approver id, no token: the id would be a
  string in a request body again, which W2 removed.
- Store the assertion only in the audit record: the row would show no
  evidence until resolution, and dual control would lose the first assertion.

## Consequences

The phone shows whose passkey it holds ("signing as Casey"), the console gains
a "pair phone" control for the signed in approver, and the pairing state
stored on the phone before this change is treated as unpaired. Under dual
control the signed record carries the quorum completing assertion only; the
first approver's assertion stays on the row (spec W14). Tests drive a software
authenticator and Chromium's virtual authenticator against the real verifier,
with no stubbed verification.
