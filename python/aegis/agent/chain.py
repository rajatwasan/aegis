"""web3.py client for the Aegis contracts plus forge-artifact deployment."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from eth_account import Account
from web3 import Web3

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "contracts"


def load_artifact(name: str) -> dict[str, Any]:
    """Read a forge build artifact (abi + creation bytecode), building if absent."""
    artifact_path = CONTRACTS_DIR / "out" / f"{name}.sol" / f"{name}.json"
    if not artifact_path.exists():
        subprocess.run(["forge", "build"], cwd=CONTRACTS_DIR, check=True, capture_output=True)
    data = json.loads(artifact_path.read_text())
    return {"abi": data["abi"], "bytecode": data["bytecode"]["object"]}


class ChainClient:
    """Signs and sends transactions as one operator account."""

    def __init__(self, rpc_url: str, operator_key: str) -> None:
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.operator = Account.from_key(operator_key)

    @property
    def operator_address(self) -> str:
        return self.operator.address

    def _send(self, tx: dict[str, Any]) -> Any:
        tx.setdefault("from", self.operator.address)
        tx.setdefault("nonce", self.w3.eth.get_transaction_count(self.operator.address))
        tx.setdefault("gas", 3_000_000)
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:
            tx["maxFeePerGas"] = self.w3.eth.gas_price * 2
            tx["maxPriorityFeePerGas"] = 0
        tx.setdefault("chainId", self.w3.eth.chain_id)
        signed = self.operator.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        if receipt["status"] != 1:
            raise RuntimeError(f"transaction reverted: {tx_hash.hex()}")
        return receipt

    def _build_params(self) -> dict[str, Any]:
        # explicit from + gas so build_transaction never gas-estimates as 0x0
        return {"from": self.operator.address, "gas": 3_000_000}

    def deploy(self, name: str, *args: Any) -> Any:
        artifact = load_artifact(name)
        contract = self.w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        receipt = self._send(contract.constructor(*args).build_transaction(self._build_params()))
        return self.w3.eth.contract(address=receipt["contractAddress"], abi=artifact["abi"])

    def at(self, name: str, address: str) -> Any:
        return self.w3.eth.contract(
            address=Web3.to_checksum_address(address), abi=load_artifact(name)["abi"]
        )

    def call_tx(self, contract_fn: Any) -> Any:
        """Send a state-changing contract call as the operator."""
        return self._send(contract_fn.build_transaction(self._build_params()))

    # ------------------------------------------------------------ conveniences

    def transfer(self, token: Any, to: str, amount: int) -> Any:
        """Plain ERC20 transfer from the operator's own balance."""
        return self.call_tx(token.functions.transfer(Web3.to_checksum_address(to), amount))

    def transfer_with_authorization(self, token: Any, auth: dict[str, Any], sig: str) -> Any:
        return self.call_tx(
            token.functions.transferWithAuthorization(_auth_tuple(auth), _hexbytes(sig))
        )

    def mint_with_authorization(self, token: Any, auth: dict[str, Any], sig: str) -> Any:
        return self.call_tx(
            token.functions.mintWithAuthorization(_auth_tuple(auth), _hexbytes(sig))
        )

    def set_frozen(self, token: Any, auth: dict[str, Any], sig: str) -> Any:
        return self.call_tx(token.functions.setFrozen(_auth_tuple(auth), _hexbytes(sig)))


def _hexbytes(value: str | bytes) -> bytes:
    return bytes.fromhex(value.removeprefix("0x")) if isinstance(value, str) else value


def _auth_tuple(auth: dict[str, Any]) -> tuple:
    """Order the Authorization dict exactly as the Solidity struct."""
    return (
        _hexbytes(auth["decisionId"]),
        auth["operation"],
        Web3.to_checksum_address(auth["token"]),
        Web3.to_checksum_address(auth["from"]),
        Web3.to_checksum_address(auth["to"]),
        auth["id"],
        auth["amount"],
        _hexbytes(auth["policyHash"]),
        auth["nonce"],
        auth["deadline"],
    )
