# Deploying Aegis

Operations runbook for the hosted stack: one machine runs the Guardian Console
API (approval service, read models, SSE) and either talks to a public chain or,
for a throwaway environment, to an anvil inside the same container. The console
is a static build served separately and talks to the API over HTTPS.

Files: `deploy/Dockerfile`, `deploy/start.sh`, `fly.toml`, `.dockerignore`,
`frontend/vercel.json`. Everything runs from the repository root.

This document describes the code at the revision it ships with. When a work
item in `SPEC.md` changes a variable, it changes this file in the same PR.

## 1. Prerequisites

- A container host. The checked in configuration targets Fly.io; any host that
  runs a Dockerfile with a persistent volume at `/data` and injects secrets as
  environment variables works the same way.
- A static host for the console (Vercel configuration is checked in; any static
  host works).
- For a public chain: an RPC url and a funded deployer key. Base Sepolia is the
  tested target (chain id 84532); see `docs/adr/005-public-testnet-anchoring.md`.
- Foundry on the build machine only if you build images locally; the Dockerfile
  installs it inside the image.

## 2. Secrets and configuration

Set these as platform secrets, never in tracked files. Section 5 of `SPEC.md`
is the authoritative list; the ones a deployment needs today:

| Variable | Purpose | Notes |
| --- | --- | --- |
| `AEGIS_RPC_URL` | chain the API deploys to and anchors on | `https://sepolia.base.org` for Base Sepolia |
| `AEGIS_OPERATOR_KEY` (alias `AEGIS_DEPLOYER_KEY`) | funded key that deploys the suite, performs the agent's plain transfers and pays for anchors | throwaway testnet key; never a key that holds value; read from the environment only, never from `state.json` |
| `AEGIS_GUARDIAN_KEY` | the guardian signing key held by the approval service | generate one (below); never reuse the deployer key |
| `AEGIS_APPROVER_TOKENS` | one bearer token per named approver, `id:token,id:token` | tokens are at least 24 characters; each human gets their own id so the audit log names who approved; rotate by redeploying the secret |
| `AEGIS_ADMIN_TOKEN` | operator token that mints passkey pairing codes | at least 24 characters; only the operator holds it |
| `AEGIS_CORS_ORIGINS` | the console origin(s), comma separated | the static host's URL |
| `AEGIS_STATE_DIR` | where `state.json`, the audit log and anchors live | `/data/aegis`, on the persistent volume |
| `AEGIS_API_HOST`, `AEGIS_API_PORT` | bind address | `0.0.0.0`, `8080` in the image |

Generate keys and tokens locally, never on the host:

```bash
python - <<'PY'
import secrets
from eth_account import Account
from web3 import Web3
for role in ("deployer", "guardian"):
    a = Account.create()
    print(f"{role}: address {a.address}  key {Web3.to_hex(a.key)}")
for who in ("ops-1", "ops-2", "admin"):
    print(f"{who}: {secrets.token_hex(24)}")
PY
```

Hand each approver their own token out of band. The console stores it in the
browser and sends it only as an `Authorization: Bearer` header; the service
records the approver id and the method (`token` or `passkey`) on every
approval and in the audit log.

Fund the deployer address on the target chain (Base Sepolia faucet: Coinbase
developer platform, or basefaucet.com; 0.02 ETH covers a deploy and many
anchors). The guardian address needs no funds; it only signs.

## 3. Deploy the API

```bash
fly apps create <app-name>
fly volumes create aegis_data --size 1 --region sjc --app <app-name>
fly secrets set --app <app-name> \
  AEGIS_RPC_URL=https://sepolia.base.org \
  AEGIS_OPERATOR_KEY=0x... \
  AEGIS_GUARDIAN_KEY=0x... \
  AEGIS_APPROVER_TOKENS=ops-1:...,ops-2:... \
  AEGIS_ADMIN_TOKEN=... \
  AEGIS_CORS_ORIGINS=https://<console-host>
fly deploy --app <app-name>
```

`fly.toml` carries the machine shape, the volume mount and the environment that
is not secret. It does not carry an app name or an origin; pass `--app` and set
origins as secrets.

