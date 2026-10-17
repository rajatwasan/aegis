"""M7 MCP server smoke test: drive the runtime over a real stdio MCP session.

Launches ``python -m aegis.mcpserver`` as a subprocess pointed at the deployed
contracts, then speaks the MCP protocol over stdio: lists the four tools, runs a
small compliant transfer (auto-executed), a large one (escalated to a human),
checks the pending queue and status, and verifies a Merkle audit proof.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from aegis.audit import MerkleTree
from tests.conftest import ACCOUNTS, CHAIN_ID, KEYS, OPERATOR, REPO_ROOT

POLICY_PATH = REPO_ROOT / "policies" / "dev.yaml"


def _server_params(deployment, workdir: Path) -> StdioServerParameters:
    env = {
        **os.environ,
        "AEGIS_RPC_URL": deployment["rpc_url"],
        "AEGIS_OPERATOR_KEY": KEYS[0],
        "AEGIS_GUARDIAN_KEY": KEYS[9],
        "AEGIS_CHAIN_ID": str(CHAIN_ID),
        "AEGIS_TOKEN_ADDRESS": deployment["token"].address,
        "AEGIS_REGISTRY_ADDRESS": deployment["registry"].address,
        "AEGIS_POLICY_PATH": str(POLICY_PATH),
        "AEGIS_STATE_DIR": str(workdir),
        "AEGIS_DB_PATH": str(workdir / "approvals.db"),
        "AEGIS_AUDIT_LOG_PATH": str(workdir / "audit.jsonl"),
        "AEGIS_AUDIT_KEY_FILE": str(workdir / "audit.key"),
    }
    return StdioServerParameters(command=sys.executable, args=["-m", "aegis.mcpserver"], env=env)


def _tool_json(result) -> dict:
    assert result.content, "tool returned no content"
    return json.loads(result.content[0].text)


async def _drive(params: StdioServerParameters, token_addr: str) -> dict:
    async with (
        stdio_client(params) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        listed = await session.list_tools()
        tool_names = {t.name for t in listed.tools}

        allow = _tool_json(
            await session.call_tool(
                "propose_transfer",
                {
                    "token": token_addr,
                    "from_addr": OPERATOR,
                    "to": ACCOUNTS[1],
                    "amount": 1_000,
                },
            )
        )
        escalate = _tool_json(
            await session.call_tool(
                "propose_transfer",
                {
                    "token": token_addr,
                    "from_addr": OPERATOR,
                    "to": ACCOUNTS[1],
                    "amount": 50_000,
                },
            )
        )
        pending = _tool_json(await session.call_tool("list_pending", {}))
        status = _tool_json(
            await session.call_tool("get_proposal_status", {"decision_id": escalate["decision_id"]})
        )
        proof = _tool_json(
            await session.call_tool(
                "get_audit_proof", {"decision_id": escalate["audit_decision_id"]}
            )
        )
        return {
            "tool_names": tool_names,
            "allow": allow,
            "escalate": escalate,
            "pending": pending,
            "status": status,
            "proof": proof,
        }


def test_mcp_stdio_smoke(deployment, tmp_path: Path) -> None:
    params = _server_params(deployment, tmp_path)
    out = anyio.run(_drive, params, deployment["token"].address)

    assert out["tool_names"] == {
        "propose_transfer",
        "get_proposal_status",
        "list_pending",
        "get_audit_proof",
    }

    # small compliant transfer to an allowlisted address auto-executes on-chain
    assert out["allow"]["status"] == "executed"
    assert out["allow"]["effect"] == "allow"

    # large transfer is gated: escalated to a human, never executed
    assert out["escalate"]["status"] == "pending_approval"
    assert out["escalate"]["effect"] == "escalate"
    decision_id = out["escalate"]["decision_id"]

    # it shows up in the pending queue and reports pending status, unsigned
    assert out["pending"]["count"] >= 1
    assert decision_id in {p["decision_id"] for p in out["pending"]["pending"]}
    assert out["status"]["found"] and out["status"]["status"] == "pending"
    assert out["status"]["has_signature"] is False

    # the audit proof verifies against its Merkle root
    proof = out["proof"]
    assert proof["found"]
    leaf = bytes.fromhex(proof["leaf"])
    siblings = [bytes.fromhex(s) for s in proof["proof"]]
    root = bytes.fromhex(proof["root"])
    assert MerkleTree.verify(leaf, siblings, root)
