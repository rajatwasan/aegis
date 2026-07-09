"""M3 tests: Merkle tree construction, proofs, verification."""

import hashlib
import random

import pytest

from aegis.audit import MerkleTree


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _pair(a: bytes, b: bytes) -> bytes:
    return _h(a + b) if a <= b else _h(b + a)


class TestConstruction:
    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError):
            MerkleTree([])

    def test_single_leaf_root_is_leaf_hash(self) -> None:
        tree = MerkleTree([b"only"])
        assert tree.root == _h(b"only")

    def test_two_leaves_sorted_pair(self) -> None:
        tree = MerkleTree([b"a", b"b"])
        assert tree.root == _pair(_h(b"a"), _h(b"b"))

    def test_odd_leaf_count_duplicates_last(self) -> None:
        tree = MerkleTree([b"a", b"b", b"c"])
        left = _pair(_h(b"a"), _h(b"b"))
        right = _pair(_h(b"c"), _h(b"c"))
        assert tree.root == _pair(left, right)


class TestProofs:
    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 8, 13, 100])
    def test_every_leaf_proves_inclusion(self, n: int) -> None:
        leaves = [f"record-{i}".encode() for i in range(n)]
        tree = MerkleTree(leaves)
        for i, leaf in enumerate(leaves):
            assert MerkleTree.verify(leaf, tree.proof(i), tree.root)

    def test_wrong_leaf_fails(self) -> None:
        leaves = [f"record-{i}".encode() for i in range(10)]
        tree = MerkleTree(leaves)
        assert not MerkleTree.verify(b"forged", tree.proof(3), tree.root)

    def test_wrong_root_fails(self) -> None:
        leaves = [f"record-{i}".encode() for i in range(10)]
        tree = MerkleTree(leaves)
        assert not MerkleTree.verify(leaves[3], tree.proof(3), _h(b"other root"))

    def test_proof_for_wrong_index_fails(self) -> None:
        leaves = [f"record-{i}".encode() for i in range(10)]
        tree = MerkleTree(leaves)
        assert not MerkleTree.verify(leaves[3], tree.proof(4), tree.root)

    def test_out_of_range_index_raises(self) -> None:
        tree = MerkleTree([b"a"])
        with pytest.raises(IndexError):
            tree.proof(1)

    def test_random_trees_roundtrip(self) -> None:
        rng = random.Random(99)
        for _ in range(20):
            n = rng.randrange(1, 40)
            leaves = [rng.randbytes(rng.randrange(1, 64)) for _ in range(n)]
            tree = MerkleTree(leaves)
            idx = rng.randrange(n)
            assert MerkleTree.verify(leaves[idx], tree.proof(idx), tree.root)
