"""Source-bounded, class-neutral native Rust equipment probe adapter.

Only items observed at the SAME position in pinned SAME-CLASS request fixtures
may enter a pool. This is an engineering diagnostic, not a proof of full
class/item legality or a cold JOINT optimizer. Native Rust remains the scorer.
"""
from __future__ import annotations

import copy
import random
from collections import Counter


class GearRejected(ValueError):
    def __init__(self, category: str, detail: str):
        self.category = category
        super().__init__(f"{category}: {detail}")


def _player(request):
    return request["raid"]["parties"][0]["players"][0]


def _class_name(class_key: str) -> str:
    return "Class" + class_key.capitalize()


class NativeGearAdapter:
    """Conservative candidate pools from actual same-class native fixtures.

    No 16-slot assumptions, no gsim/Wowhead item identity dependency, and
    no cross-class fixture mixing. Weapon/offhand/ranged positions remain
    fixed until explicit hand/equip rules have been independently verified.
    """

    def __init__(self, class_key: str, reference: dict, fixtures: list[dict], items: dict[int, dict]):
        self.class_key = class_key
        self.reference = copy.deepcopy(reference)
        self.items = items
        self.expected_class = _class_name(class_key)
        if _player(reference)["class"] != self.expected_class:
            raise GearRejected("CLASS_IDENTITY", "Reference belongs to another class")
        self.base = _player(reference)["equipment"]["items"]
        self.pools: dict[int, dict[int, dict]] = {}
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
                native = items.get(iid)
                original = items.get(original_id)
                if not native or not original or native.get("type") != original.get("type"):
                    continue
                if native.get("type") in ("ItemTypeWeapon", "ItemTypeRanged"):
                    continue  # hand, shield, relic and ranged rules are not yet certified
                # A source donor of the same broad slot type is insufficient:
                # e.g. a Mage cloth head cannot silently become a plate head.
                if native.get("armor_type") != original.get("armor_type"):
                    continue
                allow = native.get("class_allowlist") or []
                if allow and self.expected_class not in allow:
                    continue
                required_level = native.get("required_level")
                if required_level is not None and int(required_level) > 60:
                    continue
                self.pools.setdefault(index, {})[iid] = copy.deepcopy(entry)
        # No source loadout is ever described as a cold optimizer proposal.
        self.mutable_indices = tuple(sorted(i for i, pool in self.pools.items()
                                            if any(k != self.base[i]["id"] for k in pool)))

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
        used_ids = []
        limit_categories = []
        for i, entry in enumerate(entries):
            iid = entry.get("id", 0)
            if not isinstance(iid, int) or iid < 0:
                raise GearRejected("ITEM_ID", f"Bad item ID at position {i}")
            if iid == 0:
                if entry != self.base[i]:
                    raise GearRejected("EMPTY_SLOT_CHANGED", f"Position {i}")
                continue
            native = self.items.get(iid)
            if native is None:
                raise GearRejected("ITEM_IDENTITY", f"{iid} absent from native Rust DB")
            allow = native.get("class_allowlist") or []
            if allow and self.expected_class not in allow:
                raise GearRejected("CLASS_ALLOWLIST", f"{iid} excludes {self.expected_class}")
            level = native.get("required_level")
            if level is not None and int(level) > 60:
                raise GearRejected("REQUIRED_LEVEL", f"{iid} requires level {level}")
            if entry != self.base[i] and entry != self.pools.get(i, {}).get(iid):
                raise GearRejected("SOURCE_SLOT", f"{iid} not observed at position {i}")
            used_ids.append(iid)
            cat = native.get("limit_category") or 0
            if int(cat) > 0:
                limit_categories.append(int(cat))
        if any(n > 1 and self.items[iid].get("unique") for iid, n in Counter(used_ids).items()):
            raise GearRejected("UNIQUE_ITEM", "Duplicate native unique item ID")
        if any(n > 1 for n in Counter(limit_categories).values()):
            raise GearRejected("UNIQUE_CATEGORY", "Duplicate native limit_category")

    def mutate_from(
        self, candidate: dict, rng: random.Random,
        *, excluded_swaps: set[tuple[int, int]] | None = None,
    ) -> tuple[dict, dict]:
        """Add one more source-bounded legal item to an existing candidate.

        Never mutate the caller's request or reset an already searched slot
        to the reference item. The source fixture, native item identity and
        full non-gear request are checked before AND after mutation. This is
        still partial gear legality, not certified JOINT search.
        """
        self.validate(candidate)
        excluded = excluded_swaps or set()
        indices = list(self.mutable_indices)
        rng.shuffle(indices)
        current = _player(candidate)["equipment"]["items"]
        for i in indices:
            old_id = current[i]["id"]
            choices = [
                iid for iid in self.pools[i]
                if iid != old_id and iid != self.base[i]["id"]
                and (i, iid) not in excluded
            ]
            rng.shuffle(choices)
            for iid in choices:
                out = copy.deepcopy(candidate)
                _player(out)["equipment"]["items"][i] = copy.deepcopy(self.pools[i][iid])
                try:
                    self.validate(out)
                except GearRejected:
                    continue
                return out, {
                    "source_slot_index": i, "from_id": old_id, "to_id": iid,
                    "restriction_scope": "SAME_CLASS_SOURCE_FIXTURE_AND_NATIVE_DB",
                }
        raise GearRejected(
            "NO_LEGAL_SOURCE_SWAP", "No further source-bounded legal gear mutation"
        )

    def mutate_one(
        self, rng: random.Random, *, excluded_swaps: set[tuple[int, int]] | None = None
    ) -> tuple[dict, dict]:
        """Mutate one source-bounded slot; exclude prior native-failed swaps."""
        excluded = excluded_swaps or set()
        if not self.mutable_indices:
            raise GearRejected("NO_SOURCE_BOUNDED_ALTERNATIVE", "No compatible same-class fixture swap")
        indices = list(self.mutable_indices)
        rng.shuffle(indices)
        for i in indices:
            alternatives = [iid for iid in self.pools[i]
                            if iid != self.base[i]["id"] and (i, iid) not in excluded]
            rng.shuffle(alternatives)
            for iid in alternatives:
                out = copy.deepcopy(self.reference)
                _player(out)["equipment"]["items"][i] = copy.deepcopy(self.pools[i][iid])
                try:
                    self.validate(out)
                except GearRejected:
                    continue
                return out, {"source_slot_index": i, "from_id": self.base[i]["id"],
                             "to_id": iid, "restriction_scope": "SAME_CLASS_SOURCE_FIXTURE_AND_NATIVE_DB"}
        raise GearRejected("NO_LEGAL_SOURCE_SWAP", "All source-bounded alternatives conflict")