What `deploy/start.sh` does on boot:

1. If `AEGIS_RPC_URL` and `AEGIS_DEPLOYER_KEY` are set and the RPC answers, it
   deploys the contract suite (or reuses an existing deployment recorded in
   `state.json` when the contracts still hold code) and writes `state.json`.
2. Otherwise it starts a local anvil inside the container and deploys there. A
   local chain is disposable: a restart means a fresh chain and an empty audit
   log, and the console labels the chain `local` with no explorer links. Treat
   this as a development convenience, not a deployment.
3. It starts the API.

## 4. Deploy the console

```bash
cd frontend
vercel link
vercel env add VITE_API_URL production      # https://<app-name>.fly.dev
vercel --prod
```

Then point the API's CORS at the console origin:

```bash
fly secrets set --app <app-name> AEGIS_CORS_ORIGINS=https://<console-host>
```

Setting a secret restarts the machine. With `--reuse` (the default in
`start.sh`) the deployment and the audit log survive the restart.

## 5. Verify

```bash
curl -s https://<app-name>.fly.dev/metrics | python -m json.tool | grep -A8 '"chain"'
# expect chain_name "base-sepolia", public true, connected true, an explorer_url
```

Full loop in a browser: Dashboard shows the chain connected; paste your
approver token into the token field; Console runs a canned instruction; the
large transfer escalates into Approvals; approve with a comment; Audit shows
the record with your approver id and `auth: token`; Verify shows `PROOF OK`;
Anchor now (or `POST /anchor`) produces a transaction you can open on the
explorer, and the verify panel links to it.

`PROOF OK` on a `local` chain proves only that the server agrees with itself.
Only an anchor on a public chain is checkable by someone who does not trust the
server.

## 6. Rotate

- Guardian key: rotate on chain first (`rotateGuardian` from the admin account,
  which is the deployer), then set the new `AEGIS_GUARDIAN_KEY` secret. Between
  the two steps every approval fails on chain with `InvalidGuardianSignature`;
  do it in a quiet window. Authorizations signed by the old key and not yet
  submitted are dead.
- Deployer key: fund the new address, set the secret. The contracts' admin role
  stays with the old address until you grant and revoke it on chain.
- Approver token: change the entry in `AEGIS_APPROVER_TOKENS` and set the
  secret; the old token stops working at the restart. Removing an id revokes
  that approver; their past approvals keep their id in the audit log.
- CORS origin: set the secret; the restart is enough.

## 7. Roll back

`fly releases --app <app-name>` lists releases; `fly deploy --image <ref>`
redeploys a previous image. State on the volume is forward compatible within a
major version of the state file; a rollback across a `state.json` shape change
needs the migration note of the release that changed it.

### Migration notes

- **Operator key out of `state.json`.** Earlier revisions wrote the deployer's
  private key into `/data/aegis/state.json` as `operator_key`. The loader now
  refuses a state file that contains it. On an existing volume: set the secret
  (`fly secrets set AEGIS_OPERATOR_KEY=0x...`, or keep `AEGIS_DEPLOYER_KEY`,
  which is accepted as an alias), then remove the field, for example with
  `fly ssh console -C "python -c \"import json;p='/data/aegis/state.json';s=json.load(open(p));k=s.pop('operator_key');s['operator_address']=s.get('operator_address') or __import__('eth_account').Account.from_key(k).address;json.dump(s,open(p,'w'),indent=2)\""`.
  The API refuses to start until the field is gone, and refuses a key that
  does not derive to the recorded `operator_address`.

## 8. Fallbacks when the build host misbehaves

- Forge build fails inside the image: build artifacts locally (`cd contracts &&
  forge build`), remove the `RUN cd contracts && forge build` line, and drop
  `contracts/out` from `.dockerignore` so the artifacts ship in the context.
- Static host misbehaving: `cd frontend && VITE_API_URL=https://<app> npm run
  build` and serve `dist/` from any static host.

## 9. Verified deployments

None recorded yet. When a public chain deployment is verified end to end,
record the date, chain, anchor contract address and one anchor transaction
link here.
