"""Class-neutral three-axis candidate composition for the EXISTING gsim/native search.

This module is NOT another optimizer. It supplies propose/mutate/legal callbacks
to native_matrix.search_native; that single kernel still owns exploration.
Class-dependent gear, full 51-point talents, APL and cross-axis legality are
provided by separately verified adapters. Mock callbacks are NEVER native proof.

The player/request paths below are the documented MythicSim Rust request schema,
not a per-class or fixed-16-slot schema.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

from native_matrix import search_native


@dataclass(frozen=True)
class CandidateAxis:
    """One independently source-validated axis; never silently allow all."""
    cold: Callable[[Any], Any]
    mutate: Callable[[Any, Any], Any]
    legal: Callable[[Any], bool]


def _player(request: dict) -> dict:
    return request["raid"]["parties"][0]["players"][0]


def _get(request: dict, axis: str) -> Any:
    player = _player(request)
    if axis == "gear":
        return player["equipment"]["items"]
    if axis == "talents":
        return player["talentsString"]
    if axis == "apl":
        return player["rotation"]["priorityList"]
    raise ValueError("Unknown candidate axis: " + axis)


def _put(request: dict, axis: str, value: Any) -> None:
    player = _player(request)
    if axis == "gear":
        player["equipment"]["items"] = copy.deepcopy(value)
    elif axis == "talents":
        player["talentsString"] = copy.deepcopy(value)
    elif axis == "apl":
        player["rotation"]["priorityList"] = copy.deepcopy(value)
    else:
        raise ValueError("Unknown candidate axis: " + axis)


class JointCandidateAdapter:
    """Compose the three axes without embedding class-dependent search logic.

    Each axis MUST reject illegal values; joint_legal MUST validate class,
    spec, cross-axis restrictions (including equip/talents interactions), and
    source legality in a COMPLETE candidate. A native score is never itself a
    proof of source legality. Non-axis fields are frozen from the source request.
    """

    AXES = ("gear", "talents", "apl")

    def __init__(
        self,
        reference: dict,
        *,
        gear: CandidateAxis,
        talents: CandidateAxis,
        apl: CandidateAxis,
        joint_legal: Callable[[dict], bool],
    ):
        if not callable(joint_legal):
            raise TypeError("A source-backed joint legality callback is required")
        self.reference = copy.deepcopy(reference)
        self.adapters = {"gear": gear, "talents": talents, "apl": apl}
        for axis in self.AXES:
            _get(self.reference, axis)  # fail closed on unsupported native shape
            op = self.adapters[axis]
            if not all(callable(getattr(op, name, None))
                       for name in ("cold", "mutate", "legal")):
                raise TypeError("Missing source-legal operations for " + axis)
        self.joint_legal = joint_legal

    def legal(self, candidate: dict) -> bool:
        try:
            masked = copy.deepcopy(candidate)
            for axis in self.AXES:
                value = _get(candidate, axis)
                if not self.adapters[axis].legal(copy.deepcopy(value)):
                    return False
                _put(masked, axis, _get(self.reference, axis))
            if masked != self.reference:
                return False  # no altered buffs, encounter, consumes or class
            return bool(self.joint_legal(copy.deepcopy(candidate)))
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            return False

    def propose(self, rng) -> dict:
        # Cold generates all three axes; never initialize from a saved winner.
        candidate = copy.deepcopy(self.reference)
        for axis in self.AXES:
            _put(candidate, axis, self.adapters[axis].cold(rng))
        if not self.legal(candidate):
            raise ValueError("Cold JOINT candidate is not source legal")
        return candidate

    def mutate(self, previous: dict, rng) -> dict:
        if not self.legal(previous):
            raise ValueError("Cannot mutate an illegal previous candidate")
        candidate = copy.deepcopy(previous)
        # One shared scheduler for EVERY class; both multi-axis and individual
        # local moves are possible. No per-class path or fixed slot assumptions.
        roll = rng.random()
        count = 1 if roll < .65 else (2 if roll < .90 else 3)
        axes = rng.sample(self.AXES, count)
        for axis in axes:
            value = self.adapters[axis].mutate(copy.deepcopy(_get(candidate, axis)), rng)
            _put(candidate, axis, value)
        if not self.legal(candidate):
            raise ValueError("Mutated JOINT candidate is not source legal")
        return candidate


def search_joint(*, profile_id: str, adapter: JointCandidateAdapter,
                 evaluate: Callable, seconds: float, iterations: int,
                 seed: int, clock=None) -> dict:
    """Delegate to the ONE existing search kernel; evaluator must be real Rust
    in production. This helper is a screening contract, not P7.5 acceptance.
    """
    kwargs = dict(
        profile_id=profile_id, reference=adapter.reference,
        propose=adapter.propose, mutate=adapter.mutate, legal=adapter.legal,
        evaluate=evaluate, seconds=seconds, iterations=iterations, seed=seed,
    )
    if clock is not None:
        kwargs["clock"] = clock
    return search_native(**kwargs)
