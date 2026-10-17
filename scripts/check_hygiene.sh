#!/usr/bin/env bash
# Repository hygiene gate (AGENTS.md R1, R3, R43, R48; SPEC.md W8).
# Fails on: anvil dev private keys outside the dev chain module and tests;
# clean room strings; tracked files that .gitignore says must not be tracked;
# private key fields in tracked JSON; dev keys in .env.example.
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
report() { echo "hygiene: $1"; fail=1; }

DEV_KEYS='ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80|2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6|59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d|5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a'

# (a) dev private keys only in aegis/devchain.py and the test suite
hits=$(git grep -l -i -E "$DEV_KEYS" -- . ':!python/aegis/devchain.py' ':!python/tests/' ':!scripts/check_hygiene.sh' || true)
[ -n "$hits" ] && report "anvil dev private key outside devchain.py and tests: $hits"

# (b) clean room strings (R48); the pattern is assembled so this file does not match itself
CLEAN_ROOM="$(printf '%s|%s|%s' 'erc[-_ ]?75''18' 'dyc''ist' 'zon''iqx')"
hits=$(git grep -l -i -E "$CLEAN_ROOM" -- . ':!frontend/package-lock.json' ':!AGENTS.md' || true)  # AGENTS.md R48 is where the rule names them
[ -n "$hits" ] && report "clean room string present in: $hits"

# (c) tracked files that .gitignore excludes
hits=$(git ls-files -ci --exclude-standard || true)
[ -n "$hits" ] && report "tracked files matching .gitignore: $hits"

# (d) private key fields in tracked JSON
hits=$(git grep -l -E '"(operator_key|guardian_key|deployer_key)"[[:space:]]*:' -- '*.json' || true)
[ -n "$hits" ] && report "private key field in tracked JSON: $hits"

# (e) .env.example ships placeholders, never a usable key
if grep -q -i -E "$DEV_KEYS" .env.example; then report ".env.example contains an anvil dev key"; fi

[ "$fail" -eq 0 ] && echo "hygiene: ok"
exit "$fail"
