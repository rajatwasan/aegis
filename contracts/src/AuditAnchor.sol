// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title AuditAnchor
/// @notice Stores Merkle roots of off-chain audit-log batches so any single
///         decision record can later be proven included.
contract AuditAnchor is AccessControl {
    /// @notice Role allowed to anchor batch roots.
    bytes32 public constant ANCHOR_ROLE = keccak256("ANCHOR_ROLE");

    /// @notice Merkle root per batch id; zero means not anchored.
    mapping(uint256 batchId => bytes32) public rootOf;

    /// @notice Emitted once per anchored batch.
    event Anchored(uint256 indexed batchId, bytes32 root);

    error BatchAlreadyAnchored(uint256 batchId);
    error ZeroRoot();

    constructor(address admin) {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ANCHOR_ROLE, admin);
    }

    /// @notice Anchor the Merkle root of an audit batch.
    function anchor(bytes32 root, uint256 batchId) external onlyRole(ANCHOR_ROLE) {
        if (root == bytes32(0)) revert ZeroRoot();
        if (rootOf[batchId] != bytes32(0)) revert BatchAlreadyAnchored(batchId);
        rootOf[batchId] = root;
        emit Anchored(batchId, root);
    }
}
