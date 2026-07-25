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
includes the live chain probe, so if it answers, anvil + deploy worked.

Notes:
- A machine restart = fresh chain + empty audit log (start.sh redeploys).
  That's fine for the demo; `fly.toml` pins the machine on so it won't
  auto-stop overnight.
- anvil is NOT exposed publicly — only the API is. All chain reads go
  server-side, which the console already expects.

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
