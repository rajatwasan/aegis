"""FastAPI HITL approval service with guardian EIP-712 signer."""

from aegis.approval.app import create_app
from aegis.approval.config import ApprovalConfig
from aegis.approval.signer import (
    GuardianSigner,
    authorization_from_json,
    authorization_to_json,
    build_authorization,
    decision_id_to_bytes32,
)
from aegis.approval.store import ProposalStore

__all__ = [
    "ApprovalConfig",
    "GuardianSigner",
    "ProposalStore",
    "authorization_from_json",
    "authorization_to_json",
    "build_authorization",
    "create_app",
    "decision_id_to_bytes32",
]
