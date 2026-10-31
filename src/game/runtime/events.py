from __future__ import annotations

"""Generic combat events and deterministic event queue.

The queue knows nothing about classes, spells, or rulesets. Event handlers in
``simulator`` decide what follow-up events a generic Action/Effect produces.
"""

from dataclasses import dataclass, field
import heapq
from typing import Any, Mapping


@dataclass(frozen=True)
class CombatEvent:
    time_s: float
    kind: str
    actor_id: str | None = None
    target_id: str | None = None
    action_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "time_s": float(self.time_s),
            "kind": str(self.kind),
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "action_id": self.action_id,
            "payload": dict(self.payload),
        }


class EventQueue:
    """Stable timestamp-ordered queue for generic combat events."""

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, CombatEvent]] = []
        self._sequence = 0

    def push(self, event: CombatEvent) -> None:
        heapq.heappush(self._heap, (float(event.time_s), self._sequence, event))
        self._sequence += 1


    def peek_time(self) -> float:
        if not self._heap:
            raise IndexError("peek from empty EventQueue")
        return float(self._heap[0][0])

    def pop(self) -> CombatEvent:
        if not self._heap:
            raise IndexError("pop from empty EventQueue")
        return heapq.heappop(self._heap)[2]

    def discard_where(self, predicate) -> int:
        """Cancel future events matching a generic event predicate."""
        before = len(self._heap)
        self._heap = [row for row in self._heap if not predicate(row[2])]
        if len(self._heap) != before:
            heapq.heapify(self._heap)
        return before - len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)

    def __len__(self) -> int:
        return len(self._heap)
