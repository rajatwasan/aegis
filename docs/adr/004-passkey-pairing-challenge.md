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

## Amendment (2026-10-17): pairing is operator only; passkeys are principals

- `POST /guardian/pair/start` requires `Authorization: Bearer $AEGIS_ADMIN_TOKEN`.
  As first merged it was open, so anyone who could reach the API could mint a
  code, enrol a passkey and approve. Operators without the token at hand can
  mint a code from the host with `aegis guardian pair-code`, which needs
  filesystem access to the approval store.
- A verified `/guardian/decide` assertion becomes
  `Principal(id="passkey:<credential_id[:8]>", auth="passkey")` and routes into
  the same authenticated approve and reject handlers as a bearer token. The
  audit record's `human_action.auth` is `passkey` and `human_presence` carries
  the assertion, both inside the hashed and signed payload.
- `AEGIS_RP_ID` and `AEGIS_EXPECTED_ORIGIN` are required on a public chain.
