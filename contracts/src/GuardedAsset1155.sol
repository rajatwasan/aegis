// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {ERC1155} from "@openzeppelin/contracts/token/ERC1155/ERC1155.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {GuardianModule} from "./GuardianModule.sol";
import {ComplianceRegistry} from "./ComplianceRegistry.sol";

/// @title GuardedAsset1155
/// @notice Multi-class asset (ERC-1155, one token id per asset class) with the
///         same guardian gates as GuardedToken but a per-class threshold.
contract GuardedAsset1155 is ERC1155, GuardianModule {
    /// @notice Registry consulted for sender/recipient compliance.
    ComplianceRegistry public immutable registry;

    /// @notice Per-asset-class plain-transfer threshold. Unset (0) means every
    ///         transfer of that class requires authorization.
    mapping(uint256 id => uint256) public thresholdOf;

    /// @dev Set while an authorized operation executes, letting _update bypass gates.
    bool private _authorized;

    /// @notice Emitted when the admin changes a class threshold.
    event ClassThresholdSet(uint256 indexed id, uint256 previousThreshold, uint256 newThreshold);

    constructor(string memory uri_, address guardian_, address admin, ComplianceRegistry registry_)
        ERC1155(uri_)
        GuardianModule(guardian_, admin)
    {
        registry = registry_;
    }

    /// @notice Set the plain-transfer threshold for an asset class. Admin only.
    function setClassThreshold(uint256 id, uint256 newThreshold)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        emit ClassThresholdSet(id, thresholdOf[id], newThreshold);
        thresholdOf[id] = newThreshold;
    }

    /// @notice Execute a guardian-authorized single-class transfer.
    function transferWithAuthorization(Authorization calldata auth, bytes calldata signature)
        external
    {
        _consumeAuthorization(
            auth, signature, OP_TRANSFER, auth.from, auth.to, auth.id, auth.amount
        );
        _authorized = true;
        _safeTransferFrom(auth.from, auth.to, auth.id, auth.amount, "");
        _authorized = false;
    }

    /// @notice Mint via guardian authorization. from must be the zero address.
    function mintWithAuthorization(Authorization calldata auth, bytes calldata signature)
        external
    {
        _consumeAuthorization(auth, signature, OP_MINT, address(0), auth.to, auth.id, auth.amount);
        _authorized = true;
        _mint(auth.to, auth.id, auth.amount, "");
        _authorized = false;
    }

    /// @inheritdoc ERC1155
    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC1155, AccessControl)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }

    /// @dev Gate every movement per asset class; any gated id in a batch gates
    ///      the whole batch. Frozen blocks unconditionally.
    function _update(address from, address to, uint256[] memory ids, uint256[] memory values)
        internal
        override
    {
        _requireNotFrozen(from, to);
        if (!_authorized) {
            if (from == address(0) || to == address(0)) revert GuardianRequired();
            bool compliant = registry.isCompliant(from) && registry.isCompliant(to);
            for (uint256 i = 0; i < ids.length; i++) {
                if (values[i] > thresholdOf[ids[i]] || !compliant) revert GuardianRequired();
            }
        }
        super._update(from, to, ids, values);
    }
}
