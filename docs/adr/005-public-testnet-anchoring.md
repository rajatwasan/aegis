# ADR 005: Anchor audit roots on a public testnet, with explorer links

## Context

The deployed demo ran anvil inside the API container. Verification worked — the
console rebuilt each Merkle proof and compared it against `rootOf(batchId)` — but
the chain it compared against was private and disposable. "PROOF OK" therefore
proved only that the server agreed with itself: a viewer had no way to inspect
the anchoring transaction, and a container restart erased the whole history.

An audit trail whose integrity claim cannot be checked by an outsider is a claim,
not a proof. What was missing was not cryptography but *reachability*: a chain the
viewer can query independently, and a link to the transaction carrying the root.

## Decision

1. **Anchor on Base Sepolia** (chain 84532) when configured. Public, ~2s blocks,
   free faucet gas, and a block explorer. Selected via `AEGIS_RPC_URL` plus a
   funded `AEGIS_DEPLOYER_KEY`; nothing about the chain is hardcoded.

2. **Chain identity lives in one table** (`aegis.chains`). A chain id maps to a
   name and explorer base, which produce `/tx/<hash>` and `/address/<addr>` links.
   Unknown ids degrade to `chain <id>` with no links; `AEGIS_EXPLORER_URL`
   overrides the table for forks.

3. **Anchors record where they landed.** Each batch in `anchors.json` now stores
   `chain_id`, `block_number` and `anchored_at` alongside the tx hash, so the
   link survives later re-pointing of the state file. `/anchor`, `/metrics` and
   `/audit/verify/{id}` all return the same `AnchorInfo`, explorer url included.

4. **Fall back to anvil, and say so.** If the public RPC is unreachable or the
   deployer is unfunded, `deploy/start.sh` starts a local anvil instead of
   failing. A dev chain yields no explorer links and the console labels it
   `local`, so a fallback can never be mistaken for a public anchor.

5. **Reuse a deployment across restarts** (`devstack --reuse`). Contracts are
   redeployed only when their addresses hold no code. On a public chain
   redeploying costs gas and would orphan the existing audit log.

6. **Redact the RPC url in `/metrics`.** Hosted providers carry the API key in
   the url path; `/metrics` is public. Only scheme + host are exposed.

## Consequences

- Anyone can open the anchoring transaction and read the root out of calldata,
  then re-derive it from the published audit log. That is the whole point.
- Anchoring now costs real (testnet) gas and takes a block, so the console gained
  an explicit "Anchor now" action with pending/error states rather than assuming
  anchoring is instant and free.
- The guardian's EIP-712 domain must carry the live chain id, so `deploy()` takes
  `chain_id` and `operator` instead of assuming anvil's account 0 — a public
  deployer is the only account with gas, and it must also be registry owner and
  a compliant party.
- The demo and every test still run on anvil with no configuration; the public
  path is opt-in through two environment variables.
- Anvil remains installed in the image for the fallback, so image size is
  unchanged.
