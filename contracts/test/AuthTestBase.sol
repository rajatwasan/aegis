// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {GuardianModule} from "../src/GuardianModule.sol";
import {ComplianceRegistry} from "../src/ComplianceRegistry.sol";

/// @dev Shared fixture: guardian key, compliance registry, authorization builder/signer.
abstract contract AuthTestBase is Test {
    uint256 internal constant GUARDIAN_KEY = 0xA11CE;
    uint256 internal constant MALLORY_KEY = 0xBAD;

    address internal guardian;
    address internal admin = makeAddr("admin");
    address internal alice = makeAddr("alice");
    address internal bob = makeAddr("bob");
    address internal carol = makeAddr("carol");

    bytes32 internal constant POLICY_HASH = keccak256("policy-v1");

    ComplianceRegistry internal registry;

    uint256 private _decisionCounter;

    function setUp() public virtual {
        guardian = vm.addr(GUARDIAN_KEY);
        registry = new ComplianceRegistry(admin);
        vm.startPrank(admin);
        registry.setClaim(alice, registry.TOPIC_KYC(), true, 0);
        registry.setClaim(bob, registry.TOPIC_KYC(), true, 0);
        vm.stopPrank();
    }

    function freshDecisionId() internal returns (bytes32) {
        _decisionCounter++;
        return keccak256(abi.encode("decision", _decisionCounter));
    }

    function buildAuth(
        address token,
        uint8 operation,
        address from,
        address to,
        uint256 id,
        uint256 amount
    ) internal returns (GuardianModule.Authorization memory auth) {
        auth = GuardianModule.Authorization({
            decisionId: freshDecisionId(),
            operation: operation,
            token: token,
            from: from,
            to: to,
            id: id,
            amount: amount,
            policyHash: POLICY_HASH,
            nonce: _decisionCounter,
            deadline: block.timestamp + 1 hours
        });
    }

    function signAuth(GuardianModule module, GuardianModule.Authorization memory auth, uint256 key)
        internal
        view
        returns (bytes memory)
    {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, digestOf(module, auth));
        return abi.encodePacked(r, s, v);
    }

    function digestOf(GuardianModule module, GuardianModule.Authorization memory auth)
        internal
        view
        returns (bytes32)
    {
        // mirror of GuardianModule.hashAuthorization for memory structs
        bytes32 structHash = keccak256(
            abi.encode(
                module.AUTHORIZATION_TYPEHASH(),
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
        );
        (, string memory name, string memory version, uint256 chainId, address verifying,,) =
            module.eip712Domain();
        bytes32 domainSeparator = keccak256(
            abi.encode(
                keccak256(
                    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
                ),
                keccak256(bytes(name)),
                keccak256(bytes(version)),
                chainId,
                verifying
            )
        );
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator, structHash));
    }
}
