"""Stdio MCP server: four tools that drive the Aegis runtime through the gate.

Tools:
  propose_transfer      — submit a transfer; the policy gate allows, escalates,
                          or denies it (a gated move never auto-executes)
  get_proposal_status   — status of an escalated proposal awaiting a human
  list_pending          — proposals currently awaiting human approval
  get_audit_proof       — Merkle inclusion proof for an audit record

Run as ``python -m aegis.mcpserver`` with the AEGIS_* environment configured
(see :func:`aegis.mcpserver.backend.build_backend_from_env`).
"""

from __future__ import annotations

import json
from typing import Any

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from aegis.mcpserver.backend import AegisBackend, build_backend_from_env

TOOLS: list[types.Tool] = [
    types.Tool(
        name="propose_transfer",
        description=(
            "Propose an ERC20 transfer. Runs through the deterministic policy "
            "gate: small compliant transfers to known destinations execute; "
            "large or unknown ones escalate to a human; frozen parties are denied."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "token": {"type": "string", "description": "GuardedToken address"},
                "from_addr": {"type": "string", "description": "sender address"},
                "to": {"type": "string", "description": "recipient address"},
                "amount": {"type": "integer", "minimum": 0},
                "asset_class": {"type": "integer", "default": 0},
            },
            "required": ["token", "from_addr", "to", "amount"],
        },
    ),
    types.Tool(
        name="get_proposal_status",
        description="Status of an escalated proposal by its decision id.",
        inputSchema={
            "type": "object",
            "properties": {"decision_id": {"type": "string"}},
            "required": ["decision_id"],
        },
    ),
    types.Tool(
        name="list_pending",
        description="List proposals currently awaiting human approval.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="get_audit_proof",
        description="Merkle inclusion proof for the audit record with this decision id.",
        inputSchema={
            "type": "object",
            "properties": {"decision_id": {"type": "string"}},
            "required": ["decision_id"],
        },
    ),
]


def _dispatch(backend: AegisBackend, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "propose_transfer":
        return backend.propose_transfer(
            token=args["token"],
            from_addr=args["from_addr"],
            to=args["to"],
            amount=int(args["amount"]),
            asset_class=int(args.get("asset_class", 0)),
        )
    if name == "get_proposal_status":
        return backend.get_proposal_status(decision_id=args["decision_id"])
    if name == "list_pending":
        return backend.list_pending()
    if name == "get_audit_proof":
        return backend.get_audit_proof(decision_id=args["decision_id"])
    raise ValueError(f"unknown tool: {name!r}")


def build_server(backend: AegisBackend) -> Server:
    server: Server = Server("aegis")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        result = _dispatch(backend, name, arguments or {})
        return [types.TextContent(type="text", text=json.dumps(result))]

    return server


async def _serve(server: Server) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    backend = build_backend_from_env()
    server = build_server(backend)
    anyio.run(_serve, server)


if __name__ == "__main__":
    main()
