// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {GuardianModule} from "./GuardianModule.sol";
import {ComplianceRegistry} from "./ComplianceRegistry.sol";

/// @title GuardedToken
/// @notice ERC20 whose risky movements require a guardian-signed EIP-712
///         authorization. Plain transfers succeed only when the amount is at or
///         below the threshold AND both parties are compliant; everything else
///         reverts with GuardianRequired() and must go through
///         transferWithAuthorization. Minting is authorization-only.
contract GuardedToken is ERC20, GuardianModule {
    /// @notice Registry consulted for sender/recipient compliance.
    ComplianceRegistry public immutable registry;

    /// @notice Plain transfers above this amount require guardian authorization.
    uint256 public threshold;

    /// @dev Set while an authorized operation executes, letting _update bypass gates.
    bool private _authorized;

    /// @notice Emitted when the admin changes the gating threshold.
    event ThresholdSet(uint256 previousThreshold, uint256 newThreshold);

    constructor(
        string memory name_,
        string memory symbol_,
        address guardian_,
        address admin,
        ComplianceRegistry registry_,
        uint256 threshold_
    ) ERC20(name_, symbol_) GuardianModule(guardian_, admin) {
        registry = registry_;
        threshold = threshold_;
        emit ThresholdSet(0, threshold_);
    }

    /// @notice Change the plain-transfer threshold. Admin only.
    function setThreshold(uint256 newThreshold) external onlyRole(DEFAULT_ADMIN_ROLE) {
        emit ThresholdSet(threshold, newThreshold);
        threshold = newThreshold;
    }

    /// @notice Execute a guardian-authorized transfer. The authorization's
    ///         from/to/amount are the transfer parameters; id must be 0.
    function transferWithAuthorization(Authorization calldata auth, bytes calldata signature)
        external
    {
        _consumeAuthorization(auth, signature, OP_TRANSFER, auth.from, auth.to, 0, auth.amount);
        _authorized = true;
        _transfer(auth.from, auth.to, auth.amount);
        _authorized = false;
    }

    /// @notice Mint via guardian authorization. from must be the zero address.
    function mintWithAuthorization(Authorization calldata auth, bytes calldata signature)
        external
    {
        _consumeAuthorization(auth, signature, OP_MINT, address(0), auth.to, 0, auth.amount);
        _authorized = true;
        _mint(auth.to, auth.amount);
        _authorized = false;
    }

    /// @notice Burn via guardian authorization. to must be the zero address.
    function burnWithAuthorization(Authorization calldata auth, bytes calldata signature)
        external
    {
        _consumeAuthorization(auth, signature, OP_BURN, auth.from, address(0), 0, auth.amount);
        _authorized = true;
        _burn(auth.from, auth.amount);
        _authorized = false;
    }

    /// @dev Gate every movement. Frozen blocks unconditionally; ungated plain
    ///      transfers must be small and between compliant parties.
    function _update(address from, address to, uint256 value) internal override {
        _requireNotFrozen(from, to);
        if (!_authorized) {
            if (from == address(0) || to == address(0)) revert GuardianRequired();
            if (value > threshold) revert GuardianRequired();
            if (!registry.isCompliant(from) || !registry.isCompliant(to)) {
                revert GuardianRequired();
            }
        }
        super._update(from, to, value);
    }
}
