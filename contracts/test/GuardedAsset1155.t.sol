// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {AuthTestBase} from "./AuthTestBase.sol";
import {GuardianModule} from "../src/GuardianModule.sol";
import {GuardedAsset1155} from "../src/GuardedAsset1155.sol";

contract GuardedAsset1155Test is AuthTestBase {
    GuardedAsset1155 internal asset;
    uint256 internal constant CLASS_A = 1; // threshold 100
    uint256 internal constant CLASS_B = 2; // threshold 0 (always gated)

    function setUp() public override {
        super.setUp();
        asset = new GuardedAsset1155("https://example.invalid/{id}", guardian, admin, registry);
        vm.prank(admin);
        asset.setClassThreshold(CLASS_A, 100);
        _mintTo(alice, CLASS_A, 1_000);
        _mintTo(alice, CLASS_B, 1_000);
    }

    function _mintTo(address to, uint256 id, uint256 amount) internal {
        GuardianModule.Authorization memory auth =
            buildAuth(address(asset), asset.OP_MINT(), address(0), to, id, amount);
        asset.mintWithAuthorization(auth, signAuth(asset, auth, GUARDIAN_KEY));
    }

    function test_PlainTransfer_BelowClassThreshold() public {
        vm.prank(alice);
        asset.safeTransferFrom(alice, bob, CLASS_A, 100, "");
        assertEq(asset.balanceOf(bob, CLASS_A), 100);
    }

    function test_AuthorizedTransfer_AboveClassThreshold() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(asset), asset.OP_TRANSFER(), alice, bob, CLASS_A, 500);
        asset.transferWithAuthorization(auth, signAuth(asset, auth, GUARDIAN_KEY));
        assertEq(asset.balanceOf(bob, CLASS_A), 500);
    }

    function test_RevertPlainTransfer_AboveClassThreshold() public {
        vm.prank(alice);
        vm.expectRevert(GuardianModule.GuardianRequired.selector);
        asset.safeTransferFrom(alice, bob, CLASS_A, 101, "");
    }

    function test_RevertPlainTransfer_UnsetThresholdAlwaysGated() public {
        vm.prank(alice);
        vm.expectRevert(GuardianModule.GuardianRequired.selector);
        asset.safeTransferFrom(alice, bob, CLASS_B, 1, "");
    }

    function test_RevertPlainTransfer_NonCompliantRecipient() public {
        vm.prank(alice);
        vm.expectRevert(GuardianModule.GuardianRequired.selector);
        asset.safeTransferFrom(alice, carol, CLASS_A, 1, "");
    }

    function test_RevertBatchTransfer_AnyGatedIdGatesBatch() public {
        uint256[] memory ids = new uint256[](2);
        ids[0] = CLASS_A;
        ids[1] = CLASS_B;
        uint256[] memory amounts = new uint256[](2);
        amounts[0] = 1;
        amounts[1] = 1; // CLASS_B threshold 0 -> gated
        vm.prank(alice);
        vm.expectRevert(GuardianModule.GuardianRequired.selector);
        asset.safeBatchTransferFrom(alice, bob, ids, amounts, "");
    }

    function test_RevertReplayedDecisionId() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(asset), asset.OP_TRANSFER(), alice, bob, CLASS_A, 500);
        bytes memory sig = signAuth(asset, auth, GUARDIAN_KEY);
        asset.transferWithAuthorization(auth, sig);
        vm.expectRevert(
            abi.encodeWithSelector(GuardianModule.DecisionAlreadyConsumed.selector, auth.decisionId)
        );
        asset.transferWithAuthorization(auth, sig);
    }

    function test_RevertWrongSigner() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(asset), asset.OP_TRANSFER(), alice, bob, CLASS_A, 500);
        bytes memory sig = signAuth(asset, auth, MALLORY_KEY);
        vm.expectRevert(GuardianModule.InvalidGuardianSignature.selector);
        asset.transferWithAuthorization(auth, sig);
    }

    function test_RevertFieldMismatch_WrongClass() public {
        GuardianModule.Authorization memory auth =
            buildAuth(address(asset), asset.OP_TRANSFER(), alice, bob, CLASS_A, 500);
        bytes memory sig = signAuth(asset, auth, GUARDIAN_KEY);
        auth.id = CLASS_B; // consume against a different class than signed
        vm.expectRevert(GuardianModule.InvalidGuardianSignature.selector);
        asset.transferWithAuthorization(auth, sig);
    }

    function test_FrozenBlocks1155() public {
        GuardianModule.Authorization memory freezeAuth =
            buildAuth(address(asset), asset.OP_FREEZE(), alice, address(0), 0, 1);
        asset.setFrozen(freezeAuth, signAuth(asset, freezeAuth, GUARDIAN_KEY));

        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(GuardianModule.AddressFrozen.selector, alice));
        asset.safeTransferFrom(alice, bob, CLASS_A, 1, "");
    }

    function testFuzz_ClassThresholdGate(uint256 amount) public {
        amount = bound(amount, 1, 1_000);
        vm.prank(alice);
        if (amount > 100) {
            vm.expectRevert(GuardianModule.GuardianRequired.selector);
            asset.safeTransferFrom(alice, bob, CLASS_A, amount, "");
        } else {
            asset.safeTransferFrom(alice, bob, CLASS_A, amount, "");
            assertEq(asset.balanceOf(bob, CLASS_A), amount);
        }
    }
}
