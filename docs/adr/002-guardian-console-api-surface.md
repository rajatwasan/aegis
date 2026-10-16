# ADR 002 — Guardian Console API surface mapping

## Context

`docs/history/overnight-build/FRONTEND.md` milestone F0 names REST/SSE endpoints for the Guardian Console and
instructs: where the spec names an endpoint that exists differently in the
code, adapt the spec to the code and record the mapping. The existing code has
an approval service (`aegis.approval.app`), a hash-chained audit log, a pure
policy engine, and anchor/verify logic living inside the `aegis` CLI.

## Decision

- **One app, extended.** `aegis.api.create_api_app` builds the *existing*
  approval service (`create_app` gains an optional `EventBus` parameter; every
  existing route and response shape is unchanged) and mounts the new read/
  streaming endpoints on the same FastAPI instance. One process owns one
  proposal store, one audit log, one policy — the console never sees split
  state.
- **`GET /decisions` is a projection, not a new store.** A "decision" is an
  audit record written by the policy gate: `actor == "agent"` with a
  `policy_result.effect`. Human resolutions and resume records remain visible
  under `GET /audit/records`, which serves the raw chain.
- **`POST /anchor` added.** `anchor.created` cannot be emitted from the CLI
  (separate process, in-process bus). The anchor/verify logic moved out of
  `aegis.cli` into the `aegis.anchoring` library; the CLI keeps its exact
  behavior as a thin printing layer, and the API wraps the same functions so
  anchoring from the console emits the event.
- **Chain state comes from `state_dir/state.json`** (written by the demo/dev
  stack), the same contract the CLI already used. Endpoints that need a chain
  (`/audit/verify`, `/anchor`, `/agent/run`) return 503 until it exists.
- **`POST /agent/run` stays keyless by default.** A small map of canned
  instructions → scripted MockLLM tool plans (exposed as chips via
  `GET /agent/instructions`) drives the real LangGraph agent in a worker
  thread; unknown instructions get a 400 naming the canned set. When the graph
  escalates, the runner polls the shared proposal store until the human acts,
  then resumes the interrupted thread — the console's approve button is the
  resume signal.

## Consequences

- The frontend consumes exactly one origin; SSE events (`proposal.*`,
  `decision.recorded`, `anchor.created`, `agent.step`) all flow through one
  in-process bus.
- Two audit-log writers (approval service and agent runtime) share one file
  within one process; the append path re-reads the tail, so records stay
  chained.
- `aegis verify` CLI output is byte-identical to before; its tests run
  unmodified against the refactored library.
