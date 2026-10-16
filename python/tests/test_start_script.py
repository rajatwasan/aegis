"""W8 tests: deploy/start.sh falls back to a local chain only when told to.

The script is run for real with stub ``python``, ``anvil`` and ``curl``
executables first on PATH, so every branch is exercised without a chain or a
container (AGENTS.md T6, spec AC8.1, AC8.2).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
START_SH = REPO_ROOT / "deploy" / "start.sh"

FRESH_KEY = "0x" + "11" * 32

STUB_PYTHON = """#!/usr/bin/env bash
# records every invocation; devstack succeeds or fails per STUB_PUBLIC_DEPLOY
printf '%s\\n' "python $*" >> "$STUB_LOG"
case "$*" in
  *aegis.devstack*)
    if [[ "$*" == *"--rpc-url http://127.0.0.1:8545"* ]]; then
      printf '{"chain_name": "anvil"}\\n' > "$AEGIS_STATE_DIR/state.json"
      exit 0
    fi
    if [ "${STUB_PUBLIC_DEPLOY:-ok}" = "ok" ]; then
      printf '{"chain_name": "base-sepolia"}\\n' > "$AEGIS_STATE_DIR/state.json"
      exit 0
    fi
    echo "stub: unfunded key" >&2
    exit 1
    ;;
  *aegis.api*)
    echo "stub api serving"
    exit 0
    ;;
esac
exit 0
"""

STUB_CURL = """#!/usr/bin/env bash
# the RPC probe: the local anvil always answers, the public one per STUB_PUBLIC_RPC
printf '%s\\n' "curl $*" >> "$STUB_LOG"
if [[ "$*" == *"127.0.0.1:8545"* ]]; then exit 0; fi
[ "${STUB_PUBLIC_RPC:-up}" = "up" ]
"""

STUB_ANVIL = """#!/usr/bin/env bash
printf '%s\\n' "anvil $*" >> "$STUB_LOG"
sleep 2
"""


@pytest.fixture()
def stubs(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("python", STUB_PYTHON), ("curl", STUB_CURL), ("anvil", STUB_ANVIL)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def run_start(stubs: Path, tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess, str]:
    log = tmp_path / "calls.log"
    log.write_text("")
    state_dir = tmp_path / "state"
    full_env = {
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "STUB_LOG": str(log),
        "AEGIS_STATE_DIR": str(state_dir),
        "AEGIS_GUARDIAN_KEY": FRESH_KEY,
        "AEGIS_POLICY_PATH": "policies/dev.yaml",
        **env,
    }
    proc = subprocess.run(
        ["bash", str(START_SH)], env=full_env, capture_output=True, text=True, timeout=60
    )
    return proc, log.read_text()


PUBLIC = {"AEGIS_RPC_URL": "https://sepolia.example", "AEGIS_DEPLOYER_KEY": "0x" + "22" * 32}


class TestConfiguration:
    def test_refuses_without_guardian_key(self, stubs: Path, tmp_path: Path) -> None:
        proc, calls = run_start(stubs, tmp_path, AEGIS_GUARDIAN_KEY="")
        assert proc.returncode == 2
        assert "AEGIS_GUARDIAN_KEY is not set" in proc.stderr
        assert calls == ""  # nothing was launched

    def test_refuses_without_policy_path(self, stubs: Path, tmp_path: Path) -> None:
        proc, calls = run_start(stubs, tmp_path, AEGIS_POLICY_PATH="")
        assert proc.returncode == 2
        assert "AEGIS_POLICY_PATH is not set" in proc.stderr
        assert calls == ""


class TestModes:
    def test_no_public_chain_runs_local_anvil_and_says_so(
        self, stubs: Path, tmp_path: Path
    ) -> None:
        proc, calls = run_start(stubs, tmp_path)
        assert proc.returncode == 0, proc.stderr
        assert "[start] mode: local anvil (dev)" in proc.stdout
        assert "anvil --port 8545" in calls
        assert "aegis.devstack --rpc-url http://127.0.0.1:8545" in calls
        assert "stub api serving" in proc.stdout

    def test_public_chain_deploys_there_and_names_it(self, stubs: Path, tmp_path: Path) -> None:
        proc, calls = run_start(stubs, tmp_path, **PUBLIC)
        assert proc.returncode == 0, proc.stderr
        assert "[start] mode: public base-sepolia" in proc.stdout
        assert "--rpc-url https://sepolia.example" in calls
        assert "anvil --port" not in calls
        assert "stub api serving" in proc.stdout

    def test_failed_public_deploy_refuses_without_opt_in(self, stubs: Path, tmp_path: Path) -> None:
        """AC8.1: the configured chain is unusable and nobody said a stand in is fine."""
        proc, calls = run_start(stubs, tmp_path, STUB_PUBLIC_DEPLOY="fail", **PUBLIC)
        assert proc.returncode == 1
        assert "AEGIS_ALLOW_LOCAL_FALLBACK is not true" in proc.stderr
        assert "anvil --port" not in calls
        assert "aegis.api" not in calls  # the API never came up

    def test_unreachable_public_rpc_refuses_without_opt_in(
        self, stubs: Path, tmp_path: Path
    ) -> None:
        proc, calls = run_start(stubs, tmp_path, STUB_PUBLIC_RPC="down", **PUBLIC)
        assert proc.returncode == 1
        assert "AEGIS_ALLOW_LOCAL_FALLBACK is not true" in proc.stderr
        assert "aegis.devstack" not in calls  # no deploy was even attempted
        assert "aegis.api" not in calls

    def test_failed_public_deploy_falls_back_when_opted_in(
        self, stubs: Path, tmp_path: Path
    ) -> None:
        proc, calls = run_start(
            stubs,
            tmp_path,
            STUB_PUBLIC_DEPLOY="fail",
            AEGIS_ALLOW_LOCAL_FALLBACK="true",
            **PUBLIC,
        )
        assert proc.returncode == 0, proc.stderr
        assert "[start] mode: local anvil (FALLBACK, opted in)" in proc.stdout
        assert "WARNING" in proc.stderr
        assert "anvil --port 8545" in calls
        assert "aegis.devstack --rpc-url http://127.0.0.1:8545" in calls
        assert "stub api serving" in proc.stdout

    def test_fallback_opt_in_is_the_literal_true(self, stubs: Path, tmp_path: Path) -> None:
        proc, _ = run_start(
            stubs, tmp_path, STUB_PUBLIC_DEPLOY="fail", AEGIS_ALLOW_LOCAL_FALLBACK="yes", **PUBLIC
        )
        assert proc.returncode == 1
