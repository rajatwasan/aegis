#!/usr/bin/env bash
# Headless end-to-end Aegis demo: spawn anvil, deploy, run the scripted agent
# batch (4 auto-allowed transfers, 1 escalated + human-approved + guardian-
# signed, 1 denied to a frozen address), anchor the audit batch on-chain, and
# verify every decision's Merkle inclusion proof. Prints a narrative; exits 0
# only if the whole loop succeeds.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV_PY="$(pwd)/.venv/bin/python"
AEGIS="$(pwd)/.venv/bin/aegis"
STATE_DIR="$(pwd)/.aegis/demo"
PORT="${AEGIS_ANVIL_PORT:-8545}"
RPC_URL="http://127.0.0.1:${PORT}"

command -v anvil >/dev/null 2>&1 || {
  echo "demo: 'anvil' not found; install foundry and run 'make setup'" >&2
  exit 1
}
[ -x "$VENV_PY" ] || {
  echo "demo: $VENV_PY not found; run 'make setup' first" >&2
  exit 1
}

# make sure contracts are built so the python client can load artifacts
if [ ! -f contracts/out/GuardedToken.sol/GuardedToken.json ]; then
  echo "Building contracts..."
  (cd contracts && forge build >/dev/null)
fi

rm -rf "$STATE_DIR"
mkdir -p "$STATE_DIR"

echo "Starting anvil on ${RPC_URL}..."
anvil --port "$PORT" --silent &
ANVIL_PID=$!
cleanup() {
  kill "$ANVIL_PID" >/dev/null 2>&1 || true
  wait "$ANVIL_PID" 2>/dev/null || true
}
trap cleanup EXIT

# wait for anvil to accept RPC
for _ in $(seq 1 50); do
  if curl -s -X POST "$RPC_URL" -H 'content-type: application/json' \
      --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
      >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

export AEGIS_RPC_URL="$RPC_URL"
export AEGIS_STATE_DIR="$STATE_DIR"
# throwaway anvil: anvil's public dev key 9 is the demo guardian, opted in explicitly
export AEGIS_GUARDIAN_KEY="${AEGIS_GUARDIAN_KEY:-0x2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6}"
export AEGIS_ALLOW_DEV_KEYS="${AEGIS_ALLOW_DEV_KEYS:-true}"

echo "=================================================================="
echo " AEGIS DEMO — cryptographically enforced human-in-the-loop"
echo "=================================================================="

"$VENV_PY" -m aegis.demo --rpc-url "$RPC_URL" --state-dir "$STATE_DIR"

echo
echo "=== Anchoring the audit batch on-chain (aegis anchor) ==="
"$AEGIS" --state-dir "$STATE_DIR" anchor

echo
echo "=== Verifying every decision's inclusion proof (aegis verify --all) ==="
"$AEGIS" --state-dir "$STATE_DIR" verify --all

echo
echo "Demo complete. The agent could not move gated assets without a human"
echo "approval and a guardian signature, and every decision is provably logged."
