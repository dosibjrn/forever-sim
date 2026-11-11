#!/usr/bin/env python3
"""Live Rust-owned Warlock proposals for the one-call native range optimizer.

Independent anchor roots retarget the seed to each requested sample level and
let Rust options/prepare refuse invalid builds. Continuing proposals retain the exact paid native parent and prepare at the
requested sampled level only. Skipped levels are not combat or prepare gates;
this is not an earned XP/travel or continuous world-leveling receipt.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_native_digest(value: Any) -> bool:
    # Rust hashes its deterministic protobuf request; this is NOT the raw
    # source JSON file's SHA-256. Keep both identities in their own domains.
    return isinstance(value, str) and len(value) == 64 and all(
        ch in "0123456789abcdef" for ch in value
    )


def _variants(seed: str, trees: list[dict], *, points_available: int | None = None):
    """Sample transfers between Rust-listed talent slots; Rust judges proposals.

    A small paid budget must reach alternatives in *other* native trees before
    spending every slot on tweaks to the seed tree. No Warcraft tier or talent
    eligibility is asserted here: only Rust prepare can accept or refuse each
    proposed build.
    """
    fields = seed.split("-")
    if len(fields) != 3 or not all(s.isascii() and s.isdigit() for s in fields):
        raise ValueError("source talents are not three numeric trees")
    slots_by_tree = []
    for tree in trees:
        slots = tree.get("talents")
        if not isinstance(slots, list):
            raise ValueError("native options lack tree slots")
        slots_by_tree.append(slots)
    seed_points = sum(int(rank) for part in fields for rank in part)
    # Higher independent roots must be allowed to spend the extra talent
    # points advertised by native options. This is a proposal budget, NOT a
    # Python talent-legality decision: every candidate still goes to Rust.
    proposed_points = (points_available if type(points_available) is int
                       and points_available > seed_points else seed_points)

    # A one-point transfer out of a developed talent tree commonly leaves
    # the original tree dominant.  Source-native prepare must also get a
    # chance to judge genuinely different tree families within a tiny budget.
    # These are *proposals*, not claims of Warcraft legality: slot indices
    # and rank caps are supplied by Rust options; Rust prepare decides.
    def whole_tree_family(target_tree: int):
        remaining = proposed_points
        if remaining == 0:
            return None
        target = ["0"] * len(fields[target_tree])
        for option in slots_by_tree[target_tree]:
            index, maximum = option.get("index"), option.get("max_rank")
            if (type(index) is not int or index < 0
                    or type(maximum) is not int or maximum < 1):
                continue
            target.extend("0" for _ in range(index + 1 - len(target)))
            amount = min(remaining, maximum)
            target[index] = str(amount)
            remaining -= amount
            if remaining == 0:
                break
        if remaining:
            return None
        proposal = ["0" * len(part) for part in fields]
        proposal[target_tree] = "".join(target)
        return "-".join(proposal)

    dominant = max(range(len(fields)), key=lambda idx: sum(
        int(rank) for rank in fields[idx]
    ))
    # The level-scaled candidate is tried first instead of paying a sparse
    # L20 seed at L30/L40/L50/L60 when native offers more points.
    first = (whole_tree_family(dominant) if proposed_points > seed_points
             else None) or seed
    yield first
    seen = {first}
    for target_tree in range(len(fields)):
        if target_tree == dominant:
            continue
        proposal = whole_tree_family(target_tree)
        if proposal is not None and proposal not in seen:
            seen.add(proposal)
            yield proposal

    # Tree-family probes use native points_available, but all subsequent
    # mutations must retain that same level-sized source budget. Otherwise
    # after three families a large paid search silently falls back to tiny
    # mutations of the L20 seed at L30/L40/L50/L60. These remain proposals;
    # Rust prepare, never Forever, judges whether each is executable.
    if first != seed:
        fields = first.split("-")
        # High-level full-tree proposals can all fail Rust preparation (for
        # example on native prerequisites).  Do not let their later mutations
        # exhaust the paid candidate budget without trying the original
        # source root as an independently prepared, explicitly underallocated
        # baseline.  It is never promoted to an optimized high-level build.
        if seed not in seen:
            seen.add(seed)
            yield seed

    def transfer(source_tree: int, src: int, dest_tree: int, dst: int,
                 cap: int):
        if (type(src) is not int or src < 0 or type(dst) is not int
                or dst < 0 or type(cap) is not int or cap < 1
                or (source_tree == dest_tree and src == dst)):
            return None
        source_rank = (int(fields[source_tree][src])
                       if src < len(fields[source_tree]) else 0)
        dest_rank = (int(fields[dest_tree][dst])
                     if dst < len(fields[dest_tree]) else 0)
        if source_rank < 1 or dest_rank >= cap:
            return None
        changed = list(fields)
        for tree_idx, slot, delta in (
            (source_tree, src, -1), (dest_tree, dst, 1)
        ):
            digits = list(changed[tree_idx])
            digits.extend("0" for _ in range(slot + 1 - len(digits)))
            digits[slot] = str(int(digits[slot]) + delta)
            changed[tree_idx] = "".join(digits)
        return "-".join(changed)

    # Round-robin destinations *across* native trees first, so even a budget
    # of three tests seed + other-tree alternatives instead of only tree-0
    # rearrangements. Source-listed slots only; no Python legality table.
    sources = [
        (tree_idx, row.get("index"))
        for tree_idx, slots in enumerate(slots_by_tree)
        for row in slots
        if type(row.get("index")) is int
        and 0 <= row["index"] < len(fields[tree_idx])
        and fields[tree_idx][row["index"]] != "0"
    ]
    for slot_position in range(max((len(slots) for slots in slots_by_tree), default=0)):
        for source_tree, src in sources:
            for dest_tree, slots in enumerate(slots_by_tree):
                if source_tree == dest_tree or slot_position >= len(slots):
                    continue
                dst_row = slots[slot_position]
                candidate = transfer(
                    source_tree, src, dest_tree,
                    dst_row.get("index"), dst_row.get("max_rank"),
                )
                if candidate is not None and candidate not in seen:
                    seen.add(candidate)
                    yield candidate

    # Once competing native trees have been exposed, spend remaining budget
    # on within-tree rank transfers; preparation still has final authority.
    for tree_idx, slots in enumerate(slots_by_tree):
        for source in slots:
            for target in slots:
                candidate = transfer(
                    tree_idx, source.get("index"), tree_idx,
                    target.get("index"), target.get("max_rank"),
                )
                if candidate is not None and candidate not in seen:
                    seen.add(candidate)
                    yield candidate


def _native_apl_variants(seed: dict, prepared: dict):
    """Propose fallback policies from spells registered on the prepared actor.

    get_options spell-family rows include unlearned and triggered spells; they
    must not be presented as executable APL choices. The exact native-prepared
    actor supplies registered SpellFlagAPL actions; Rust prepare judges every
    new policy again. No spell-ID or gameplay-eligibility table lives here.
    """
    actor = seed["raid"]["parties"][0]["players"][0]
    rotation = actor.get("rotation")
    priorities = rotation.get("priorityList") if isinstance(rotation, dict) else None
    if not isinstance(priorities, list) or not priorities:
        return
    spells = prepared.get("player", {}).get("spells", [])
    if not isinstance(spells, list):
        return
    seen = {json.dumps(priorities, sort_keys=True)}
    for spell in spells:
        if not isinstance(spell, dict) or "SpellFlagAPL" not in spell.get("flags", []):
            continue
        action = spell.get("action_id")
        spell_id = action.get("spell_id") if isinstance(action, dict) else None
        if type(spell_id) is not int or spell_id <= 0:
            continue
        proposal = copy.deepcopy(seed)
        fallback = proposal["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
        fallback[-1] = {"action": {"castSpell": {"spellId": {"spellId": spell_id}}}}
        identity = json.dumps(fallback, sort_keys=True)
        if identity not in seen:
            seen.add(identity)
            yield proposal




def _backward_ancestor_variants(hints: Any, *, points_available: int | None):
    """Propose native-option-budget ancestors of paid later talent strings.

    The rank removal order is a search mutation, not Warcraft legality.
    Native Rust prepare must accept any candidate before world evaluation.
    """
    if not isinstance(hints, list) or type(points_available) is not int:
        return
    seen: set[str] = set()
    for hint in hints[:8]:
        if not isinstance(hint, dict) or not isinstance(hint.get("talents"), str):
            continue
        fields = hint["talents"].split("-")
        if len(fields) != 3 or not all(s.isascii() and s.isdigit() for s in fields):
            continue
        for backwards in (True, False):
            parts = [[int(rank) for rank in field] for field in fields]
            excess = sum(sum(tree) for tree in parts) - points_available
            if excess < 0:
                continue
            slots = [(tree, index)
                     for tree in range(3) for index in range(len(parts[tree]))]
            if backwards:
                slots.reverse()
            for tree, index in slots:
                if excess == 0:
                    break
                removal = min(excess, parts[tree][index])
                parts[tree][index] -= removal
                excess -= removal
            if excess:
                continue
            proposal = "-".join("".join(str(rank) for rank in tree) for tree in parts)
            if proposal not in seen:
                seen.add(proposal)
                yield proposal


def _continuing_variants(seed: str, trees: list[dict]):
    """Add only source-listed ranks, never silently replace a paid talent tree."""
    parts = seed.split("-")
    if len(parts) != 3 or not all(p.isascii() and p.isdigit() for p in parts):
        raise ValueError("invalid source talent serialization")
    yield seed
    for number, tree in enumerate(trees):
        for option in tree.get("talents", []):
            slot, cap = option.get("index"), option.get("max_rank")
            if type(slot) is not int or slot < 0 or type(cap) is not int or not 1 <= cap <= 9:
                continue
            digits = list(parts[number])
            digits.extend("0" for _ in range(slot + 1 - len(digits)))
            rank = int(digits[slot])
            if rank >= cap:
                continue
            digits[slot] = str(rank + 1)
            candidate = list(parts)
            candidate[number] = "".join(digits)
            yield "-".join(candidate)


def _paid_parent_source(parent: dict, binary: Path) -> tuple[dict, str]:
    """Read original parent source plus paid native receipt, not a labeled seed."""
    source_sha, engine_sha = parent.get("source_request_sha256"), parent.get("engine_binary_sha256")
    if (not isinstance(source_sha, str) or len(source_sha) != 64
            or not isinstance(engine_sha, str) or _sha256(binary) != engine_sha):
        raise ValueError("native parent source/engine identity mismatch")
    source_path = Path(parent["source_request_file"])
    prepared_path = Path(parent["prepared_file"])
    raw_path = Path(parent["native_raw_receipt_file"])
    # Reusing a paid parent must not silently re-author its original receipt.
    # Legacy receipts without a recorded digest remain supported, but when
    # the scorer supplied one we must preserve those exact paid bytes.
    original_raw_sha = parent.get("native_raw_receipt_sha256")
    if original_raw_sha is not None and (
            not _valid_native_digest(original_raw_sha)
            or _sha256(raw_path) != original_raw_sha):
        raise ValueError("native parent original paid receipt bytes mismatch")
    # Bind the source JSON bytes independently when the scorer recorded their
    # digest. A protobuf request identity alone cannot detect later edits to
    # the source file; historical parents without this field remain readable.
    source_file_sha = parent.get("source_request_file_sha256")
    if source_file_sha is not None and (
            not _valid_native_digest(source_file_sha)
            or _sha256(source_path) != source_file_sha):
        raise ValueError("native parent original source bytes mismatch")
    source = json.loads(source_path.read_text())
    prepared = json.loads(prepared_path.read_text())
    # A native prepare receipt hashes its deterministic protobuf request, not
    # necessarily the source JSON bytes.  Historical file-hash parent IDs are
    # also supported; neither domain is a Python legality/Warcraft proof.
    if (source_sha != _sha256(source_path)
            and source_sha != prepared.get("request_sha256")):
        raise ValueError("native parent source identity mismatch")
    raw = json.loads(raw_path.read_text())
    actor = source["raid"]["parties"][0]["players"][0]
    terminal = raw["native_terminal_recovery"]
    if (actor.get("class") != "ClassWarlock" or actor.get("level") != parent["level"]
            or source["encounter"]["targets"][0].get("level") != parent["level"]
            or not _valid_native_digest(prepared.get("request_sha256"))
            or prepared["player"].get("class") != "ClassWarlock"
            or prepared["player"].get("level") != parent["level"]
            or raw.get("source_sha256") != prepared.get("request_sha256")
            or raw.get("actual_2d_ack") is not True
            or raw.get("world_targets_killed") != parent.get("mob_count")
            or terminal.get("paid") is not True
            or terminal.get("native_clock_accounted") is not True
            or type(terminal.get("max_health")) not in (int, float)
            or type(terminal.get("max_mana")) not in (int, float)
            or terminal["max_health"] <= 0 or terminal["max_mana"] <= 0
            or terminal.get("health_after") != terminal["max_health"]
            or terminal.get("mana_after") != terminal["max_mana"]):
        raise ValueError("native parent paid ACK/prepare mismatch")
    return source, _sha256(raw_path)


def produce_frontier(
    request: dict[str, Any], *, binary: Path, seed_source: Path, out: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Return exact native-prepared files, or native continuation refusal."""
    level, budget = request.get("level"), request.get("budget")
    if (type(level) is not int or not 10 <= level <= 60
            or type(budget) is not int or budget < 1
            or request.get("rng_mode") != "balanced"
            or request.get("iterations") != 1
            or request.get("recover_to_full") is not True
            or type(request.get("mob_count")) is not int
            or not 1 <= request["mob_count"] <= 100):
        raise ValueError("INVALID_NATIVE_FRONTIER_REQUEST")
    parent = request.get("parent")
    raw_parent_sha = None
    if parent is not None:
        try:
            if (not isinstance(parent, dict) or not binary.is_file()
                    or type(parent.get("level")) is not int
                    or not 10 <= parent["level"] < level):
                raise ValueError("native parent level/binary missing")
            seed, raw_parent_sha = _paid_parent_source(parent, binary)
            out = out / parent["source_request_sha256"][:16]
            out.mkdir(parents=True, exist_ok=True)
            # Sparse checkpoints are samples: only the requested level is
            # native-prepared, not each unmeasured skipped level.
            seed = copy.deepcopy(seed)
            seed["raid"]["parties"][0]["players"][0]["level"] = level
            seed["encounter"]["targets"][0]["level"] = level
        except (KeyError, TypeError, ValueError, OSError, IndexError,
                subprocess.TimeoutExpired) as exc:
            return {"entries": [], "refusals": [{
                "candidate_id": None, "status": "NATIVE_CONTINUITY_NOT_ATTESTED",
                "native_refusal": str(exc)[-1500:],
                "native_prepared": False, "level": level,
            "parent_source_sha256": (parent.get("source_request_sha256")
                                     if isinstance(parent, dict) else None),
            }]}
    else:
        if not binary.is_file() or not seed_source.is_file():
            raise ValueError("PINNED_NATIVE_BINARY_OR_SOURCE_MISSING")
        seed = json.loads(seed_source.read_text())
        if request.get("search_mode") == "independent":
            # A root is a same-level Rust proposal, NOT a continuation from
            # the seed level. Rust options/prepare decide whether its build
            # is executable; no skipped-level ancestry or respec is claimed.
            seed = copy.deepcopy(seed)
            seed["raid"]["parties"][0]["players"][0]["level"] = level
            seed["encounter"]["targets"][0]["level"] = level
    actor = seed["raid"]["parties"][0]["players"][0]
    if (actor.get("class") != "ClassWarlock" or actor.get("level") != level
            or seed["encounter"]["targets"][0].get("level") != level):
        raise ValueError("NATIVE_SOURCE_ACTOR_OR_TARGET_LEVEL_MISMATCH")
    options_result = runner([
        str(binary.resolve()), "options", "--class", "warlock", "--level", str(level),
    ], capture_output=True, text=True, timeout=60, check=False)
    if options_result.returncode:
        return {"entries": [], "refusals": [{
            "candidate_id": None, "status": "NATIVE_OPTIONS_REFUSED",
            "native_refusal": (options_result.stderr or options_result.stdout)[-1500:],
            "native_prepared": False, "level": level,
            "parent_source_sha256": (parent.get("source_request_sha256")
                                     if isinstance(parent, dict) else None),
        }]}
    options = json.loads(options_result.stdout)
    talents = options.get("talents", {})
    trees = talents.get("trees")
    if (options.get("level") != level or talents.get("status") != "ok"
            or not isinstance(trees, list) or len(trees) != 3):
        raise ValueError("NATIVE_OPTIONS_INCOMPLETE_FOR_SOURCE_PROPOSALS")

    out.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    refusals: list[dict] = []
    # Keep the root and two distinct talent proposals in a tiny budget, then
    # offer native-registered APL fallbacks before spending every remaining
    # attempt on local talent moves. Every proposal still pays a Rust prepare.
    if parent is not None:
        talent_variants = iter(_continuing_variants(actor["talentsString"], trees))
    else:
        talent_variants = iter(_variants(
            actor["talentsString"], trees,
            points_available=(talents.get("points_available")
                              if request.get("search_mode") == "independent" else None),
        ))
    root_prepared: dict | None = None
    root_proposal: dict | None = None

    def proposals():
        seen_talents: set[str] = set()
        if parent is None:
            for variant in _backward_ancestor_variants(
                    request.get("candidate_hints"),
                    points_available=talents.get("points_available")):
                if variant not in seen_talents:
                    seen_talents.add(variant)
                    yield variant, None
        for _ in range(3):
            variant = next(talent_variants, None)
            if variant is None:
                break
            seen_talents.add(variant)
            yield variant, None
        # A bounded independent higher-level search must try the original
        # same-level source baseline before optional APL alternatives. The
        # first successfully prepared scaled family may advertise many native
        # APL actions; otherwise they can consume the entire remaining budget
        # and the original baseline never reaches Rust prepare.
        if (parent is None and request.get("search_mode") == "independent"
                and actor["talentsString"] not in seen_talents):
            seen_talents.add(actor["talentsString"])
            yield actor["talentsString"], None
        if root_prepared is not None and root_proposal is not None:
            for native_apl in _native_apl_variants(root_proposal, root_prepared):
                yield None, native_apl
        for variant in talent_variants:
            if variant not in seen_talents:
                seen_talents.add(variant)
                yield variant, None

    # Accepted proposals and native prepare refusals share the supplied
    # candidate budget. No extra unpaid attempts are hidden from the caller.
    for index, (talents_string, apl_source) in enumerate(proposals()):
        if index >= budget:
            break
        cid = f"source_{index:03d}"
        proposal = copy.deepcopy(seed) if apl_source is None else apl_source
        if talents_string is not None:
            proposal["raid"]["parties"][0]["players"][0]["talentsString"] = talents_string
        source_path = out / f"{cid}.source.json"
        prepared_path = out / f"{cid}.prepared.json"
        source_path.write_text(json.dumps(proposal, sort_keys=True) + "\n")
        prepared_path.unlink(missing_ok=True)
        try:
            result = runner([
                str(binary.resolve()), "prepare", "--request", str(source_path.resolve()),
                "--actor-level", str(level), "--outfile",
                str(prepared_path.resolve()),
            ], capture_output=True, text=True, timeout=60, check=False)
            if result.returncode:
                raise ValueError((result.stderr or result.stdout)[-1500:])
            prepared = json.loads(prepared_path.read_text())
            player = prepared["player"]
            if (not _valid_native_digest(prepared.get("request_sha256"))
                    or player.get("class") != "ClassWarlock"
                    or player.get("level") != level):
                raise ValueError("prepared native source/actor identity mismatch")
        except (KeyError, ValueError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
            refusals.append({"candidate_id": cid, "status": "NATIVE_PREPARE_REFUSED",
                             "native_prepared": False, "native_refusal": str(exc)[-1500:],
                             "level": level,
                             "parent_source_sha256": (parent["source_request_sha256"]
                                                      if parent is not None else None)})
            continue
        if root_prepared is None and talents_string is not None:
            root_prepared = prepared
            root_proposal = proposal
        entry = {"id": cid, "level": level,
                 "parent_source_sha256": (parent["source_request_sha256"]
                                          if parent is not None else None),
                 "source_request": str(source_path.resolve()),
                 "prepared": str(prepared_path.resolve())}
        if parent is not None:
            lineage_path = out / f"{cid}.continuity.json"
            lineage_path.write_text(json.dumps({
                "source_request_sha256": _sha256(source_path),
                "native_parent_source_sha256": parent["source_request_sha256"],
                "native_parent_raw_receipt_sha256": raw_parent_sha,
                "native_continuity_from_level": parent["level"],
                "native_continuity_ack": True,
                "native_intermediate_levels_verified": False,
                "native_engine_binary_sha256": _sha256(binary),
                "scope": "sampled prepared build lineage, skipped levels unmeasured",
                "infill": [],
            }, sort_keys=True) + "\n")
            entry["native_continuity_receipt"] = str(lineage_path.resolve())
        entries.append(entry)
    return {"entries": entries, "refusals": refusals,
            "native_binary_sha256": _sha256(binary), "level": level,
            "parent_source_sha256": (parent["source_request_sha256"]
                                     if parent is not None else None),
            "source_root_sha256": (_sha256(seed_source) if parent is None else
                                   parent["source_request_sha256"]),
            "native_intermediate_prepares": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--seed-source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    request = json.load(sys.stdin)
    result = produce_frontier(request, binary=args.binary, seed_source=args.seed_source,
                              out=args.out / f"L{request['level']}")
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
