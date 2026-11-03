"""Class-neutral three-axis candidate composition for the EXISTING gsim/native search.

This module is NOT another optimizer. It supplies propose/mutate/candidate-domain
callbacks to native_matrix.search_native; that single kernel still owns
exploration. Class-dependent gear, talent and APL axes constrain candidate
proposals only. MythicSim Rust is authoritative for build legality and native
request evaluation. Mock callbacks are NEVER native proof.

The player/request paths below are the documented MythicSim Rust request schema,
not a per-class or fixed-16-slot schema.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

from native_matrix import search_native


MISSING_TALENT_STRING = ("__FOREVER_MISSING_TALENT_STRING__",)


@dataclass(frozen=True)
class CandidateAxis:
    """One candidate axis; native Rust, not this callback, decides game legality."""
    cold: Callable[..., Any]
    mutate: Callable[..., Any]
    legal: Callable[[Any], bool]
    candidate_aware: bool = False


def _player(request: dict) -> dict:
    return request["raid"]["parties"][0]["players"][0]


def _get(request: dict, axis: str) -> Any:
    player = _player(request)
    if axis == "gear":
        return player["equipment"]["items"]
    if axis == "talents":
        return player.get("talentsString", MISSING_TALENT_STRING)
    if axis == "apl":
        return player["rotation"]["priorityList"]
    raise ValueError("Unknown candidate axis: " + axis)


def _put(request: dict, axis: str, value: Any) -> None:
    player = _player(request)
    if axis == "gear":
        player["equipment"]["items"] = copy.deepcopy(value)
    elif axis == "talents":
        if value == MISSING_TALENT_STRING:
            player.pop("talentsString", None)
        else:
            player["talentsString"] = copy.deepcopy(value)
    elif axis == "apl":
        player["rotation"]["priorityList"] = copy.deepcopy(value)
    else:
        raise ValueError("Unknown candidate axis: " + axis)


class JointCandidateAdapter:
    """Compose the three axes without embedding class-dependent search logic.

    Axis callbacks constrain the optimizer's source-bounded candidate domain;
    they do not prove game legality. joint_legal may enforce request shape,
    class identity and search-domain invariants, but MythicSim Rust validates
    the exact complete request. Non-axis fields are frozen from the source request.
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
            raise TypeError("A joint candidate-domain callback is required")
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
            op = self.adapters[axis]
            value = (
                op.cold(rng, copy.deepcopy(candidate))
                if op.candidate_aware else op.cold(rng)
            )
            _put(candidate, axis, value)
        if not self.legal(candidate):
            raise ValueError("Cold JOINT candidate is outside the candidate domain")
        return candidate

    def mutate(self, previous: dict, rng) -> dict:
        if not self.legal(previous):
            raise ValueError("Cannot mutate a candidate outside the candidate domain")
        candidate = copy.deepcopy(previous)
        # One shared scheduler for EVERY class; both multi-axis and individual
        # local moves are possible. No per-class path or fixed slot assumptions.
        roll = rng.random()
        count = 1 if roll < .65 else (2 if roll < .90 else 3)
        axes = rng.sample(self.AXES, count)
        if any(self.adapters[axis].candidate_aware for axis in axes):
            # Apply dependent axes in declaration order so later axes see
            # earlier choices (notably APL mutation sees the selected donor).
            axes = sorted(axes, key=self.AXES.index)
        for axis in axes:
            op = self.adapters[axis]
            current_value = copy.deepcopy(_get(candidate, axis))
            value = (
                op.mutate(current_value, rng, copy.deepcopy(candidate))
                if op.candidate_aware else op.mutate(current_value, rng)
            )
            _put(candidate, axis, value)
        if not self.legal(candidate):
            raise ValueError("Mutated JOINT candidate is outside the candidate domain")
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
