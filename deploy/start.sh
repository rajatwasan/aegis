#!/usr/bin/env bash
# Boot the hosted stack inside one container: deploy (or reuse) the Aegis
# suite, then serve the Guardian Console API.
#
# Public chain (preferred): AEGIS_RPC_URL + a funded AEGIS_DEPLOYER_KEY make
# every anchored Merkle root a transaction anyone can open in an explorer. The
# deployment is reused across restarts while the contracts still exist (public
# chains cost gas, and redeploying would orphan the audit log).
#
# Local anvil is what runs when no public chain is configured. It is also the
# fallback when the public deployment fails, but only when
# AEGIS_ALLOW_LOCAL_FALLBACK=true says so: a hosted machine that quietly swaps
# a public chain for a throwaway one would be lying about what it anchors
# (AGENTS.md C9; spec W8, decision D7).
#
# Exit codes: 2 for missing configuration, 1 when the configured chain cannot
# be used and no fallback was allowed.
set -euo pipefail

STATE_DIR="${AEGIS_STATE_DIR:-/data/aegis}"
PUBLIC_RPC="${AEGIS_RPC_URL:-}"
DEPLOYER_KEY="${AEGIS_DEPLOYER_KEY:-}"
ALLOW_FALLBACK="${AEGIS_ALLOW_LOCAL_FALLBACK:-false}"
LOCAL_RPC="http://127.0.0.1:8545"
mkdir -p "$STATE_DIR"

# The guardian key is the one secret this service exists to hold. There is no
# default: generate one and set it (fly secrets set AEGIS_GUARDIAN_KEY=0x...).
if [ -z "${AEGIS_GUARDIAN_KEY:-}" ]; then
  echo "[start] AEGIS_GUARDIAN_KEY is not set; refusing to start (see deploy/DEPLOY.md)" >&2
  exit 2
fi
# The policy is named, never assumed: its hash is bound into every authorization.
if [ -z "${AEGIS_POLICY_PATH:-}" ]; then
  echo "[start] AEGIS_POLICY_PATH is not set; refusing to start (see deploy/DEPLOY.md)" >&2
  exit 2
fi

rpc_alive() {
  curl -fsS -X POST "$1" \
    -H 'content-type: application/json' \
    --max-time 10 \
    --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
    >/dev/null 2>&1
}

start_anvil() {
  echo "[start] launching anvil (internal :8545)..."
  anvil --port 8545 --silent &
  for _ in $(seq 1 100); do
    rpc_alive "$LOCAL_RPC" && break
    sleep 0.2
  done
  echo "[start] anvil is up"
}

deploy_local() {
  start_anvil
  # local anvil is a dev chain: anvil account 0 deploys, opted in explicitly
  export AEGIS_ALLOW_DEV_KEYS=true
  # a fresh anvil has no contracts, so --reuse correctly redeploys
  python -m aegis.devstack --rpc-url "$LOCAL_RPC" --state-dir "$STATE_DIR" --reuse
}

chain_name() {
  # the name devstack recorded for the chain it deployed to (state.json)
  sed -n 's/.*"chain_name": *"\([^"]*\)".*/\1/p' "$STATE_DIR/state.json" 2>/dev/null | head -n 1
}

mode=""
if [ -n "$PUBLIC_RPC" ] && [ -n "$DEPLOYER_KEY" ]; then
  echo "[start] public chain configured; probing RPC..."
  if rpc_alive "$PUBLIC_RPC" \
      && python -m aegis.devstack \
           --rpc-url "$PUBLIC_RPC" \
           --operator-key "$DEPLOYER_KEY" \
           --state-dir "$STATE_DIR" \
           --reuse; then
    mode="public $(chain_name)"
  elif [ "$ALLOW_FALLBACK" = "true" ]; then
    echo "[start] WARNING: public deployment failed (unreachable RPC or unfunded key);" \
         "AEGIS_ALLOW_LOCAL_FALLBACK=true, so running a local anvil instead" >&2
    deploy_local
    mode="local anvil (FALLBACK, opted in)"
  else
    echo "[start] public deployment failed (unreachable RPC or unfunded key) and" \
         "AEGIS_ALLOW_LOCAL_FALLBACK is not true; refusing to start on a chain" \
         "that is not the one configured" >&2
    exit 1
  fi
else
  echo "[start] no AEGIS_RPC_URL/AEGIS_DEPLOYER_KEY set; using local anvil"
  deploy_local
  mode="local anvil (dev)"
fi

echo "[start] mode: $mode"
echo "[start] starting Guardian Console API on :${AEGIS_API_PORT:-8080}"
exec python -m aegis.api
