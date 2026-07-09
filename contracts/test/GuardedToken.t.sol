// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {AuthTestBase} from "./AuthTestBase.sol";
import {GuardianModule} from "../src/GuardianModule.sol";
import {GuardedToken} from "../src/GuardedToken.sol";

contract GuardedTokenTest is AuthTestBase {
    GuardedToken internal token;
    uint256 internal constant THRESHOLD = 10_000;

    function setUp() public override {
        super.setUp();
        token = new GuardedToken("Aegis Guarded", "AGD", guardian, admin, registry, THRESHOLD);
        _mintTo(alice, 1_000_000);
    }

    function _mintTo(address to, uint256 amount) internal {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_MINT(), address(0), to, 0, amount);
        token.mintWithAuthorization(_calldataAuth(auth), signAuth(token, auth, GUARDIAN_KEY));
    }

    /// @dev Round-trip a memory struct so external functions get calldata.
    function _calldataAuth(GuardianModule.Authorization memory auth)
        internal
        pure
        returns (GuardianModule.Authorization memory)
    {
        return auth;
    }

    // ------------------------------------------------------------------ happy

    function test_PlainTransfer_BelowThreshold_Compliant() public {
        vm.prank(alice);
        token.transfer(bob, 5_000);
        assertEq(token.balanceOf(bob), 5_000);
    }

    function test_PlainTransfer_AtThreshold() public {
        vm.prank(alice);
        token.transfer(bob, THRESHOLD);
        assertEq(token.balanceOf(bob), THRESHOLD);
    }

    function test_AuthorizedTransfer_AboveThreshold() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, bob, 0, 50_000);
        bytes memory sig = signAuth(token, auth, GUARDIAN_KEY);

        vm.expectEmit(true, true, true, true);
        emit GuardianModule.AuthorizationConsumed(auth.decisionId, 1, alice, bob, 0, 50_000);
        token.transferWithAuthorization(auth, sig);
        assertEq(token.balanceOf(bob), 50_000);
        assertTrue(token.isConsumed(auth.decisionId));
    }

    function test_AuthorizedTransfer_NonCompliantRecipient() public {
        // carol has no KYC claim; guardian authorization overrides the gate
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, carol, 0, 10);
        token.transferWithAuthorization(auth, signAuth(token, auth, GUARDIAN_KEY));
        assertEq(token.balanceOf(carol), 10);
    }

    function test_MintWithAuthorization() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_MINT(), address(0), bob, 0, 777);
        token.mintWithAuthorization(auth, signAuth(token, auth, GUARDIAN_KEY));
        assertEq(token.balanceOf(bob), 777);
    }

    function test_BurnWithAuthorization() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_BURN(), alice, address(0), 0, 1_000);
        token.burnWithAuthorization(auth, signAuth(token, auth, GUARDIAN_KEY));
        assertEq(token.balanceOf(alice), 999_000);
    }

    function test_FreezeAndUnfreeze() public {
        GuardianModule.Authorization memory freezeAuth =
            buildAuth(address(token), token.OP_FREEZE(), bob, address(0), 0, 1);
        token.setFrozen(freezeAuth, signAuth(token, freezeAuth, GUARDIAN_KEY));
        assertTrue(token.frozen(bob));

        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(GuardianModule.AddressFrozen.selector, bob));
        token.transfer(bob, 1);

        GuardianModule.Authorization memory unfreezeAuth =
            buildAuth(address(token), token.OP_FREEZE(), bob, address(0), 0, 0);
        token.setFrozen(unfreezeAuth, signAuth(token, unfreezeAuth, GUARDIAN_KEY));
        assertFalse(token.frozen(bob));

        vm.prank(alice);
        token.transfer(bob, 1);
        assertEq(token.balanceOf(bob), 1);
    }

    function test_GuardianRotation() public {
        uint256 newKey = 0xC0FFEE;
        address newGuardian = vm.addr(newKey);
        vm.prank(admin);
        token.rotateGuardian(newGuardian);

        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, bob, 0, 50_000);
        // old key no longer accepted
        bytes memory oldSig = signAuth(token, auth, GUARDIAN_KEY);
        vm.expectRevert(GuardianModule.InvalidGuardianSignature.selector);
        token.transferWithAuthorization(auth, oldSig);
        // new key accepted
        token.transferWithAuthorization(auth, signAuth(token, auth, newKey));
        assertEq(token.balanceOf(bob), 50_000);
    }

    // ---------------------------------------------------------------- reverts

    function test_RevertPlainTransfer_AboveThreshold() public {
        vm.prank(alice);
        vm.expectRevert(GuardianModule.GuardianRequired.selector);
        token.transfer(bob, THRESHOLD + 1);
    }

    function test_RevertPlainTransfer_NonCompliantRecipient() public {
        vm.prank(alice);
        vm.expectRevert(GuardianModule.GuardianRequired.selector);
        token.transfer(carol, 1);
    }

    function test_RevertPlainTransfer_NonCompliantSender() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, carol, 0, 100);
        token.transferWithAuthorization(auth, signAuth(token, auth, GUARDIAN_KEY));

        vm.prank(carol);
        vm.expectRevert(GuardianModule.GuardianRequired.selector);
        token.transfer(alice, 1);
    }

    function test_RevertPlainTransfer_ExpiredCompliance() public {
        vm.startPrank(admin);
        registry.setClaim(bob, registry.TOPIC_KYC(), true, uint64(block.timestamp + 1));
        vm.stopPrank();
        vm.warp(block.timestamp + 2);

        vm.prank(alice);
        vm.expectRevert(GuardianModule.GuardianRequired.selector);
        token.transfer(bob, 1);
    }

    function test_RevertWrongSigner() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, bob, 0, 50_000);
        bytes memory sig = signAuth(token, auth, MALLORY_KEY);
        vm.expectRevert(GuardianModule.InvalidGuardianSignature.selector);
        token.transferWithAuthorization(auth, sig);
    }

    function test_RevertExpiredDeadline() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, bob, 0, 50_000);
        bytes memory sig = signAuth(token, auth, GUARDIAN_KEY);
        vm.warp(auth.deadline + 1);
        vm.expectRevert(GuardianModule.AuthorizationExpired.selector);
        token.transferWithAuthorization(auth, sig);
    }

    function test_RevertReplayedDecisionId() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, bob, 0, 50_000);
        bytes memory sig = signAuth(token, auth, GUARDIAN_KEY);
        token.transferWithAuthorization(auth, sig);
        vm.expectRevert(
            abi.encodeWithSelector(GuardianModule.DecisionAlreadyConsumed.selector, auth.decisionId)
        );
        token.transferWithAuthorization(auth, sig);
    }

    function test_RevertFieldMismatch_TamperedAmount() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, bob, 0, 50_000);
        bytes memory sig = signAuth(token, auth, GUARDIAN_KEY);
        auth.amount = 60_000; // signature no longer matches the struct
        vm.expectRevert(GuardianModule.InvalidGuardianSignature.selector);
        token.transferWithAuthorization(auth, sig);
    }

    function test_RevertFieldMismatch_WrongToken() public {
        GuardedToken other = new GuardedToken("Other", "OTH", guardian, admin, registry, THRESHOLD);
        GuardianModule.Authorization memory auth =
            buildAuth(address(other), token.OP_TRANSFER(), alice, bob, 0, 50_000);
        bytes memory sig = signAuth(token, auth, GUARDIAN_KEY);
        vm.expectRevert(GuardianModule.FieldMismatch.selector);
        token.transferWithAuthorization(auth, sig);
    }

    function test_RevertFieldMismatch_WrongOperation() public {
        // guardian signed a MINT; struct cannot be consumed through transfer
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_MINT(), address(0), bob, 0, 50_000);
        bytes memory sig = signAuth(token, auth, GUARDIAN_KEY);
        vm.expectRevert(GuardianModule.FieldMismatch.selector);
        token.transferWithAuthorization(auth, sig);
    }

    function test_RevertFieldMismatch_NonZeroIdForERC20() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, bob, 7, 50_000);
        bytes memory sig = signAuth(token, auth, GUARDIAN_KEY);
        vm.expectRevert(GuardianModule.FieldMismatch.selector);
        token.transferWithAuthorization(auth, sig);
    }

    function test_RevertMint_NonZeroFrom() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_MINT(), alice, bob, 0, 100);
        bytes memory sig = signAuth(token, auth, GUARDIAN_KEY);
        vm.expectRevert(GuardianModule.FieldMismatch.selector);
        token.mintWithAuthorization(auth, sig);
    }

    function test_RevertRotateGuardian_NotAdmin() public {
        vm.prank(alice);
        vm.expectRevert();
        token.rotateGuardian(alice);
    }

    function test_RevertAuthorizedTransfer_FrozenSender() public {
        GuardianModule.Authorization memory freezeAuth =
            buildAuth(address(token), token.OP_FREEZE(), alice, address(0), 0, 1);
        token.setFrozen(freezeAuth, signAuth(token, freezeAuth, GUARDIAN_KEY));

        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, bob, 0, 50_000);
        bytes memory sig = signAuth(token, auth, GUARDIAN_KEY);
        vm.expectRevert(abi.encodeWithSelector(GuardianModule.AddressFrozen.selector, alice));
        token.transferWithAuthorization(auth, sig);
    }

    // ------------------------------------------------------------------- fuzz

    function testFuzz_PlainTransferGate(uint256 amount) public {
        amount = bound(amount, 0, token.balanceOf(alice));
        vm.prank(alice);
        if (amount > THRESHOLD) {
            vm.expectRevert(GuardianModule.GuardianRequired.selector);
            token.transfer(bob, amount);
        } else {
            token.transfer(bob, amount);
            assertEq(token.balanceOf(bob), amount);
        }
    }

    function testFuzz_AuthorizedTransfer_AnyNonceAmount(uint256 nonce, uint256 amount) public {
        amount = bound(amount, 0, token.balanceOf(alice));
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, bob, 0, amount);
        auth.nonce = nonce;
        token.transferWithAuthorization(auth, signAuth(token, auth, GUARDIAN_KEY));
        assertEq(token.balanceOf(bob), amount);
    }

    function testFuzz_DeadlineBoundary(uint64 deadline, uint64 nowTs) public {
        deadline = uint64(bound(deadline, 1, type(uint64).max - 1));
        nowTs = uint64(bound(nowTs, 1, type(uint64).max - 1));
        GuardianModule.Authorization memory auth =
            buildAuth(address(token), token.OP_TRANSFER(), alice, bob, 0, 1_234);
        auth.deadline = deadline;
        bytes memory sig = signAuth(token, auth, GUARDIAN_KEY);
        vm.warp(nowTs);
        if (nowTs > deadline) {
            vm.expectRevert(GuardianModule.AuthorizationExpired.selector);
            token.transferWithAuthorization(auth, sig);
        } else {
            token.transferWithAuthorization(auth, sig);
            assertEq(token.balanceOf(bob), 1_234);
        }
    }
}
