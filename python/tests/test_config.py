"""Configuration contract (SPEC.md section 5): no default secrets.

Every case here fails on the parent commit, where ``ApprovalConfig`` fell back
to the anvil dev guardian key whenever ``AEGIS_GUARDIAN_KEY`` was unset.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis import devchain
from aegis.api import ApiConfig
from aegis.approval import ApprovalConfig
from aegis.approval.config import guardian_key_from_env
from aegis.config import ConfigError, env_flag, validate_hex_key
from tests.helpers import DEV_GUARDIAN_KEY, dev_approval_config, fresh_key

PUBLIC_CHAIN = 84532  # base sepolia
FRESH_KEY = fresh_key()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AEGIS_GUARDIAN_KEY", "AEGIS_CHAIN_ID", "AEGIS_STATE_DIR", "AEGIS_DUAL_CONTROL"):
        monkeypatch.delenv(name, raising=False)


class TestGuardianKey:
    def test_guardian_key_is_required_by_the_model(self, tmp_path: Path) -> None:
        with pytest.raises(Exception) as excinfo:
            ApprovalConfig(db_path=str(tmp_path / "a.db"))  # type: ignore[call-arg]
        assert "guardian_key" in str(excinfo.value)

    def test_guardian_key_hex_shape(self, tmp_path: Path) -> None:
        with pytest.raises(Exception) as excinfo:
            dev_approval_config(tmp_path, guardian_key="not-a-key")
        assert "64 hex" in str(excinfo.value)

    def test_dev_guardian_key_allowed_on_dev_chain(self, tmp_path: Path) -> None:
        config = dev_approval_config(tmp_path, chain_id=31337)
        assert config.guardian_key == DEV_GUARDIAN_KEY

    def test_dev_guardian_key_refused_on_public_chain(self, tmp_path: Path) -> None:
        with pytest.raises(Exception) as excinfo:
            dev_approval_config(tmp_path, chain_id=PUBLIC_CHAIN)
        message = str(excinfo.value)
        assert "publicly known anvil dev key" in message
        assert str(PUBLIC_CHAIN) in message
        assert DEV_GUARDIAN_KEY not in message  # never echo a key

    def test_fresh_key_allowed_on_public_chain(self, tmp_path: Path) -> None:
        config = dev_approval_config(tmp_path, chain_id=PUBLIC_CHAIN, guardian_key=FRESH_KEY)
        assert config.chain_id == PUBLIC_CHAIN


class TestGuardianKeyFromEnv:
    def test_unset_on_public_chain_names_the_variable(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            guardian_key_from_env(PUBLIC_CHAIN)
        assert "AEGIS_GUARDIAN_KEY" in str(excinfo.value)

    def test_unset_on_dev_chain_substitutes_and_announces(self, capsys) -> None:
        assert guardian_key_from_env(31337) == DEV_GUARDIAN_KEY
        assert "anvil dev guardian key" in capsys.readouterr().err

    def test_explicit_dev_key_refused_on_public_chain(self, monkeypatch) -> None:
        monkeypatch.setenv("AEGIS_GUARDIAN_KEY", DEV_GUARDIAN_KEY)
        with pytest.raises(ConfigError) as excinfo:
            guardian_key_from_env(PUBLIC_CHAIN)
        assert "AEGIS_GUARDIAN_KEY" in str(excinfo.value)

    def test_malformed_value_names_the_variable(self, monkeypatch) -> None:
        monkeypatch.setenv("AEGIS_GUARDIAN_KEY", "0x1234")
        with pytest.raises(ConfigError) as excinfo:
            guardian_key_from_env(31337)
        assert "AEGIS_GUARDIAN_KEY" in str(excinfo.value)

    def test_explicit_fresh_key_is_used_without_notice(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("AEGIS_GUARDIAN_KEY", FRESH_KEY)
        assert guardian_key_from_env(PUBLIC_CHAIN) == FRESH_KEY
        assert capsys.readouterr().err == ""

    def test_approval_config_from_env_refuses_public_chain_without_key(self, monkeypatch) -> None:
        monkeypatch.setenv("AEGIS_CHAIN_ID", str(PUBLIC_CHAIN))
        with pytest.raises(ConfigError):
            ApprovalConfig.from_env()

    def test_api_config_from_env_uses_state_chain_id(self, monkeypatch, tmp_path: Path) -> None:
        # state.json says the deployment is on a public chain: no key means no start
        (tmp_path / "state.json").write_text(json.dumps({"chain_id": PUBLIC_CHAIN}))
        monkeypatch.setenv("AEGIS_STATE_DIR", str(tmp_path))
        with pytest.raises(ConfigError) as excinfo:
            ApiConfig.from_env()
        assert "AEGIS_GUARDIAN_KEY" in str(excinfo.value)

    def test_api_config_from_env_dev_chain_without_state(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("AEGIS_STATE_DIR", str(tmp_path))
        config = ApiConfig.from_env()
        assert config.approval.guardian_key == DEV_GUARDIAN_KEY
        assert config.approval.chain_id == 31337


class TestPrimitives:
    def test_validate_hex_key_accepts_and_trims(self) -> None:
        assert validate_hex_key(f"  {FRESH_KEY}  ", "X") == FRESH_KEY

    @pytest.mark.parametrize("bad", ["", "0x", FRESH_KEY[:-1], FRESH_KEY[2:], "0x" + "g" * 64])
    def test_validate_hex_key_rejects(self, bad: str) -> None:
        with pytest.raises(ConfigError) as excinfo:
            validate_hex_key(bad, "AEGIS_X")
        assert "AEGIS_X" in str(excinfo.value)

    def test_env_flag_strict(self, monkeypatch) -> None:
        monkeypatch.setenv("AEGIS_FLAG", "yes")
        assert env_flag("AEGIS_FLAG") is True
        monkeypatch.setenv("AEGIS_FLAG", "maybe")
        with pytest.raises(ConfigError):
            env_flag("AEGIS_FLAG")
        monkeypatch.delenv("AEGIS_FLAG")
        assert env_flag("AEGIS_FLAG", True) is True

    def test_devchain_resolve_key_public_chain_requires_explicit(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            devchain.resolve_key(None, role="operator", chain_id=PUBLIC_CHAIN, dev_key="0x00")
        assert "operator" in str(excinfo.value)
