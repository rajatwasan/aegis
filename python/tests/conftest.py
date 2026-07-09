"""Shared fixtures: local anvil chain, deployed contracts, approval service."""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path

import pytest
from web3 import Web3

from aegis.agent.chain import ChainClient
from aegis.approval.signer import GuardianSigner, build_authorization

REPO_ROOT = Path(__file__).resolve().parents[2]

# anvil's default dev mnemonic accounts (test-only, publicly known)
ACCOUNTS = {
    0: "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    1: "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    2: "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    3: "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
    4: "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
    9: "0xa0Ee7A142d267C1f36714E4a8F75612F20a79720",
}
KEYS = {
    0: "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    9: "0x2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6",
}
OPERATOR = ACCOUNTS[0]
GUARDIAN = ACCOUNTS[9]
FROZEN_ACCOUNT = ACCOUNTS[4]
THRESHOLD = 10_000
CHAIN_ID = 31337


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def anvil_url():
    """Spawn anvil for the whole session; always terminated in teardown."""
    port = _free_port()
    proc = subprocess.Popen(
        ["anvil", "--port", str(port), "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        w3 = Web3(Web3.HTTPProvider(url))
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                if w3.is_connected() and w3.eth.chain_id == CHAIN_ID:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("anvil did not come up in 15s")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def deployment(anvil_url):
    """Deploy the contract suite and prepare accounts.

    Accounts 0-3 are KYC-compliant; account 4 is frozen and non-compliant.
    The operator (account 0) starts with 1,000,000 tokens.
    """
    chain = ChainClient(anvil_url, KEYS[0])
    registry = chain.deploy("ComplianceRegistry", OPERATOR)
    token = chain.deploy(
        "GuardedToken", "Aegis Guarded", "AGD", GUARDIAN, OPERATOR, registry.address, THRESHOLD
    )
    anchor = chain.deploy("AuditAnchor", OPERATOR)

    kyc_topic = registry.functions.TOPIC_KYC().call()
    for i in range(4):
        chain.call_tx(registry.functions.setClaim(ACCOUNTS[i], kyc_topic, True, 0))

    signer = GuardianSigner(KEYS[9], CHAIN_ID)
    now = int(time.time())

    mint_auth = build_authorization(
        decision_id="fixture-mint-operator",
        operation=2,
        token=token.address,
        from_addr="0x" + "0" * 40,
        to=OPERATOR,
        asset_class=0,
        amount=1_000_000,
        policy_hash="00" * 32,
        nonce=0,
        deadline=now + 3600,
    )
    chain.mint_with_authorization(token, mint_auth, signer.sign_authorization(mint_auth))

    freeze_auth = build_authorization(
        decision_id="fixture-freeze-account4",
        operation=4,
        token=token.address,
        from_addr=FROZEN_ACCOUNT,
        to="0x" + "0" * 40,
        asset_class=0,
        amount=1,
        policy_hash="00" * 32,
        nonce=0,
        deadline=now + 3600,
    )
    chain.set_frozen(token, freeze_auth, signer.sign_authorization(freeze_auth))

    return {
        "chain": chain,
        "registry": registry,
        "token": token,
        "anchor": anchor,
        "rpc_url": anvil_url,
    }
