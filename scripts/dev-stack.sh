#!/usr/bin/env bash
# Foreground dev stack for the Guardian Console. HUMAN-ONLY: runs until ^C.
# Never invoke from tests, CI, or unattended automation.
#
#   anvil (spawned here unless one already answers on $AEGIS_ANVIL_PORT)
#   -> deploy the Aegis suite, write .aegis/dev/state.json
#   -> uvicorn API on :8000
#   -> vite dev server on :5173
set -euo pipefail
cd "$(dirname "$0")/.."

VENV_PY="$(pwd)/.venv/bin/python"
STATE_DIR="$(pwd)/.aegis/dev"
PORT="${AEGIS_ANVIL_PORT:-8545}"
RPC_URL="http://127.0.0.1:${PORT}"
API_PORT="${AEGIS_API_PORT:-8000}"

command -v anvil >/dev/null 2>&1 || { echo "anvil not found; install foundry" >&2; exit 1; }
[ -x "$VENV_PY" ] || { echo "$VENV_PY not found; run 'make setup'" >&2; exit 1; }
[ -d frontend/node_modules ] || (cd frontend && npm install)

if [ ! -f contracts/out/GuardedToken.sol/GuardedToken.json ]; then
  (cd contracts && forge build >/dev/null)
fi

PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do kill "$pid" >/dev/null 2>&1 || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if ! curl -s -X POST "$RPC_URL" -H 'content-type: application/json' \
    --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' >/dev/null 2>&1; then
  echo "Starting anvil on ${RPC_URL}..."
  anvil --port "$PORT" --silent &
  PIDS+=($!)
  for _ in $(seq 1 50); do
    curl -s -X POST "$RPC_URL" -H 'content-type: application/json' \
      --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
      >/dev/null 2>&1 && break
    sleep 0.2
  done
else
  echo "Using existing anvil on ${RPC_URL}"
fi

"$VENV_PY" -m aegis.devstack --rpc-url "$RPC_URL" --state-dir "$STATE_DIR"

# Approvals are authenticated (AGENTS.md R4). The dev stack mints a token for
# the approver "dev" unless the caller set AEGIS_APPROVER_TOKENS, and an admin
# token for pairing passkeys unless AEGIS_ADMIN_TOKEN is set. Both live only in
# this process and are printed once below.
if [ -z "${AEGIS_APPROVER_TOKENS:-}" ]; then
  DEV_TOKEN="$("$VENV_PY" -c 'import secrets; print(secrets.token_hex(16))')"
  export AEGIS_APPROVER_TOKENS="dev:${DEV_TOKEN}"
else
  DEV_TOKEN="${AEGIS_APPROVER_TOKENS#*:}"
fi
if [ -z "${AEGIS_ADMIN_TOKEN:-}" ]; then
  export AEGIS_ADMIN_TOKEN="$("$VENV_PY" -c 'import secrets; print(secrets.token_hex(16))')"
fi

export AEGIS_STATE_DIR="$STATE_DIR"
export AEGIS_API_PORT="$API_PORT"
"$VENV_PY" -m aegis.api &
PIDS+=($!)

echo
echo "Guardian Console: http://localhost:5173  (API on :${API_PORT}, RPC on :${PORT})"
echo "Approver token (paste into the console's token field): ${DEV_TOKEN}"
echo "Admin token (pairing codes):                           ${AEGIS_ADMIN_TOKEN}"
echo "Ctrl-C stops everything."
echo
(cd frontend && exec npm run dev)
