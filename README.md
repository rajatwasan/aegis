# Aegis

**Cryptographically enforced human-in-the-loop control for AI agents operating
on tokenized assets.**

An LLM agent proposes token operations. A deterministic policy engine allows,
denies, or escalates. Escalations pause the agent until a human approves.
Approved high-risk operations execute on-chain **only** with an EIP-712
authorization co-signed by a guardian key held by the approval service. Every
decision lands in a hash-chained audit log whose Merkle roots are anchored
on-chain, and a CLI can prove any single decision's inclusion.

The guarantee is enforced below the model: even a fully prompt-injected agent
cannot move gated assets, because the chain refuses without the guardian
signature.

## Status

Under construction — see [PROGRESS.md](PROGRESS.md) for milestone status.

## Quickstart

```bash
# prerequisites: foundry (forge + anvil), python 3.11+, git
make setup     # create .venv, install python deps, install forge deps
make test      # run contract + python test suites
make demo      # headless end-to-end demo on a local anvil chain
```

## Layout

- `contracts/` — Foundry project: guardian-gated ERC20/ERC1155, compliance registry, audit anchor
- `python/aegis/` — policy engine, audit log, approval service, LangGraph agent, MCP server
- `evals/` — prompt-injection corpus and harness
- `policies/` — YAML policy files
- `docs/` — architecture, threat model, ADRs

## License

MIT
