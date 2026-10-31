from __future__ import annotations

"""Tiny deterministic event queue shared by experimental combat backends.

The queue knows nothing about WoW, rulesets, classes or combat mechanics.  It
only provides stable time/sequence ordering so class backends can replay exact
cooldown/resource timelines without coupling generic code to a ruleset.
"""

from dataclasses import dataclass, field
import heapq
from typing import Any


@dataclass(order=True, frozen=True)
class Event:
    time: float
    sequence: int
    kind: str = field(compare=False)
    payload: Any = field(default=None, compare=False)


class EventQueue:
    def __init__(self) -> None:
        self._heap: list[Event] = []
        self._sequence = 0

    def __len__(self) -> int:
        return len(self._heap)

    def schedule(self, time: float, kind: str, payload: Any = None) -> Event:
        ev = Event(max(0.0, float(time)), self._sequence, str(kind), payload)
        self._sequence += 1
        heapq.heappush(self._heap, ev)
        return ev

    def pop(self) -> Event:
        return heapq.heappop(self._heap)

    def peek_time(self) -> float | None:
        return self._heap[0].time if self._heap else None
