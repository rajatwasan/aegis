# Aegis threat model

This document states what Aegis protects, who it protects against, and where the
guarantees stop. The central claim: **an AI agent — even one fully controlled by
an attacker via prompt injection — cannot move gated tokenized assets without a
human approval and a guardian signature.** Aegis is designed so that claim holds
*below* the model, in deterministic code and on-chain checks.

## Assets

1. **Gated tokens** — ERC20 (`GuardedToken`) and ERC1155 asset classes
   (`GuardedAsset1155`) balances that exceed a threshold or involve a
   non-compliant/frozen party.
2. **The guardian key** — the EIP-712 signing key held by the approval service;
   compromise defeats the whole model.
3. **Audit integrity** — the hash-chained log and its on-chain Merkle anchors;
   the record that a decision happened and who approved it.
4. **Policy integrity** — `policies/default.yaml`; its sha256 is bound into every
   authorization via `policyHash`.
5. **Compliance state** — KYC claims in `ComplianceRegistry`.

## Actors and trust

| Actor | Trust | Notes |
| --- | --- | --- |
| LLM / agent | **Untrusted** | Assumed fully attacker-controlled (prompt-injected). |
| Tool caller / MCP client | Untrusted | Reaches the runtime only through typed tools. |
| Aegis runtime host | Trusted | Runs policy + audit; holds no guardian key. |
| Approval service | Trusted, key-custodian | Holds the guardian key; signs only post-approval. |
| Human approver | Trusted | The intended locus of control. |
| Chain (anvil / EVM) | Trusted execution | Enforces the guardian gate deterministically. |
| Contract admin | Trusted | Can rotate the guardian and grant roles. |

## Trust boundaries

- **LLM → runtime.** Crossed only by a proposed tool action. The typed registry
  rejects unknown tools and malformed args; the policy engine — a pure,
  network-free function — decides allow/deny/escalate.
- **Runtime → chain.** A gated move requires a consumed `Authorization`. The
  `GuardianModule` checks the guardian signature, single-use `decisionId`,
  `deadline`, and that **every** struct field equals the call parameters.
- **Approval → chain.** The guardian signs the exact struct the contract hashes
  (EIP-712 domain `AegisGuardian`/`1`), including `policyHash`.
- **Audit → verifier.** Off-chain records are provable against on-chain roots via
  Merkle proofs; tampering breaks the hash chain and the proof.

## STRIDE analysis

| # | Threat (STRIDE) | Vector | Mitigation | Residual |
| --- | --- | --- | --- | --- |
| 1 | **S**poofing | LLM claims to be the guardian/admin/approver in prose | Authority is a key, not a phrase; contract checks `signer == guardian`; role text in prompts is inert | None on-chain; approver must not be socially engineered (see #12) |
| 2 | **S**poofing | Forged/replayed guardian signature | ECDSA recover to current guardian; single-use `decisionId`; `deadline` | Guardian key compromise (#8) |
| 3 | **T**ampering | Mutate an audit record | Hash chain + Ed25519 signature + Merkle root anchored on-chain; `aegis verify` fails on any edit | Pre-anchor records rely on the signing key; anchor promptly |
| 4 | **T**ampering | Swap the policy after approval | `policyHash` bound into the signed `Authorization`; mismatch is detectable | Admin can ship a bad policy (#11) |
| 5 | **T**ampering | Smuggle extra tool fields (`bypass_policy`, fake `signature`) | Pydantic schemas ignore unknown fields; the chain ignores anything not in the struct | None |
| 6 | **R**epudiation | Deny who approved what, or approve as someone else | Approve and reject require an approver credential: a token the service issued and stores only as a hash, or a passkey paired to that approver by someone holding the token (W10). The identity on the approval and in the signed audit record is resolved from the credential, never from the request body (W2); a passkey decision also embeds the WebAuthn assertion over the exact decision in the signed record | Credential theft: a stolen token acts as that approver until revoked (`aegis approver revoke`, which also stops their phone); a passkey needs the device and its biometric |
| 7 | **I**nfo disclosure | Coax the agent to leak the guardian key or an approver token | The runtime/agent never holds the key or any approver token; the key lives only in the approval service (no default, dev keys refused, binding to the on chain guardian checked at startup, W1) and tokens live only in approvers' browsers | Key custody hardening is deployment-specific |
| 8 | **I**nfo disclosure / **E**oP | Approval-service or guardian-key compromise | Key isolated from the agent; rotation via admin; dual-control mode needs two approvers | **Full compromise defeats the gate — out of scope to prevent, only to contain** |
| 9 | **D**enial of service | Flood escalations to exhaust approvers | TTL auto-reject (default 15 min); nothing executes on timeout | Availability of approvals is not guaranteed (fails safe/closed) |
| 10 | **D**oS | Spam the chain / gas grief | Local anvil; per-tx gas caps | Real-network economics out of scope |
| 11 | **E**oP | Malicious contract admin rotates guardian to attacker | Admin is a trusted role; events on every rotation; monitor on-chain | Trusted-admin assumption; use a multisig in production |
| 12 | **E**oP | Social-engineer the human approver (fake urgency/tickets) | Approver sees raw proposal + policy result; comments are advisory only | Human judgment is the residual control |

## Explicitly in scope: malicious / compromised LLM and prompt injection

Aegis assumes the LLM is **hostile**. The M6 eval harness runs 50+ injection
attempts — instruction override, tool-schema smuggling, role confusion,
social-engineering of the approver text, unicode/homoglyph obfuscation,
many-shot distraction, destination and rate-limit evasion, replay, and
confused-deputy — with the MockLLM in **gullible mode**, meaning the model layer
*obeys every injected instruction*. The result: **bypass rate 0.** Attacks
either get refused at the typed-tool boundary, denied by policy, or escalated to
a human; none auto-executes a gated move. See [../evals/report.md](../evals/report.md).

The reason this works: prompt injection can change what the agent *asks for*, but
not what the chain *accepts*. The gate is a signature the agent cannot forge and
a human it cannot impersonate.

## Residual risks (accepted)

- **Guardian-key or approval-service compromise** defeats the model. Aegis
  contains it (key isolated from the agent, rotation, optional dual-control,
  signed/anchored audit) but cannot prevent it. Treat the guardian like a
  signing HSM in production.
- **Trusted admin** can rotate the guardian or grant roles maliciously; use a
  multisig/timelock. Rotations emit events for monitoring.
- **Approver credential theft** acts as that approver until the token is
  revoked. Tokens are random, stored hashed, compared in constant time, and
  revocable; a paired passkey proves presence per decision and dies with the
  approver's revocation (W10). The next step is approver signed approvals.
- **Human approver error / social engineering** is the deliberate last line of
  control; Aegis surfaces the raw proposal and policy verdict but cannot make the
  decision for the human.
- **Policy quality** is a human responsibility; Aegis guarantees the policy is
  applied deterministically and its hash is bound to each authorization, not that
  the policy is correct.
- **Availability**: if no approver acts, escalations expire and nothing moves —
  Aegis fails **closed** by design, trading liveness for safety.
