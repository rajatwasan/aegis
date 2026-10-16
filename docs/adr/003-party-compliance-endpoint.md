# ADR 003 — Party compliance endpoint and approver identity mapping

## Context

`docs/history/overnight-build/FRONTEND.md` milestone F2 requires the proposal detail drawer to show the
"compliance status of both parties". Compliance and freeze standing live
on-chain (`ComplianceRegistry.isCompliant`, `GuardedToken.frozen`); no F0
endpoint exposes them. The stack section resolves this tension explicitly:
viem in the browser only "if a read-only chain call is genuinely needed
client-side; default to letting the backend do all RPC."

F2 also says the approver identity is "sent as a header", but the existing
approval service (`POST /proposals/{id}/approve|reject`) takes `approver`
in the JSON body — a shape frozen since M4 and consumed by the agent runtime.

## Decision

- **`GET /compliance/{address}` added** (one read-only route beyond the F0
  list, the minimal backend change consistent with the F2 acceptance
  criteria). It reuses the `AgentRunner`'s shared `AegisRuntime` — the same
  `check_compliance` / `is_frozen` reads the policy gate itself performs — so
  the console shows exactly what the gate would see. Response is
  `PartyStatus {address, known, compliant?, frozen?}`; with no chain state or
  an unreachable RPC it degrades to `known: false` instead of erroring, so
  the drawer stays usable chainless.
- **Approver identity stays in the body.** The console stores the reviewer's
  name client-side (localStorage) per the spec, but sends it as the existing
  `approver` body field rather than a new header: adapt the spec to the code,
  not the code to the spec.

## Consequences

- `frontend/openapi.json` and the generated client are regenerated; the
  drawer's party panel is fully typed.
- Guardian signing keys and dual-control enforcement remain server-side;
  the client-side "identity" is a label, as the spec intends.
