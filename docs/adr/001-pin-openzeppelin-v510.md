# ADR 001: Pin OpenZeppelin to v5.1.0

## Context

The locally installed foundry toolchain is forge/anvil 0.2.0 (2024-09-09).
`forge install OpenZeppelin/openzeppelin-contracts` resolved to v5.6.1, whose
bundled `foundry.toml` sets `evm_version = 'osaka'`. This forge version does
not recognize `osaka` and panics during remapping/config discovery, aborting
every `forge build`/`forge test`. Installing a newer foundry is prohibited
(no system-state changes, no global installs).

## Decision

Pin `openzeppelin-contracts` to v5.1.0 (October 2024), contemporary with the
installed toolchain. It satisfies the "OpenZeppelin v5.x" requirement in
PROMPT.md and compiles cleanly with solc 0.8.26.

## Consequences

- All contract imports target the OZ v5.1.0 API (ERC20, ERC1155, EIP712,
  ECDSA, AccessControl — all stable across v5.x).
- CI uses the checked-in submodule revision, so it is unaffected by the local
  toolchain age.
