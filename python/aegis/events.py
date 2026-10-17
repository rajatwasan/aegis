"""In-process pub/sub event bus feeding the SSE stream.

Publishers may run on any thread (FastAPI sync handlers run in a threadpool,
the agent runner runs in its own thread); subscribers are asyncio consumers
inside the SSE endpoint. Each subscription pins its queue to the event loop it
was created on, so cross-thread publishes are marshalled with
``call_soon_threadsafe``. A bounded ``recent`` buffer keeps the latest events
for tests and late subscribers that want a snapshot.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import itertools
import threading
from collections import deque
from pathlib import Path
from typing import Any

from aegis.audit import AuditLog, AuditSigner

EVENT_TYPES = (
    "proposal.created",
    "proposal.approved",
    "proposal.rejected",
    "proposal.expired",
    "decision.recorded",
    "anchor.created",
    "agent.step",
)


class EventBus:
    """Thread-safe fan-out of typed JSON events to asyncio subscribers."""

    def __init__(self, history: int = 256) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, tuple[asyncio.Queue[dict[str, Any]], Any]] = {}
        self._tokens = itertools.count(1)
        self._seq = itertools.count(1)
        self.recent: deque[dict[str, Any]] = deque(maxlen=history)

    def publish(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Stamp and deliver one event; safe to call from any thread."""
        event = {
            "seq": next(self._seq),
            "type": event_type,
            "ts": dt.datetime.now(dt.UTC).isoformat(),
            "data": data,
        }
        with self._lock:
            self.recent.append(event)
            subscribers = list(self._subscribers.values())
        for queue, loop in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        return event

    def subscribe(self) -> tuple[int, asyncio.Queue[dict[str, Any]]]:
        """Register the calling event loop as a consumer. Returns (token, queue)."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        with self._lock:
            token = next(self._tokens)
            self._subscribers[token] = (queue, loop)
        return token, queue

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subscribers.pop(token, None)

    def events_of(self, event_type: str) -> list[dict[str, Any]]:
        """Recent events of one type (test/introspection helper)."""
        with self._lock:
            return [e for e in self.recent if e["type"] == event_type]


class EmittingAuditLog(AuditLog):
    """AuditLog that publishes ``decision.recorded`` for every appended record."""

    def __init__(self, path: str | Path, signer: AuditSigner, bus: EventBus) -> None:
        super().__init__(path, signer)
        self.bus = bus

    def append(
        self,
        *,
        actor: str,
        proposal: dict[str, Any],
        policy_result: dict[str, Any],
        human_action: dict[str, Any] | None = None,
        decision_id: str | None = None,
        ts: str | None = None,
        human_presence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = super().append(
            actor=actor,
            proposal=proposal,
            policy_result=policy_result,
            human_action=human_action,
            decision_id=decision_id,
            ts=ts,
            human_presence=human_presence,
        )
        self.bus.publish("decision.recorded", record)
        return record
