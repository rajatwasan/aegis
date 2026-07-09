// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {GuardianModule} from "../src/GuardianModule.sol";
import {GuardedToken} from "../src/GuardedToken.sol";
import {ComplianceRegistry} from "../src/ComplianceRegistry.sol";

/// @dev Randomly attempts plain and authorized transfers. Records any plain
///      transfer that crossed a gate (amount above threshold or a non-compliant
///      party) yet succeeded — the invariant says that never happens.
contract TransferHandler is Test {
    GuardedToken public immutable token;
    ComplianceRegistry public immutable registry;
    uint256 internal immutable guardianKey;

    address[] public actors;
    bool public gateBypassed;
    uint256 public authorizedVolume;
    uint256 public consumedCount;
    uint256 internal decisionCounter;

    constructor(
        GuardedToken token_,
        ComplianceRegistry registry_,
        uint256 guardianKey_,
        address[] memory actors_
    ) {
        token = token_;
        registry = registry_;
        guardianKey = guardianKey_;
        actors = actors_;
    }

    function plainTransfer(uint256 fromSeed, uint256 toSeed, uint256 amount) external {
        address from = actors[fromSeed % actors.length];
        address to = actors[toSeed % actors.length];
        amount = bound(amount, 0, token.balanceOf(from));

        bool gated = amount > token.threshold() || !registry.isCompliant(from)
            || !registry.isCompliant(to) || token.frozen(from) || token.frozen(to);

        vm.prank(from);
        try token.transfer(to, amount) {
            if (gated && from != to && amount > 0) gateBypassed = true;
        } catch {}
    }

    function authorizedTransfer(uint256 fromSeed, uint256 toSeed, uint256 amount) external {
        address from = actors[fromSeed % actors.length];
        address to = actors[toSeed % actors.length];
        amount = bound(amount, 0, token.balanceOf(from));
        if (from == to || token.frozen(from) || token.frozen(to)) return;

        decisionCounter++;
        GuardianModule.Authorization memory auth = GuardianModule.Authorization({
            decisionId: keccak256(abi.encode("inv", decisionCounter)),
            operation: 1,
            token: address(token),
            from: from,
            to: to,
            id: 0,
            amount: amount,
            policyHash: keccak256("policy-v1"),
            nonce: decisionCounter,
            deadline: block.timestamp + 1 hours
        });
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(guardianKey, token.hashAuthorization(auth));
        token.transferWithAuthorization(auth, abi.encodePacked(r, s, v));
        authorizedVolume += amount;
        consumedCount++;
    }
}

contract GuardedTokenInvariantTest is Test {
    uint256 internal constant GUARDIAN_KEY = 0xA11CE;
    uint256 internal constant THRESHOLD = 10_000;

    GuardedToken internal token;
    ComplianceRegistry internal registry;
    TransferHandler internal handler;

    function setUp() public {
        address admin = makeAddr("admin");
        address guardian = vm.addr(GUARDIAN_KEY);
        registry = new ComplianceRegistry(admin);
        token = new GuardedToken("Aegis Guarded", "AGD", guardian, admin, registry, THRESHOLD);

        address[] memory actors = new address[](4);
        actors[0] = makeAddr("actor0"); // compliant
        actors[1] = makeAddr("actor1"); // compliant
        actors[2] = makeAddr("actor2"); // non-compliant
        actors[3] = makeAddr("actor3"); // non-compliant
        vm.startPrank(admin);
        registry.setClaim(actors[0], registry.TOPIC_KYC(), true, 0);
        registry.setClaim(actors[1], registry.TOPIC_KYC(), true, 0);
        vm.stopPrank();

        handler = new TransferHandler(token, registry, GUARDIAN_KEY, actors);

        // seed balances via guardian-authorized mints
        for (uint256 i = 0; i < actors.length; i++) {
            GuardianModule.Authorization memory auth = GuardianModule.Authorization({
                decisionId: keccak256(abi.encode("seed", i)),
                operation: 2,
                token: address(token),
                from: address(0),
                to: actors[i],
                id: 0,
                amount: 1_000_000,
                policyHash: keccak256("policy-v1"),
                nonce: i,
                deadline: block.timestamp + 1 hours
            });
            (uint8 v, bytes32 r, bytes32 s) = vm.sign(GUARDIAN_KEY, token.hashAuthorization(auth));
            token.mintWithAuthorization(auth, abi.encodePacked(r, s, v));
        }

        targetContract(address(handler));
        bytes4[] memory selectors = new bytes4[](2);
        selectors[0] = TransferHandler.plainTransfer.selector;
        selectors[1] = TransferHandler.authorizedTransfer.selector;
        targetSelector(FuzzSelector({addr: address(handler), selectors: selectors}));
    }

    /// @notice No gated transfer ever succeeds without a consumed authorization.
    function invariant_NoGatedTransferWithoutAuthorization() public view {
        assertFalse(handler.gateBypassed());
    }

    /// @notice Total supply is conserved by transfers (only mints created it).
    function invariant_SupplyConserved() public view {
        assertEq(token.totalSupply(), 4_000_000);
    }
}
