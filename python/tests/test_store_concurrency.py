"""The stores share one sqlite connection across threads (request handlers and
the agent runner's worker). Every statement must run under the store lock, or
concurrent reads and writes raise ``sqlite3.InterfaceError`` at random
(AGENTS.md T6: this is the failure that was observed, reproduced on purpose).
"""

from __future__ import annotations

import threading
from pathlib import Path

from aegis.approval.identity import hash_token
from aegis.approval.store import ProposalStore
from aegis.guardian_touch.store import GuardianStore

THREADS = 8
ROUNDS = 60


def hammer(worker, threads: int = THREADS) -> list[BaseException]:
    """Run ``worker(i)`` on ``threads`` threads at once; collect what they raise."""
    errors: list[BaseException] = []
    barrier = threading.Barrier(threads)

    def run(i: int) -> None:
        barrier.wait()
        try:
            worker(i)
        except BaseException as exc:  # noqa: BLE001 - the point is to see every failure
            errors.append(exc)

    pool = [threading.Thread(target=run, args=(i,)) for i in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join(timeout=60)
    return errors


def test_proposal_store_survives_concurrent_reads_and_writes(tmp_path: Path) -> None:
    store = ProposalStore(str(tmp_path / "approvals.db"))
    store.add_approver("casey", "Casey", hash_token("tok"))

    def worker(i: int) -> None:
        for n in range(ROUNDS):
            row, _ = store.create({"amount": n, "from": f"0x{i}"}, 900.0, None)
            assert store.get(row["decision_id"]) is not None
            store.list("pending")
            store.get_approver("casey")
            store.get_approver_by_token_hash(hash_token("tok"))
            if n % 10 == 0:
                store.add_approval(row["decision_id"], {"approver": "casey"}, "ok")
                store.expire_older_than(0)

    assert hammer(worker) == []
    assert len(store.list()) == THREADS * ROUNDS


def test_guardian_store_survives_concurrent_reads_and_writes(tmp_path: Path) -> None:
    ProposalStore(str(tmp_path / "approvals.db"))  # the shared database file
    store = GuardianStore(str(tmp_path / "approvals.db"))

    def worker(i: int) -> None:
        for n in range(ROUNDS):
            code = f"C{i}{n:04d}"
            store.create_pairing_code(code, "casey", 1e12)
            assert store.get_pairing_code(code) is not None
            store.add_credential(f"cred-{i}", b"key", n, "casey")
            store.get_credential(f"cred-{i}")
            store.list_credentials()
            store.update_sign_count(f"cred-{i}", n + 1)

    assert hammer(worker) == []
    assert len(store.list_credentials()) == THREADS
