"""Stdio MCP server exposing the Aegis runtime to any MCP client.

The server drives proposals through the exact same policy gate, approval
service, and audit log as the LangGraph agent, so an MCP client gets no path
around the guardian: gated moves still escalate to a human and still need an
on-chain guardian signature.
"""

from aegis.mcpserver.backend import AegisBackend, build_backend_from_env
from aegis.mcpserver.server import TOOLS, build_server, main

__all__ = ["TOOLS", "AegisBackend", "build_backend_from_env", "build_server", "main"]
