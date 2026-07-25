#!/usr/bin/env bash
# Boot the public demo stack inside one container:
# anvil (internal only) -> deploy Aegis suite -> Guardian Console API (public).
# A machine restart redeploys a fresh, clean world — acceptable for the demo.
set -euo pipefail

STATE_DIR="${AEGIS_STATE_DIR:-/data/aegis}"
mkdir -p "$STATE_DIR"

echo "[start] launching anvil (internal :8545)..."
anvil --port 8545 --silent &

for _ in $(seq 1 100); do
  curl -s -X POST http://127.0.0.1:8545 \
    -H 'content-type: application/json' \
    --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
    >/dev/null 2>&1 && break
  sleep 0.2
done
echo "[start] anvil is up"

echo "[start] deploying Aegis suite..."
python -m aegis.devstack --rpc-url http://127.0.0.1:8545 --state-dir "$STATE_DIR"

echo "[start] starting Guardian Console API on :${AEGIS_API_PORT:-8080}"
exec python -m aegis.api
