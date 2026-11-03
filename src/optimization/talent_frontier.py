"""Game-model-independent talent allocation identity and neighbor values.

Source-backed neighbor generation and legality stay in src.game.talent_frontier.
This module owns only the stable candidate representation used by optimizers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


def allocation_key(selection: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
    """Return a deterministic, positive-rank identity for a talent allocation."""
    return tuple(sorted((str(k), int(v)) for k, v in selection.items() if int(v) > 0))


@dataclass(frozen=True)
class Neighbor:
    allocation: tuple[tuple[str, int], ...]
    operation: str
    changed_ids: tuple[str, ...]

    def as_dict(self):
        return {'allocation': dict(self.allocation), 'operation': self.operation,
                'changed_ids': list(self.changed_ids)}


__all__ = ("Neighbor", "allocation_key")
