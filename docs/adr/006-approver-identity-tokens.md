# ADR 006: approver identity comes from a server held credential

Date: 2026-10-16. Status: accepted. Spec: docs/specs/2026-10-hardening.md W2, decision D1.

## Context

`POST /proposals/{id}/approve` and `/reject` took the approver's name from the
request body. Any caller that could reach the API approved as anyone, dual
control could be satisfied by one person typing two names, and the audit record
attributed the decision to a string. The README claimed a human the agent cannot
impersonate; the API did not deliver it (AGENTS.md C4, I2).

## Decision

Approvers are registered server side (`aegis approver add <id>`), receive a 256
bit random bearer token exactly once, and the service stores `sha256(token)`.
Approve and reject require `Authorization: Bearer <token>`; the approver id,
display name and `auth_method` written to approvals, resolutions and audit
records are resolved from the token. The body carries only `comment`, with extra
fields forbidden so stale clients fail loudly. `GET /approvers/me` tells a client
who its token is. All resolution paths go through one internal function,
`resolve_decision`, which is the only code that records an approval, signs an
authorization and writes the audit record; the passkey path (ADR 004, which lands with W10) will
call it with `auth_method="passkey"` and the assertion as evidence.

Tokens are compared in constant time, can be revoked, and are never logged or
listed. The console keeps the token in the viewer's browser (localStorage, per
viewer convenience) and attaches it only to the routes that need it.

## Alternatives

- Approver signed approvals (EIP 712 `ApprovalIntent` from a registered key):
  stronger and replay safe, but the console has no signer yet. Next step after
  W10.
- Passkey only: the desktop console would lose its approve button on machines
  without a platform authenticator, and the branch as written routed into the
  open endpoint.
- An allowlist of names in the body: a name is not a credential.

## Consequences

Breaking API change: old clients get 401 (no token) or 422 (body `approver`).
The dev stack creates approver `dev` and writes its token to
`.aegis/dev/dev-approver.token`; the demo registers its own approver; hosted
deployments create approvers with the CLI on the machine. A stolen token acts
as that approver until revoked (threat model row 6).
