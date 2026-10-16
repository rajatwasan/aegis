# Deploying Aegis

One container runs the Guardian Console API together with the chain it
deploys to (a public testnet, or a local anvil for a demo); a static host
serves the console. The reference setup below uses Fly for the API and Vercel
for the console, but nothing depends on either: the image is
`deploy/Dockerfile`, the entrypoint is `deploy/start.sh`, and every
configuration value is an environment variable listed in section 2.

Everything runs from the repository root.

## 1. What a deployment holds

| Secret or setting | Held by | Why |
| --- | --- | --- |
| `AEGIS_GUARDIAN_KEY` | the API container only | signs every approved authorization; its address is the token's on chain guardian |
| `AEGIS_DEPLOYER_KEY` | the API container only | deploys the suite and pays for anchor transactions on a public chain |
| approver tokens | each approver, in their browser | approve and reject require one; the service stores only hashes |
| `AEGIS_POLICY_PATH` | the API container | the policy file whose sha256 is bound into every authorization |

The agent, the MCP server and the console hold none of these. A machine that
has the guardian key is the trust anchor of the whole system: treat it the way
you would treat a signing service.

## 2. Configuration

Required, no defaults (the service exits 2 and names the variable otherwise):

| Variable | Value |
| --- | --- |
| `AEGIS_GUARDIAN_KEY` | a 32 byte hex private key generated for this deployment and held nowhere else |
| `AEGIS_POLICY_PATH` | path to the policy file inside the container, for example `policies/dev.yaml` for the demo policy or your own file |

Public chain (recommended; without both, the container runs a local anvil and
every restart is a fresh chain with an empty audit log):

| Variable | Value |
| --- | --- |
| `AEGIS_RPC_URL` | an RPC endpoint of the chain, for example `https://sepolia.base.org` |
| `AEGIS_DEPLOYER_KEY` | a funded throwaway key on that chain; it becomes the operator and pays for anchors |
| `AEGIS_EXPLORER_URL` | only for chains the built in table does not know (see `python/aegis/chains.py`) |

Behavior switches, all off unless set to the literal `true`:

| Variable | Effect |
| --- | --- |
| `AEGIS_ALLOW_LOCAL_FALLBACK` | when the public deployment fails (RPC unreachable, key unfunded), run a local anvil instead of refusing to start. The startup log then says `mode: local anvil (FALLBACK, opted in)` and the console labels the chain `local`. Never set this on a machine whose anchors anyone relies on |
| `AEGIS_ALLOW_DEV_KEYS` | accept anvil's public development keys as guardian or deployer. Local dev chains only; `start.sh` sets it itself for a local anvil and nothing else should |
| `AEGIS_DUAL_CONTROL` | require two distinct approvers per decision |

Frontend facing:

| Variable | Value |
| --- | --- |
| `AEGIS_CORS_ORIGINS` | comma separated origins the console is served from, for example `https://your-console.example` |
| `AEGIS_RP_ID`, `AEGIS_EXPECTED_ORIGIN` | the domain and origin the console page is served from (not the API), for phone passkeys: `your-console.example` and `https://your-console.example` |
| `VITE_API_URL` (console build) | the API's public URL |

Paths and ports (`AEGIS_STATE_DIR`, `AEGIS_API_HOST`, `AEGIS_API_PORT`) are
set in `fly.toml` and the Dockerfile; the state directory must be a persistent
volume or the audit log dies with the machine.

## 3. Generate the keys

```bash
python - <<'PY'
from eth_account import Account
guardian, deployer = Account.create(), Account.create()
print("guardian address:", guardian.address)
print("AEGIS_GUARDIAN_KEY=" + guardian.key.hex())
print("deployer address:", deployer.address)
print("AEGIS_DEPLOYER_KEY=" + deployer.key.hex())
PY
```

Keep the guardian key only in the deployment's secret store. Fund the deployer
address on the chain you chose (Base Sepolia: the Coinbase faucet at
<https://portal.cdp.coinbase.com/products/faucet>, about 0.02 ETH is plenty).
Never use a key that holds anything of value.

## 4. API on Fly

```bash
curl -L https://fly.io/install.sh | sh && fly auth login
fly apps create <your-app-name>            # then set `app` in fly.toml
fly volumes create aegis_data --size 1     # persistent state directory

fly secrets set \
  AEGIS_GUARDIAN_KEY=0x<guardian key> \
  AEGIS_DEPLOYER_KEY=0x<deployer key> \
  AEGIS_RPC_URL=https://sepolia.base.org \
  AEGIS_CORS_ORIGINS=https://<your-console-domain> \
  AEGIS_RP_ID=<your-console-domain> \
  AEGIS_EXPECTED_ORIGIN=https://<your-console-domain>

fly deploy                                  # first build takes a few minutes (forge build)
fly logs | grep '\[start\]'                 # expect "mode: public base-sepolia"
```

`fly.toml` sets `AEGIS_POLICY_PATH=policies/dev.yaml`, the demo policy whose
allowlist is anvil's accounts; replace it with your own file (copy it into
`policies/` before the build, or mount it) before anything real depends on the
deployment.

Create the first approver on the machine. The token is printed once; hand it
to the person, who pastes it into the console's approver field:

```bash
fly ssh console -C "aegis --state-dir /data/aegis approver add ops-casey --name Casey"
```

## 5. Console on Vercel

```bash
cd frontend
vercel link
vercel env add VITE_API_URL production      # https://<your-app-name>.fly.dev
vercel --prod
```

The URL it prints is the console domain used in the CORS and passkey
variables above; set those secrets and redeploy the API if you did not know
the domain beforehand.

## 6. Verify before anyone relies on it

```bash
API=https://<your-app-name>.fly.dev
curl -s $API/metrics | python -m json.tool | grep -A8 '"chain"'
# chain_name "base-sepolia", public true, guardian_verified true
```

`guardian_verified: true` means the key the service signs with is the key the
deployed token trusts; the service refuses to start when it is not. Then, in
the console:

1. Paste the approver token; the status bar names the approver.
2. Console page, fire a canned instruction; the large transfer escalates.
3. Approve it; the transfer executes; the audit record shows the approver.
4. Press *pair phone*, open `/guardian` on a phone, enter the code, approve
   the next escalation with Face ID; the record shows
   *human presence: passkey verified*.
5. Anchor (dashboard button or `curl -X POST $API/anchor`) and open the
   anchor transaction on the explorer the proof links to.

Only after step 5 passes on a public chain is the deployment something to
cite (spec AC9.4).

## 7. Operations

- Restarts reuse the deployment while the contracts still hold code; the
  audit log and approvers live on the volume.
- Rotating the guardian key means redeploying the suite (the token trusts one
  guardian); `devstack --reuse` refuses a state whose guardian differs from
  the configured key, so a mismatch cannot start quietly.
- Revoke an approver with `aegis approver revoke <id>`; their token and any
  passkey paired to them stop working at once.
- `/metrics` exposes only the scheme and host of the RPC URL, so a keyed
  provider URL does not leak.
- If the Fly builder cannot run `forge build`, build the contracts locally
  (`cd contracts && forge build`), remove the `forge build` line from the
  Dockerfile and drop `contracts/out` from `.dockerignore` so the artifacts
  ship in the build context.
