"""Thin source-only bridge to the selected MythicSim Rust `get_options` API.

Rust owns class/level/item/talent/spell mechanics. Never infer spell learnability,
equipment proficiency, or build legality in Python. Exact candidates are still
prepared and paid in the native engine; this only expands the proposal domain.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable


class NativeOptionsError(ValueError):
    """The selected Rust get_options boundary did not provide valid source data."""


def query_native_options(
    binary: str | Path, class_key: str, level: int, *,
    runner: Callable = subprocess.run,
) -> dict:
    """Read one native source snapshot with fail-closed CLI/contract handling."""
    class_key = str(class_key).lower()
    if not class_key or type(level) is not int or not 1 <= level <= 60:
        raise NativeOptionsError("NATIVE_OPTIONS_INVALID_REQUEST")
    cmd = [str(binary), "options", "--class", class_key, "--level", str(level)]
    try:
        result = runner(cmd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeOptionsError("NATIVE_OPTIONS_EXECUTION_FAILED") from exc
    if result.returncode:
        raise NativeOptionsError("NATIVE_OPTIONS_EXECUTION_FAILED:"
                                 + str(result.stderr or "")[-500:])
    try:
        source = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise NativeOptionsError("NATIVE_OPTIONS_INVALID_JSON") from exc
    if (not isinstance(source, dict)
            or source.get("schema_version") != 1
            or source.get("class") != class_key
            or source.get("level") != level
            or not isinstance(source.get("spells"), list)
            or not isinstance(source.get("items"), list)
            or not isinstance(source.get("talents"), dict)
            or not isinstance(source.get("coverage"), dict)
            or not isinstance(source.get("source_revision"), str)):
        raise NativeOptionsError("NATIVE_OPTIONS_INVALID_RESPONSE")
    coverage = source["coverage"]
    if (type(coverage.get("spell_learnability_complete")) is not bool
            or type(coverage.get("item_eligibility_complete")) is not bool
            or coverage.get("talent_prerequisites_complete") is not True
            or source["talents"].get("status") != "ok"
            or not isinstance(source["talents"].get("trees"), list)
            or len(source["talents"]["trees"]) != 3):
        raise NativeOptionsError("NATIVE_OPTIONS_INVALID_COVERAGE")
    for item in source["items"]:
        if not isinstance(item, dict) or type(item.get("item_id")) is not int:
            raise NativeOptionsError("NATIVE_OPTIONS_INVALID_ITEM")
        if item.get("eligibility") == "native_eligible":
            native = item.get("native")
            if (not isinstance(native, dict)
                    or native.get("item_id") != item["item_id"]
                    or not isinstance(native.get("slot"), str)
                    or not native["slot"]):
                raise NativeOptionsError("NATIVE_OPTIONS_INVALID_NATIVE_ITEM")
        elif item.get("eligibility") == "proficiency_unverified":
            if item.get("native") is not None:
                raise NativeOptionsError("NATIVE_OPTIONS_UNVERIFIED_AS_NATIVE")
        else:
            raise NativeOptionsError("NATIVE_OPTIONS_UNKNOWN_ELIGIBILITY")
    return source


def native_equipment_proposals(source: dict, base_items: list[dict]) -> dict[int, list[dict]]:
    """Match a native source slot to an existing equipped item's native slot.

    Never guess the slot of an empty/unknown item or convert unverified options
    into proposals. Multi-item/unique/hand restrictions remain native decisions.
    Native item entries have a valid request shape of `{"id": item_id}`.
    """
    verified = [entry["native"] for entry in source["items"]
                if entry["eligibility"] == "native_eligible"]
    by_id = {entry["item_id"]: entry for entry in verified}
    by_slot: dict[str, list[dict]] = {}
    for native in verified:
        by_slot.setdefault(native["slot"], []).append(native)
    proposals: dict[int, list[dict]] = {}
    for index, equipped in enumerate(base_items):
        if not isinstance(equipped, dict):
            continue
        anchor = by_id.get(equipped.get("id"))
        if anchor is None:
            continue  # no inferred slot, especially for 0/empty slots
        options = [{"id": entry["item_id"]}
                   for entry in by_slot.get(anchor["slot"], [])
                   if entry["item_id"] != equipped["id"]]
        if options:
            proposals[index] = options
    return proposals


def native_joint_request_proposals(
    source: dict, reference: dict, *,
    max_talents: int = 6, max_spells: int = 4,
) -> tuple[list[dict], dict[str, int]]:
    """Produce *unverified* class-neutral talent and spell/APL search requests.

    The native get_options tree indexes and spell IDs supply the move domain.
    One-point transfers are search moves, NOT a Python implementation of tier,
    prerequisite, acquisition or action legality. Every completed request must
    reach native prepare/evaluate; native INVALID/UNSUPPORTED remains decisive.
    """
    import copy

    player = reference["raid"]["parties"][0]["players"][0]
    output: list[dict] = []
    talent_count = 0
    spell_count = 0

    # A string is only mutated if its three source-native tree lengths align.
    original = player.get("talentsString")
    trees = source["talents"]["trees"]
    if isinstance(original, str) and len(trees) == 3:
        parts = original.split("-")
        layouts = [tree.get("talents") for tree in trees]
        if (len(parts) == 3
                and all(isinstance(layout, list) for layout in layouts)
                and all(len(part) <= len(layout)
                        and all(ch in "0123456789" for ch in part)
                        for part, layout in zip(parts, layouts))):
            ranks = [
                [int(ch) for ch in part.ljust(len(layout), "0")]
                for part, layout in zip(parts, layouts)
            ]
            seen = {original}
            for tree_index, layout in enumerate(layouts):
                for source_index, source_rank in enumerate(ranks[tree_index]):
                    if source_rank <= 0:
                        continue
                    # Same-row moves get explored first, but do not make an
                    # eligibility claim. Native decides every exact build.
                    targets = sorted(
                        range(len(layout)),
                        key=lambda index: (
                            layout[index].get("row") != layout[source_index].get("row"),
                            index,
                        ),
                    )
                    for target_index in targets:
                        if target_index == source_index:
                            continue
                        maximum = layout[target_index].get("max_rank")
                        if (type(maximum) is not int
                                or ranks[tree_index][target_index] >= maximum):
                            continue
                        changed = copy.deepcopy(ranks)
                        changed[tree_index][source_index] -= 1
                        changed[tree_index][target_index] += 1
                        candidate = "-".join(
                            "".join(map(str, row)).rstrip("0") for row in changed
                        )
                        if candidate in seen:
                            continue
                        seen.add(candidate)
                        request = copy.deepcopy(reference)
                        request["raid"]["parties"][0]["players"][0]["talentsString"] = candidate
                        output.append(request)
                        talent_count += 1
                        if talent_count >= max_talents:
                            break
                    if talent_count >= max_talents:
                        break
                if talent_count >= max_talents:
                    break

    # Source class-family rows may be passive, triggered or not learned.
    # We never mark these as executable; they enter the search proposal
    # domain only, with the baseline native-positive APL left intact.
    actions = player.get("rotation", {}).get("priorityList")
    if isinstance(actions, list) and 0 < len(actions) < 20:
        known_ids = {
            cast_id
            for entry in actions if isinstance(entry, dict)
            for action in [entry.get("action")]
            if isinstance(action, dict)
            for spell in [action.get("castSpell")]
            if isinstance(spell, dict)
            for identity in [spell.get("spellId")]
            if isinstance(identity, dict)
            for cast_id in [identity.get("spellId")]
            if type(cast_id) is int
        }
        for spell in source["spells"]:
            spell_id = spell.get("spell_id") if isinstance(spell, dict) else None
            if type(spell_id) is not int or spell_id <= 0 or spell_id in known_ids:
                continue
            known_ids.add(spell_id)
            request = copy.deepcopy(reference)
            request["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"].append(
                {"action": {"castSpell": {"spellId": {"spellId": spell_id}}}}
            )
            output.append(request)
            spell_count += 1
            if spell_count >= max_spells:
                break

    return output, {
        "native_options_talent_proposals": talent_count,
        "native_options_unverified_spell_apl_proposals": spell_count,
    }
