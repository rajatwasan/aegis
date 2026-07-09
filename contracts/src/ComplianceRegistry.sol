// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title ComplianceRegistry
/// @notice Boolean claims with expiry, per address per bytes32 topic.
///         Registrars attest facts ("kyc passed", "accredited") off-chain and
///         record them here; token contracts consult the registry at transfer time.
contract ComplianceRegistry is AccessControl {
    /// @notice Role allowed to set and revoke claims.
    bytes32 public constant REGISTRAR_ROLE = keccak256("REGISTRAR_ROLE");

    /// @notice Canonical topic consulted by `isCompliant`.
    bytes32 public constant TOPIC_KYC = keccak256("aegis.kyc");

    struct Claim {
        bool value;
        uint64 expiry; // unix seconds; 0 means never expires
    }

    mapping(address subject => mapping(bytes32 topic => Claim)) private _claims;

    /// @notice Emitted whenever a claim is written.
    event ClaimSet(address indexed subject, bytes32 indexed topic, bool value, uint64 expiry);

    constructor(address admin) {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(REGISTRAR_ROLE, admin);
    }

    /// @notice Set a boolean claim for `subject` under `topic`.
    /// @param subject The address the claim is about.
    /// @param topic Arbitrary claim namespace, e.g. keccak256("aegis.kyc").
    /// @param value The boolean claim value.
    /// @param expiry Unix timestamp after which the claim is void; 0 = no expiry.
    function setClaim(address subject, bytes32 topic, bool value, uint64 expiry)
        external
        onlyRole(REGISTRAR_ROLE)
    {
        _claims[subject][topic] = Claim({value: value, expiry: expiry});
        emit ClaimSet(subject, topic, value, expiry);
    }

    /// @notice Read a claim, honoring expiry.
    /// @return True only if the claim is set true and not expired.
    function getClaim(address subject, bytes32 topic) public view returns (bool) {
        Claim memory c = _claims[subject][topic];
        if (!c.value) return false;
        if (c.expiry != 0 && c.expiry < block.timestamp) return false;
        return true;
    }

    /// @notice Convenience: whether `subject` holds a valid KYC claim.
    function isCompliant(address subject) external view returns (bool) {
        return getClaim(subject, TOPIC_KYC);
    }
}
