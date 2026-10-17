#!/usr/bin/env bash
# W7: deploy/start.sh refuses a silent fallback to anvil when a public deploy
# fails, unless AEGIS_ALLOW_LOCAL_FALLBACK=true. Runs without a network: the
# RPC points at a closed local port, and anvil/python are stubbed on PATH.
set -uo pipefail
cd "$(dirname "$0")/../.."
STUBS="$(mktemp -d)"
trap 'rm -rf "$STUBS"' EXIT
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUBS/anvil"
printf '#!/usr/bin/env bash\necho "python $*" >> "%s/calls"; exit 0\n' "$STUBS" > "$STUBS/python"
chmod +x "$STUBS/anvil" "$STUBS/python"

run() {
  env -i PATH="$STUBS:/usr/bin:/bin" HOME="$STUBS" AEGIS_STATE_DIR="$STUBS/state" \
    AEGIS_RPC_URL="http://127.0.0.1:1" AEGIS_DEPLOYER_KEY="0x$(printf 'ab%.0s' {1..32})" \
    "$@" bash deploy/start.sh >"$STUBS/out" 2>&1
}

fail=0
run; code=$?
if [ "$code" -ne 1 ] || ! grep -q "refusing to fall back" "$STUBS/out"; then
  echo "FAIL: expected exit 1 and a refusal without the flag (got $code)"; cat "$STUBS/out"; fail=1
else
  echo "ok: refuses fallback by default"
fi

rm -f "$STUBS/calls"
run AEGIS_ALLOW_LOCAL_FALLBACK=true; code=$?
if [ "$code" -ne 0 ] || ! grep -q "falling back to anvil" "$STUBS/out"; then
  echo "FAIL: expected fallback with the flag (got $code)"; cat "$STUBS/out"; fail=1
else
  echo "ok: falls back when explicitly allowed"
fi
exit "$fail"
