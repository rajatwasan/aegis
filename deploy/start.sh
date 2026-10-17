#!/usr/bin/env bash
# Boot the public demo stack inside one container.
#
# Preferred: deploy the Aegis suite to a PUBLIC chain (Base Sepolia) so every
# anchored Merkle root is a transaction anyone can open in a block explorer.
# That needs AEGIS_RPC_URL + a funded AEGIS_DEPLOYER_KEY (fly secrets).
#
# Fallback: only with AEGIS_ALLOW_LOCAL_FALLBACK=true. Otherwise a public deploy
# that fails (RPC unreachable, deployer unfunded, bad key) exits 1: a hosted
# service silently running on a disposable chain is the failure this prevents.
# With no public chain configured at all, a local anvil is the explicit choice.
#
# The deployment is REUSED across restarts when the contracts still exist
# (public chains cost gas, and redeploying would orphan the audit log).
set -euo pipefail

STATE_DIR="${AEGIS_STATE_DIR:-/data/aegis}"
PUBLIC_RPC="${AEGIS_RPC_URL:-}"
DEPLOYER_KEY="${AEGIS_OPERATOR_KEY:-${AEGIS_DEPLOYER_KEY:-}}"
mkdir -p "$STATE_DIR"

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
    rpc_alive http://127.0.0.1:8545 && break
    sleep 0.2
  done
  echo "[start] anvil is up"
}

deployed=0
ALLOW_FALLBACK="${AEGIS_ALLOW_LOCAL_FALLBACK:-false}"

refuse_or_fallback() {
  if [ "$ALLOW_FALLBACK" = "true" ]; then
    echo "[start] WARNING: $1; AEGIS_ALLOW_LOCAL_FALLBACK=true, falling back to anvil" >&2
  else
    echo "[start] ERROR: $1; refusing to fall back to a local chain" >&2
    echo "[start] set AEGIS_ALLOW_LOCAL_FALLBACK=true to run on a disposable anvil" >&2
    exit 1
  fi
}

if [ -n "$PUBLIC_RPC" ] && [ -n "$DEPLOYER_KEY" ]; then
  echo "[start] public chain configured; probing RPC..."
  if rpc_alive "$PUBLIC_RPC"; then
    if python -m aegis.devstack \
        --rpc-url "$PUBLIC_RPC" \
        --operator-key "$DEPLOYER_KEY" \
        --state-dir "$STATE_DIR" \
        --reuse; then
      deployed=1
    else
      refuse_or_fallback "public deploy failed (unfunded or invalid key?)"
    fi
  else
    refuse_or_fallback "public RPC unreachable"
  fi
else
  echo "[start] no AEGIS_RPC_URL/AEGIS_DEPLOYER_KEY set; using local anvil"
fi

if [ "$deployed" -eq 0 ]; then
  start_anvil
  # a fresh anvil has no contracts, so --reuse correctly redeploys
  python -m aegis.devstack \
    --rpc-url http://127.0.0.1:8545 \
    --state-dir "$STATE_DIR" \
    --reuse
fi

echo "[start] starting Guardian Console API on :${AEGIS_API_PORT:-8080}"
exec python -m aegis.api
