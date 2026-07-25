#!/usr/bin/env bash
# Boot the public demo stack inside one container.
#
# Preferred: deploy the Aegis suite to a PUBLIC chain (Base Sepolia) so every
# anchored Merkle root is a transaction anyone can open in a block explorer.
# That needs AEGIS_RPC_URL + a funded AEGIS_DEPLOYER_KEY (fly secrets).
#
# Fallback: if the public RPC is unreachable or the deployer is unfunded, run a
# local anvil so the demo still works — the console labels the chain, so a
# local fallback is never mistaken for the real thing.
#
# The deployment is REUSED across restarts when the contracts still exist
# (public chains cost gas, and redeploying would orphan the audit log).
set -euo pipefail

STATE_DIR="${AEGIS_STATE_DIR:-/data/aegis}"
PUBLIC_RPC="${AEGIS_RPC_URL:-}"
DEPLOYER_KEY="${AEGIS_DEPLOYER_KEY:-}"
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
      echo "[start] WARNING: public deploy failed (unfunded key?); falling back to anvil" >&2
    fi
  else
    echo "[start] WARNING: public RPC unreachable; falling back to anvil" >&2
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
