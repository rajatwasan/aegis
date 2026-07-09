// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {AuditAnchor} from "../src/AuditAnchor.sol";

contract AuditAnchorTest is Test {
    AuditAnchor internal anchorContract;
    address internal admin = makeAddr("admin");
    address internal stranger = makeAddr("stranger");

    function setUp() public {
        anchorContract = new AuditAnchor(admin);
    }

    function test_Anchor() public {
        bytes32 root = keccak256("batch-0");
        vm.prank(admin);
        vm.expectEmit(true, false, false, true);
        emit AuditAnchor.Anchored(0, root);
        anchorContract.anchor(root, 0);
        assertEq(anchorContract.rootOf(0), root);
    }

    function test_RevertDoubleAnchor() public {
        vm.startPrank(admin);
        anchorContract.anchor(keccak256("a"), 1);
        vm.expectRevert(abi.encodeWithSelector(AuditAnchor.BatchAlreadyAnchored.selector, 1));
        anchorContract.anchor(keccak256("b"), 1);
        vm.stopPrank();
    }

    function test_RevertZeroRoot() public {
        vm.prank(admin);
        vm.expectRevert(AuditAnchor.ZeroRoot.selector);
        anchorContract.anchor(bytes32(0), 2);
    }

    function test_RevertNotAnchorRole() public {
        vm.prank(stranger);
        vm.expectRevert();
        anchorContract.anchor(keccak256("x"), 3);
    }

    function testFuzz_AnchorDistinctBatches(bytes32 root, uint256 batchId) public {
        vm.assume(root != bytes32(0));
        vm.prank(admin);
        anchorContract.anchor(root, batchId);
        assertEq(anchorContract.rootOf(batchId), root);
    }
}
