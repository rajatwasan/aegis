"""Merkle tree over audit records: sha256, sorted pairs, duplicate-last for odd.

Sorted-pair hashing (smaller node first) means proofs need no left/right flags.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _pair(a: bytes, b: bytes) -> bytes:
    return _h(a + b) if a <= b else _h(b + a)


class MerkleTree:
    """Built from raw leaf payloads; each leaf node is sha256(payload)."""

    def __init__(self, leaves: Sequence[bytes]) -> None:
        if not leaves:
            raise ValueError("Merkle tree needs at least one leaf")
        self.leaf_nodes = [_h(leaf) for leaf in leaves]
        self.levels: list[list[bytes]] = [self.leaf_nodes]
        level = self.leaf_nodes
        while len(level) > 1:
            if len(level) % 2 == 1:
                level = [*level, level[-1]]
            level = [_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
            self.levels.append(level)

    @property
    def root(self) -> bytes:
        return self.levels[-1][0]

    def proof(self, index: int) -> list[bytes]:
        """Sibling hashes from leaf to root for the leaf at `index`."""
        if not 0 <= index < len(self.leaf_nodes):
            raise IndexError(f"leaf index {index} out of range")
        siblings: list[bytes] = []
        for level in self.levels[:-1]:
            padded = [*level, level[-1]] if len(level) % 2 == 1 else level
            sibling = padded[index ^ 1]
            siblings.append(sibling)
            index //= 2
        return siblings

    @staticmethod
    def verify(leaf: bytes, proof: Sequence[bytes], root: bytes) -> bool:
        """Check that `leaf`'s payload is included under `root` via `proof`."""
        node = _h(leaf)
        for sibling in proof:
            node = _pair(node, sibling)
        return node == root
