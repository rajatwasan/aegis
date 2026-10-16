"""W1 and W5 tests: the guardian key and the policy path have no defaults.

Regression tests for the findings that ``ApprovalConfig`` and ``ApiConfig``
fell back to anvil's public dev key 9 when ``AEGIS_GUARDIAN_KEY`` was unset
(AGENTS.md C3) and to ``policies/default.yaml`` when ``AEGIS_POLICY_PATH`` was
unset (C9, C10).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from eth_account import Account

from aegis.api import ApiConfig
from aegis.approval import ApprovalConfig
from aegis.approval.config import guardian_key_from_env, policy_path_from_env
from aegis.devkeys import KEYS, address_of, is_dev_address, is_dev_key
from aegis.errors import ConfigError

FRESH_KEY = Account.create().key.hex()


class TestGuardianKeyFromEnv:
    def test_config_guardian_key_required(self) -> None:
        with pytest.raises(ConfigError, match="AEGIS_GUARDIAN_KEY is required"):
            guardian_key_from_env({})
        with pytest.raises(ConfigError, match="AEGIS_GUARDIAN_KEY is required"):
            guardian_key_from_env({"AEGIS_GUARDIAN_KEY": "   "})

    def test_config_rejects_malformed_key(self) -> None:
        with pytest.raises(ConfigError, match="not a usable private key"):
            guardian_key_from_env({"AEGIS_GUARDIAN_KEY": "0xreplace-with-a-key"})

    def test_config_dev_key_refused_without_opt_in(self) -> None:
        with pytest.raises(ConfigError, match="public development keys"):
            guardian_key_from_env({"AEGIS_GUARDIAN_KEY": KEYS[9]})
        with pytest.raises(ConfigError, match="public development keys"):
            guardian_key_from_env({"AEGIS_GUARDIAN_KEY": KEYS[9], "AEGIS_ALLOW_DEV_KEYS": "yes"})

    def test_config_dev_key_allowed_with_opt_in(self) -> None:
        env = {"AEGIS_GUARDIAN_KEY": KEYS[9], "AEGIS_ALLOW_DEV_KEYS": "true"}
        assert guardian_key_from_env(env) == KEYS[9]

    def test_config_fresh_key_needs_no_opt_in(self) -> None:
        assert guardian_key_from_env({"AEGIS_GUARDIAN_KEY": FRESH_KEY}) == FRESH_KEY

    def test_approval_config_has_no_default_guardian_key(self) -> None:
        assert "default" not in repr(ApprovalConfig.model_fields["guardian_key"])
        with pytest.raises(Exception, match="guardian_key"):
            ApprovalConfig()  # type: ignore[call-arg]

    def test_from_env_paths_refuse_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AEGIS_GUARDIAN_KEY", raising=False)
        monkeypatch.setenv("AEGIS_POLICY_PATH", "policies/dev.yaml")
        with pytest.raises(ConfigError):
            ApprovalConfig.from_env()
        with pytest.raises(ConfigError):
            ApiConfig.from_env()


class TestPolicyPathFromEnv:
    def test_policy_path_required(self) -> None:
        with pytest.raises(ConfigError, match="AEGIS_POLICY_PATH is required"):
            policy_path_from_env({})
        with pytest.raises(ConfigError, match="AEGIS_POLICY_PATH is required"):
            policy_path_from_env({"AEGIS_POLICY_PATH": "   "})

    def test_policy_path_is_returned_as_given(self) -> None:
        assert policy_path_from_env({"AEGIS_POLICY_PATH": " policies/dev.yaml "}) == (
            "policies/dev.yaml"
        )

    def test_approval_config_has_no_default_policy_path(self) -> None:
        assert "default" not in repr(ApprovalConfig.model_fields["policy_path"])
        with pytest.raises(Exception, match="policy_path"):
            ApprovalConfig(guardian_key=FRESH_KEY)  # type: ignore[call-arg]

    def test_from_env_paths_refuse_without_policy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AEGIS_GUARDIAN_KEY", FRESH_KEY)
        monkeypatch.delenv("AEGIS_POLICY_PATH", raising=False)
        with pytest.raises(ConfigError, match="AEGIS_POLICY_PATH is required"):
            ApprovalConfig.from_env()
        with pytest.raises(ConfigError, match="AEGIS_POLICY_PATH is required"):
            ApiConfig.from_env()

    def test_no_file_is_named_default(self) -> None:
        """The dev policy says what it is in its name and header (C10)."""
        policies = Path(__file__).resolve().parents[2] / "policies"
        assert not (policies / "default.yaml").exists()
        header = (policies / "dev.yaml").read_text().splitlines()[0]
        assert "DEV" in header and "local" in header


class TestDeployerKey:
    def test_devstack_deployer_key_required_without_opt_in(self) -> None:
        from aegis.devstack import resolve_operator_key

        with pytest.raises(ConfigError, match="AEGIS_DEPLOYER_KEY"):
            resolve_operator_key(None, {})
        assert resolve_operator_key(None, {"AEGIS_ALLOW_DEV_KEYS": "true"}) == KEYS[0]
        assert resolve_operator_key(FRESH_KEY, {}) == FRESH_KEY


class TestDevKeys:
    def test_every_dev_key_derives_its_listed_address(self) -> None:
        from aegis.devkeys import ANVIL_ACCOUNTS

        assert len(ANVIL_ACCOUNTS) == 10
        for index, (address, key) in ANVIL_ACCOUNTS.items():
            assert address_of(key) == address, index
            assert is_dev_key(key)
            assert is_dev_key(key.upper().replace("0X", "0x"))
            assert is_dev_address(address.lower())

    def test_fresh_key_is_not_dev(self) -> None:
        assert not is_dev_key(FRESH_KEY)
        assert not is_dev_key("not-a-key")
        assert not is_dev_address(address_of(FRESH_KEY))


class TestEntrypoint:
    def test_api_entrypoint_exits_2_without_guardian_key(self, tmp_path: Path) -> None:
        """AC1.2: ``python -m aegis.api`` prints one line and exits 2, no traceback."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("AEGIS_")}
        env["AEGIS_STATE_DIR"] = str(tmp_path)
        proc = subprocess.run(
            [sys.executable, "-m", "aegis.api"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 2
        assert "AEGIS_GUARDIAN_KEY is required" in proc.stderr
        assert "Traceback" not in proc.stderr

    def test_api_entrypoint_exits_2_without_policy_path(self, tmp_path: Path) -> None:
        """AC5.2 at the process boundary: the key alone is not enough to start."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("AEGIS_")}
        env["AEGIS_STATE_DIR"] = str(tmp_path)
        env["AEGIS_GUARDIAN_KEY"] = FRESH_KEY
        proc = subprocess.run(
            [sys.executable, "-m", "aegis.api"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 2
        assert "AEGIS_POLICY_PATH is required" in proc.stderr
        assert "Traceback" not in proc.stderr
