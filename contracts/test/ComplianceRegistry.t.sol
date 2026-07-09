// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {ComplianceRegistry} from "../src/ComplianceRegistry.sol";

contract ComplianceRegistryTest is Test {
    ComplianceRegistry internal registry;
    address internal admin = makeAddr("admin");
    address internal user = makeAddr("user");
    bytes32 internal constant TOPIC = keccak256("aegis.accredited");

    function setUp() public {
        registry = new ComplianceRegistry(admin);
    }

    function test_SetAndGetClaim() public {
        vm.prank(admin);
        vm.expectEmit(true, true, false, true);
        emit ComplianceRegistry.ClaimSet(user, TOPIC, true, 0);
        registry.setClaim(user, TOPIC, true, 0);
        assertTrue(registry.getClaim(user, TOPIC));
    }

    function test_UnsetClaimIsFalse() public view {
        assertFalse(registry.getClaim(user, TOPIC));
        assertFalse(registry.isCompliant(user));
    }

    function test_ClaimExpiry() public {
        vm.prank(admin);
        registry.setClaim(user, TOPIC, true, uint64(block.timestamp + 100));
        assertTrue(registry.getClaim(user, TOPIC));
        vm.warp(block.timestamp + 101);
        assertFalse(registry.getClaim(user, TOPIC));
    }

    function test_ClaimRevocation() public {
        vm.startPrank(admin);
        registry.setClaim(user, TOPIC, true, 0);
        registry.setClaim(user, TOPIC, false, 0);
        vm.stopPrank();
        assertFalse(registry.getClaim(user, TOPIC));
    }

    function test_IsCompliantUsesKycTopic() public {
        bytes32 kycTopic = registry.TOPIC_KYC();
        vm.prank(admin);
        registry.setClaim(user, kycTopic, true, 0);
        assertTrue(registry.isCompliant(user));
    }

    function test_RevertSetClaim_NotRegistrar() public {
        vm.prank(user);
        vm.expectRevert();
        registry.setClaim(user, TOPIC, true, 0);
    }

    function testFuzz_ExpiryBoundary(uint64 expiry, uint64 nowTs) public {
        expiry = uint64(bound(expiry, 1, type(uint64).max));
        nowTs = uint64(bound(nowTs, 1, type(uint64).max));
        vm.prank(admin);
        registry.setClaim(user, TOPIC, true, expiry);
        vm.warp(nowTs);
        assertEq(registry.getClaim(user, TOPIC), expiry >= nowTs);
    }
}
