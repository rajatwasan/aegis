"""Typed tool registry: pydantic schemas for every action the LLM may pick."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ProposeTransferArgs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    token: str
    from_addr: str = Field(alias="from")
    to: str
    amount: int = Field(ge=0)
    asset_class: int = 0


class ProposeMintArgs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    token: str
    to: str
    amount: int = Field(ge=0)
    asset_class: int = 0


class CheckComplianceArgs(BaseModel):
    address: str


class GetBalanceArgs(BaseModel):
    token: str
    address: str


TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "propose_transfer": ProposeTransferArgs,
    "propose_mint": ProposeMintArgs,
    "check_compliance": CheckComplianceArgs,
    "get_balance": GetBalanceArgs,
}


class UnknownToolError(Exception):
    pass


def validate_action(action: dict[str, Any]) -> tuple[str, BaseModel] | tuple[str, None]:
    """Validate an LLM-chosen action against the registry.

    Returns (tool_name, parsed_args). 'done' carries no args. Unknown tools and
    schema violations raise — the agent refuses malformed actions outright.
    """
    tool = action.get("tool")
    if tool == "done":
        return "done", None
    if tool == "malformed":  # a model reply the provider could not read
        reason = (action.get("args") or {}).get("reason", "unreadable model reply")
        raise UnknownToolError(f"malformed model reply: {reason}")
    if not isinstance(tool, str) or tool not in TOOL_SCHEMAS:
        raise UnknownToolError(f"unknown tool: {tool!r}")
    try:
        args = TOOL_SCHEMAS[tool].model_validate(action.get("args", {}))
    except ValidationError as exc:
        raise UnknownToolError(f"invalid args for {tool}: {exc}") from exc
    return tool, args
