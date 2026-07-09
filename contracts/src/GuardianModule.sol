// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

/// @title GuardianModule
/// @notice Shared EIP-712 authorization machinery for guardian-gated tokens.
///         A guardian key (held by the off-chain approval service) co-signs an
///         Authorization struct after a human approves the operation; consuming
///         that authorization is the only path through the gates. Each
///         decisionId is single-use, binding one on-chain execution to exactly
///         one audit-log record.
abstract contract GuardianModule is AccessControl, EIP712 {
    /// @notice Operation discriminators carried in Authorization.operation.
    uint8 public constant OP_TRANSFER = 1;
    uint8 public constant OP_MINT = 2;
    uint8 public constant OP_BURN = 3;
    uint8 public constant OP_FREEZE = 4;

    struct Authorization {
        bytes32 decisionId; // links on-chain execution to the audit record
        uint8 operation; // 1 TRANSFER, 2 MINT, 3 BURN, 4 FREEZE
        address token;
        address from;
        address to;
        uint256 id; // asset class; 0 for the ERC20 token
        uint256 amount;
        bytes32 policyHash; // sha256 of the exact policy file version
        uint256 nonce;
        uint256 deadline;
    }

    bytes32 public constant AUTHORIZATION_TYPEHASH = keccak256(
        "Authorization(bytes32 decisionId,uint8 operation,address token,address from,address to,uint256 id,uint256 amount,bytes32 policyHash,uint256 nonce,uint256 deadline)"
    );

    /// @notice Current guardian; the only key whose signatures are accepted.
    address public guardian;

    /// @notice Frozen addresses can neither send nor receive.
    mapping(address account => bool) public frozen;

    mapping(bytes32 decisionId => bool) private _consumed;

    /// @notice Emitted once per consumed authorization.
    event AuthorizationConsumed(
        bytes32 indexed decisionId,
        uint8 operation,
        address indexed from,
        address indexed to,
        uint256 id,
        uint256 amount
    );

    /// @notice Emitted when the guardian key is rotated.
    event GuardianRotated(address indexed previousGuardian, address indexed newGuardian);

    /// @notice Emitted when an account's frozen state changes.
    event FrozenSet(address indexed account, bool isFrozen);

    error GuardianRequired();
    error InvalidGuardianSignature();
    error AuthorizationExpired();
    error DecisionAlreadyConsumed(bytes32 decisionId);
    error FieldMismatch();
    error AddressFrozen(address account);
    error ZeroGuardian();

    constructor(address guardian_, address admin) EIP712("AegisGuardian", "1") {
        if (guardian_ == address(0)) revert ZeroGuardian();
        guardian = guardian_;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        emit GuardianRotated(address(0), guardian_);
    }

    /// @notice Rotate the guardian key. Admin only.
    function rotateGuardian(address newGuardian) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (newGuardian == address(0)) revert ZeroGuardian();
        emit GuardianRotated(guardian, newGuardian);
        guardian = newGuardian;
    }

    /// @notice Whether a decisionId has already been consumed.
    function isConsumed(bytes32 decisionId) external view returns (bool) {
        return _consumed[decisionId];
    }

    /// @notice EIP-712 digest for an authorization, for off-chain signers and tests.
    function hashAuthorization(Authorization calldata auth) public view returns (bytes32) {
        return _hashTypedDataV4(
            keccak256(
                abi.encode(
                    AUTHORIZATION_TYPEHASH,
                    auth.decisionId,
                    auth.operation,
                    auth.token,
                    auth.from,
                    auth.to,
                    auth.id,
                    auth.amount,
                    auth.policyHash,
                    auth.nonce,
                    auth.deadline
                )
            )
        );
    }

    /// @dev Validate and consume an authorization. Every struct field must match
    ///      the actual call parameters supplied by the concrete function; the
    ///      signer must be the current guardian; each decisionId is single-use.
    function _consumeAuthorization(
        Authorization calldata auth,
        bytes calldata signature,
        uint8 expectedOperation,
        address expectedFrom,
        address expectedTo,
        uint256 expectedId,
        uint256 expectedAmount
    ) internal {
        if (
            auth.token != address(this) || auth.operation != expectedOperation
                || auth.from != expectedFrom || auth.to != expectedTo || auth.id != expectedId
                || auth.amount != expectedAmount
        ) revert FieldMismatch();
        if (block.timestamp > auth.deadline) revert AuthorizationExpired();
        if (_consumed[auth.decisionId]) revert DecisionAlreadyConsumed(auth.decisionId);

        address signer = ECDSA.recover(hashAuthorization(auth), signature);
        if (signer != guardian) revert InvalidGuardianSignature();

        _consumed[auth.decisionId] = true;
        emit AuthorizationConsumed(
            auth.decisionId, auth.operation, auth.from, auth.to, auth.id, auth.amount
        );
    }

    /// @notice Freeze or unfreeze an account. Guardian authorization only:
    ///         operation FREEZE, from = the account, amount = 1 to freeze / 0 to
    ///         unfreeze, id = 0.
    function setFrozen(Authorization calldata auth, bytes calldata signature) external {
        _consumeAuthorization(
            auth, signature, OP_FREEZE, auth.from, address(0), 0, auth.amount == 0 ? 0 : 1
        );
        bool isFrozen = auth.amount != 0;
        frozen[auth.from] = isFrozen;
        emit FrozenSet(auth.from, isFrozen);
    }

    /// @dev Revert if either endpoint of a movement is frozen. Frozen status
    ///      blocks all movement, including guardian-authorized transfers; the
    ///      account must be unfrozen first.
    function _requireNotFrozen(address from, address to) internal view {
        if (frozen[from]) revert AddressFrozen(from);
        if (frozen[to]) revert AddressFrozen(to);
    }
}
