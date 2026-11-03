"""Source-observed, class-neutral equipment proposal adapter for MythicSim.

Only same-class fixtures at the same request position supply candidates.
Python constrains the optimizer's proposal domain, not Warcraft equipment
legality: the selected MythicSim Rust evaluator accepts/refuses exact builds.
"""
from __future__ import annotations

import copy
import random


class GearRejected(ValueError):
    def __init__(self, category: str, detail: str):
        self.category = category
        super().__init__(f"{category}: {detail}")


def _player(request):
    return request["raid"]["parties"][0]["players"][0]


def _class_name(class_key: str) -> str:
    return "Class" + class_key.capitalize()


class NativeGearAdapter:
    """Candidate proposals from exact same-class, same-position source fixtures.

    This adapter constrains candidate provenance and request shape only. It
    deliberately does not consult the Python item index or decide item
    identity, slot/type, armor, class, level, hand, or uniqueness legality.
    The selected MythicSim Rust evaluator decides whether each exact proposal
    is valid, invalid, or unsupported.
    """

    def __init__(
        self, class_key: str, reference: dict, fixtures: list[dict],
        items: dict[int, dict] | None = None,
    ):
        self.class_key = class_key
        self.reference = copy.deepcopy(reference)
        # Retained as a compatibility argument for existing callers only.
        # Never use Python item metadata to veto a source-observed proposal.
        self.expected_class = _class_name(class_key)
        if _player(reference)["class"] != self.expected_class:
            raise GearRejected("CLASS_IDENTITY", "Reference belongs to another class")
        self.base = _player(reference)["equipment"]["items"]
        self.pools: dict[int, dict[int, dict]] = {}
        # Multiple pinned requests may use the same item ID with different
        # source-observed enchants/effects. ID-only pools lose those choices.
        self.variants: dict[int, list[dict]] = {}
        for source in fixtures:
            p = _player(source)
            if p.get("class") != self.expected_class:
                continue
            gear = p.get("equipment", {}).get("items", [])
            if len(gear) != len(self.base):
                continue  # no inferred slot reindexing across request schemas
            for index, entry in enumerate(gear):
                iid = entry.get("id", 0)
                original_id = self.base[index].get("id", 0)
                if not isinstance(iid, int) or iid <= 0 or not isinstance(original_id, int) or original_id <= 0:
                    continue
                # Same-class, same-position source entries are proposals.
                # Do not pre-check native DB presence, item type, slot fit,
                # armor, class, level, hand, or uniqueness here; Rust owns all
                # of those decisions, including native INVALID/UNSUPPORTED.
                self.pools.setdefault(index, {})[iid] = copy.deepcopy(entry)
                variants = self.variants.setdefault(index, [])
                if entry not in variants:
                    variants.append(copy.deepcopy(entry))
        # Full observed item entries, not just item IDs, define mutable gear.
        self.mutable_indices = tuple(sorted(
            i for i, variants in self.variants.items()
            if any(entry != self.base[i] for entry in variants)
        ))

    def validate(self, candidate: dict) -> None:
        p = _player(candidate)
        if p.get("class") != self.expected_class:
            raise GearRejected("CLASS_IDENTITY", "Candidate class changed")
        ref_player = _player(self.reference)
        if p.get("talentsString") != ref_player.get("talentsString"):
            raise GearRejected("TALENTS_CHANGED", "Talent dimension must remain fixed")
        if p.get("rotation") != ref_player.get("rotation"):
            raise GearRejected("APL_CHANGED", "APL dimension must remain fixed")
        # The only permitted request difference is equipment.items; never
        # let an altered encounter, buffs, consumables or simOptions through.
        masked = copy.deepcopy(candidate)
        _player(masked)["equipment"]["items"] = copy.deepcopy(self.base)
        if masked != self.reference:
            raise GearRejected("NON_GEAR_CHANGED", "Candidate changed fields outside equipment.items")
        entries = p.get("equipment", {}).get("items", [])
        if len(entries) != len(self.base):
            raise GearRejected("SLOT_COUNT", "Candidate equipment shape changed")
        for i, entry in enumerate(entries):
            iid = entry.get("id", 0)
            if not isinstance(iid, int) or iid < 0:
                raise GearRejected("ITEM_ID", f"Bad item ID at position {i}")
            if iid == 0:
                if entry != self.base[i]:
                    raise GearRejected("EMPTY_SLOT_CHANGED", f"Position {i}")
                continue
            # A source-observed entry is only a proposal. Even native DB
            # identity and slot/type compatibility are decided by Rust.
            if entry != self.base[i] and entry not in self.variants.get(i, []):
                raise GearRejected("SOURCE_SLOT", f"{iid} entry not observed at position {i}")
        # Native Rust decides item identity/type, slot fit, armor, class,
        # level, hand, uniqueness and all other equipment legality.

    def mutate_from(
        self, candidate: dict, rng: random.Random,
        *, excluded_swaps: set[tuple[int, int]] | None = None,
    ) -> tuple[dict, dict]:
        """Add one more source-observed item proposal to an existing candidate.

        Never mutate the caller's request or reset an already searched slot
        to the reference item. The exact source fixture and full non-gear
        request shape are checked before and after mutation; Rust decides
        whether the proposed equipment is valid.
        """
        self.validate(candidate)
        excluded = excluded_swaps or set()
        indices = list(self.mutable_indices)
        rng.shuffle(indices)
        current = _player(candidate)["equipment"]["items"]
        for i in indices:
            old_id = current[i]["id"]
            choices = [
                entry for entry in self.variants[i]
                if entry != current[i] and entry != self.base[i]
                and (i, entry["id"]) not in excluded
            ]
            rng.shuffle(choices)
            for entry in choices:
                iid = entry["id"]
                out = copy.deepcopy(candidate)
                _player(out)["equipment"]["items"][i] = copy.deepcopy(entry)
                try:
                    self.validate(out)
                except GearRejected:
                    continue
                return out, {
                    "source_slot_index": i, "from_id": old_id, "to_id": iid,
                    "restriction_scope": "SAME_CLASS_SOURCE_FIXTURE_AND_POSITION",
                }
        raise GearRejected(
            "NO_SOURCE_OBSERVED_SWAP", "No further source-observed gear proposal"
        )

    def mutate_one(
        self, rng: random.Random, *, excluded_swaps: set[tuple[int, int]] | None = None
    ) -> tuple[dict, dict]:
        """Mutate one source-observed slot; exclude prior native-refused swaps."""
        excluded = excluded_swaps or set()
        if not self.mutable_indices:
            raise GearRejected("NO_SOURCE_BOUNDED_ALTERNATIVE", "No source-observed same-position item proposal")
        indices = list(self.mutable_indices)
        rng.shuffle(indices)
        for i in indices:
            alternatives = [
                entry for entry in self.variants[i]
                if entry != self.base[i] and (i, entry["id"]) not in excluded
            ]
            rng.shuffle(alternatives)
            for entry in alternatives:
                iid = entry["id"]
                out = copy.deepcopy(self.reference)
                _player(out)["equipment"]["items"][i] = copy.deepcopy(entry)
                try:
                    self.validate(out)
                except GearRejected:
                    continue
                return out, {"source_slot_index": i, "from_id": self.base[i]["id"],
                             "to_id": iid, "restriction_scope": "SAME_CLASS_SOURCE_FIXTURE_AND_POSITION"}
        raise GearRejected("NO_SOURCE_OBSERVED_SWAP", "All source-observed alternatives were already excluded")
