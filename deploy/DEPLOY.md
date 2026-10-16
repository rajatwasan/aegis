# Aegis public deployment — Night Hack prep

Goal: kill "localhost" before tonight. One Fly machine runs anvil + the
Guardian Console API; Vercel serves the console. Zero code changes — CORS and
the API URL were already env-configurable.

Budget ~30–45 min including account signup. Everything runs from the repo root.

## 0. One-time tooling

```bash
# Fly CLI
curl -L https://fly.io/install.sh | sh      # then follow PATH instructions
fly auth signup                              # or: fly auth login

# Vercel CLI (uses your npm)
npm i -g vercel
vercel login
```

## 0b. Guardian key (required before anything else)

The approval service refuses to start without `AEGIS_GUARDIAN_KEY`, and the
contracts are deployed with that key's address as the token guardian. Generate
a key that exists nowhere else and set it as a secret before `fly deploy`:

```bash
python - <<'PY'
from eth_account import Account
a = Account.create()
print("guardian address:", a.address); print("AEGIS_GUARDIAN_KEY:", a.key.hex())
PY
fly secrets set AEGIS_GUARDIAN_KEY=0x<the key above>
```

Anvil's public development keys are refused unless `AEGIS_ALLOW_DEV_KEYS=true`;
never set that on a hosted machine. At startup the API reads the token's
`guardian()` and refuses to start if it differs from the configured key; check
`/metrics` for `chain.guardian_verified: true` after deploy.

## 1. Backend (anvil + API) on Fly

Files: `deploy/Dockerfile`, `deploy/start.sh`, `fly.toml`, `.dockerignore`.

```bash
cd <repo-root>

# create the app (pick another name if taken, then update fly.toml `app`)
fly apps create aegis-guardian

fly deploy          # remote builder; first build ~5-8 min (forge build inside)
```

Smoke test:

```bash
curl https://aegis-guardian.fly.dev/metrics | head
curl https://aegis-guardian.fly.dev/agent/instructions
```

You should see decision counts and the canned instruction chips. `/metrics`
includes the live chain probe, so if it answers, the chain + deploy worked.

Notes:
- Without the Base Sepolia secrets below, `start.sh` runs a local anvil and a
  machine restart means a fresh chain + empty audit log. The console labels that
  chain `local` and shows no explorer links.
- anvil is NOT exposed publicly — only the API is. All chain reads go
  server-side, which the console already expects.

## 1b. Anchor on Base Sepolia (public, verifiable roots)

Anchoring to a public chain is what makes "PROOF OK" checkable by someone who
does not trust the server: the anchoring transaction is on a block explorer and
the console links straight to it. See `docs/adr/005-public-testnet-anchoring.md`.

```bash
# a throwaway deployer key + its address (never a key that holds value)
python - <<'PY'
from eth_account import Account
a = Account.create()
print("address:", a.address); print("key:", a.key.hex())
PY
```

Fund the printed address with Base Sepolia ETH (~0.02 is plenty):
Coinbase faucet <https://portal.cdp.coinbase.com/products/faucet> or
<https://basefaucet.com>. Then:

```bash
fly secrets set \
  AEGIS_RPC_URL=https://sepolia.base.org \
  AEGIS_DEPLOYER_KEY=0x<the key you just funded>
# setting secrets restarts the machine, which deploys the suite on Base Sepolia
fly logs | grep -E "deploying|reusing|WARNING"
```

Confirm it took:

```bash
curl -s https://aegis-guardian.fly.dev/metrics | python -m json.tool | grep -A6 '"chain"'
# expect chain_name "base-sepolia", public true, an explorer_url and anchor_url
```

Then anchor and follow the link (or press **Anchor now** on the dashboard):

```bash
curl -s -X POST https://aegis-guardian.fly.dev/anchor | python -m json.tool
# -> batch.tx_url = https://sepolia.basescan.org/tx/0x...  <- open this
```

Notes:
- The deployment is **reused** across restarts while the contracts still hold
  code, so restarts no longer burn faucet gas or orphan the audit log.
- If the RPC is unreachable or the key is unfunded, `start.sh` falls back to a
  local anvil rather than failing — check `fly logs` for `WARNING` and the
  status bar for a `local` badge before demoing.
- The deployer is the operator: it owns the registry, holds the minted supply,
  and pays for anchors. Top it up if anchoring starts failing.
- `/metrics` exposes only scheme + host of the RPC url, so a keyed provider url
  (`.../v2/<key>`) does not leak.

## 2. Frontend (Guardian Console) on Vercel

```bash
cd frontend
vercel link                                  # create project "aegis-console"
vercel env add VITE_API_URL production       # value: https://aegis-guardian.fly.dev
vercel --prod
```

Note the URL it prints, e.g. `https://aegis-console.vercel.app`.

## 3. Point CORS at the Vercel origin

```bash
fly secrets set AEGIS_CORS_ORIGINS=https://aegis-console.vercel.app
# (this restarts the machine -> fresh clean chain, which is what you want)
```

## 4. Full-loop smoke test (the thing that matters)

Open the Vercel URL **on your phone as well as your laptop**:

1. Dashboard loads, status bar shows the chain live (SSE connected).
2. Console page → fire a canned instruction → steps stream in.
3. The big transfer escalates → appears in Approvals with TTL ticking.
4. Approve with a comment → execution resumes → transfer lands.
5. Audit → the record → Verify → **PROOF OK**.
6. POST /anchor via the dashboard/console if exposed, or:
   `curl -X POST https://aegis-guardian.fly.dev/anchor`

If SSE doesn't reconnect on phone-lock/unlock, note it — tonight's feature
work will touch that path anyway.

## Hackathon disclosure

Everything deployed today is pre-existing work and must be disclosed as such.
Tonight's judged work = the new guardian-on-phone / proof-of-human feature,
built during event hours on top of this.

## Fallbacks

- Fly build fails on forge: build artifacts locally (`cd contracts && forge
  build`), remove the `RUN cd contracts && forge build` line, drop
  `contracts/out` from `.dockerignore` so the artifacts ship in the context.
- Vercel misbehaving: `cd frontend && npm run build` and drag `dist/` into
  Netlify Drop as an emergency static host (set VITE_API_URL first via
  `VITE_API_URL=... npm run build`).
- Venue wifi dies mid-demo: phone hotspot; everything is public HTTPS, so
  nothing depends on the venue network.
