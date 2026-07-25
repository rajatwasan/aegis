# 004 — Derive the passkey pairing challenge from the pairing code

## Context

Guardian passkey enrollment (`/guardian/pair/*`) needs a WebAuthn
registration challenge that the server can verify when the browser returns
the attestation. The natural implementation stores a random challenge next
to the pairing code, but the `pairing_codes` table is specified as exactly
`(code PK, expires_at, used)` and the pairing code itself is already a
short-lived, single-use secret.

## Decision

The registration challenge is derived deterministically from the code:
`sha256("aegis-guardian-pair:" || code)`. Both `/guardian/pair/options` and
`/guardian/pair/complete` recompute it, so no challenge state is persisted
and the table keeps its specified shape. Decision assertions are unaffected:
they use their own challenge, `sha256(decision_id || canonical_json(proposal))`.

## Consequences

- One fewer column and no cleanup path; options/complete stay stateless.
- The challenge is only as secret as the pairing code (6 chars, 5-minute
  TTL, single use), which is the same trust anchor the flow already rests
  on — anyone holding a live code could complete pairing regardless of how
  the challenge is generated.
