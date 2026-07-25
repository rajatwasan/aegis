"""Chain identity, explorer links, and RPC-url redaction."""

from __future__ import annotations

import pytest

from aegis import chains

TX = "0x" + "ab" * 32
ADDRESS = "0x1111111111111111111111111111111111111111"


class TestChainMeta:
    def test_known_public_chain(self) -> None:
        meta = chains.chain_meta(84532)
        assert meta.name == "base-sepolia"
        assert meta.explorer_url == "https://sepolia.basescan.org"
        assert meta.public is True

    def test_dev_chain_is_not_public_and_has_no_explorer(self) -> None:
        meta = chains.chain_meta(31337)
        assert (meta.name, meta.explorer_url, meta.public) == ("anvil", None, False)

    def test_unknown_chain_degrades(self) -> None:
        meta = chains.chain_meta(999_999)
        assert meta.name == "chain 999999"
        assert meta.explorer_url is None

    def test_missing_chain_id(self) -> None:
        assert chains.chain_meta(None).name == "unknown chain"

    def test_explicit_explorer_overrides_the_table(self) -> None:
        meta = chains.chain_meta(31337, "https://fork.example/")
        assert meta.explorer_url == "https://fork.example"  # trailing slash trimmed
        assert meta.public is True  # an explorer means someone can inspect it

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AEGIS_EXPLORER_URL", "https://env.example/")
        assert chains.explorer_from_env() == "https://env.example"
        monkeypatch.setenv("AEGIS_EXPLORER_URL", "  ")
        assert chains.explorer_from_env() is None


class TestLinks:
    def test_tx_url_on_public_chain(self) -> None:
        assert chains.tx_url(84532, TX) == f"https://sepolia.basescan.org/tx/{TX}"

    def test_tx_url_adds_missing_hex_prefix(self) -> None:
        assert chains.tx_url(84532, "ab" * 32) == f"https://sepolia.basescan.org/tx/{TX}"

    def test_no_explorer_means_no_link(self) -> None:
        assert chains.tx_url(31337, TX) is None
        assert chains.address_url(31337, ADDRESS) is None

    def test_missing_hash_means_no_link(self) -> None:
        assert chains.tx_url(84532, None) is None
        assert chains.address_url(84532, None) is None

    def test_address_url(self) -> None:
        assert chains.address_url(84532, ADDRESS) == (
            f"https://sepolia.basescan.org/address/{ADDRESS}"
        )

    @pytest.mark.parametrize("value", [None, "", "  "])
    def test_hex0x_of_empty(self, value: str | None) -> None:
        assert chains.hex0x(value) is None

    def test_hex0x_of_bytes(self) -> None:
        assert chains.hex0x(b"\xab" * 32) == TX


class TestRedactRpcUrl:
    def test_loopback_survives_intact(self) -> None:
        assert chains.redact_rpc_url("http://127.0.0.1:8545") == "http://127.0.0.1:8545"

    def test_public_rpc_without_path_survives(self) -> None:
        assert chains.redact_rpc_url("https://sepolia.base.org") == "https://sepolia.base.org"

    def test_provider_key_in_path_is_stripped(self) -> None:
        redacted = chains.redact_rpc_url("https://base-sepolia.g.alchemy.com/v2/SECRETKEY")
        assert "SECRETKEY" not in redacted
        assert redacted == "https://base-sepolia.g.alchemy.com/…"

    def test_key_in_query_is_stripped(self) -> None:
        redacted = chains.redact_rpc_url("https://rpc.example?apikey=SECRETKEY")
        assert "SECRETKEY" not in redacted

    def test_none(self) -> None:
        assert chains.redact_rpc_url(None) is None
