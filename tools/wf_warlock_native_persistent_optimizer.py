"""Persistent Rust options/prepare/evaluate adapter for the generic optimizer.

Only Rust decides whether a proposed build is executable. World damage, travel,
survival and full-resource recovery run through the existing causal gsim bridge.
No source/prepared JSON exchange files or Python Warcraft rules are involved.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

# Class plugin metadata; native_range_optimizer owns the shared ranking pipeline.
DEFAULT_NATIVE_SOURCE = Path("fixtures/warlock-l20-native-paid-30s.request.json")
import subprocess
import sys
from typing import Any, Callable

from src.scenarios.leveling_targets import representative_hp
from tools.wf_warlock_native_source_frontier import (
    _backward_ancestor_variants, _native_apl_variants, _variants,
)
from tools.wf_warlock_native_candidate_scoring import (
    _exact_paid_cache_identity, _verified_legacy_paid_cache, score_native_chain,
)

BRIDGE = Path(__file__).resolve().parents[1] / "integrations/mythicsim-rust"
if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> str:
    return _digest(path.read_bytes())


def _forward_native_talent_hints(hints: Any, *, level: int,
                                 points_available: int, trees: list[dict]):
    """Carry source-paid earlier talent families and propose native-option spends.

    Earlier allocations are not respeced or automatically made legal: each
    candidate still pays Rust prepare and genuine gsim/Rust world evaluation.
    """
    if not isinstance(hints, list) or type(points_available) is not int:
        return
    seen: set[str] = set()
    for hint in hints[:12]:
        if (not isinstance(hint, dict)
                or type(hint.get("from_level")) is not int
                or hint["from_level"] >= level
                or not isinstance(hint.get("talents"), str)):
            continue
        original = hint["talents"]
        pieces = original.split("-")
        if len(pieces) != 3 or not all(
                piece.isascii() and piece.isdigit() for piece in pieces):
            continue
        ranks = [[int(value) for value in piece] for piece in pieces]
        spent = sum(sum(p) for p in ranks)
        if spent > points_available:
            continue
        if original not in seen:
            seen.add(original)
            yield original
        # Native options supply only slot index and rank cap. Any additional
        # tier/prerequisite and level legality belongs solely to Rust prepare.
        for order in ([0, 1, 2], [1, 0, 2], [2, 0, 1]):
            next_ranks = [p[:] for p in ranks]
            needed = points_available - spent
            for tree_index in order:
                slots = trees[tree_index].get("talents", [])
                for slot in slots:
                    idx, cap = slot.get("index"), slot.get("max_rank")
                    if (type(idx) is not int or idx < 0
                            or type(cap) is not int or not 1 <= cap <= 9):
                        continue
                    next_ranks[tree_index].extend(
                        [0] * max(0, idx + 1 - len(next_ranks[tree_index])))
                    old = next_ranks[tree_index][idx]
                    extra = min(needed, max(0, cap - old))
                    next_ranks[tree_index][idx] += extra
                    needed -= extra
                    if needed == 0:
                        break
                if needed == 0:
                    break
            if needed:
                continue
            candidate = "-".join(
                "".join(map(str, tree)) for tree in next_ranks)
            if candidate not in seen:
                seen.add(candidate)
                yield candidate


# Equipment positions are protobuf request serialization slots, not a Python
# item-eligibility catalogue. Rust supplies each candidate's native slot and
# decides complete equipment legality during prepare.
_NATIVE_EQUIPMENT_POSITIONS = {
    "head": (0,), "neck": (1,), "shoulder": (2,), "back": (3,),
    "chest": (4,), "wrist": (5,), "hands": (6,), "waist": (7,),
    "legs": (8,), "feet": (9,), "finger": (10, 11),
    "trinket": (12, 13), "main_hand": (14,), "one_hand": (14,),
    "two_hand": (14,), "off_hand": (15,), "ranged": (16,),
}


def _source_item_alternatives(source: dict, options: dict):
    """Source-listed slot proposals; only Rust prepare can judge the build.

    The L20 reference's historical 17 items may be absent from the current
    native options. Try the sanitized baseline AND actually equipped variants,
    not 17 deletion-only proposals labeled gear optimization.  Unverified
    native rows never acquire a guessed slot.
    """
    choices = options.get("items", [])
    if not isinstance(choices, list):
        yield source
        return
    verified = [row for row in choices
                if isinstance(row, dict)
                and row.get("eligibility") == "native_eligible"
                and isinstance(row.get("native"), dict)
                and type(row.get("item_id")) is int
                and isinstance(row["native"].get("slot"), str)]
    available = {row["item_id"] for row in choices
                 if isinstance(row, dict) and type(row.get("item_id")) is int}
    actor = source["raid"]["parties"][0]["players"][0]
    equipped = actor.get("equipment", {}).get("items", [])
    if not isinstance(equipped, list):
        yield source
        return
    base = copy.deepcopy(source)
    items = base["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    for index, row in enumerate(equipped):
        if isinstance(row, dict) and row.get("id") not in (None, 0, *available):
            items[index] = {"id": 0}
    yield base
    by_position: dict[int, list[int]] = {}
    for row in verified:
        for index in _NATIVE_EQUIPMENT_POSITIONS.get(row["native"]["slot"], ()):
            if index < len(items):
                ids = by_position.setdefault(index, [])
                if row["item_id"] not in ids:
                    ids.append(row["item_id"])
    if not by_position:
        return

    # An all-empty sanitized historical fixture cannot fight fairly. Construct
    # one complete, Rust-advertised slot proposal, then vary one item at a time.
    # No item is called legal until the *whole* native prepare succeeds.
    anchor = copy.deepcopy(base)
    anchor_items = anchor["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    for index, ids in by_position.items():
        if anchor_items[index].get("id", 0) == 0:
            anchor_items[index] = {"id": ids[0]}
    if anchor != base:
        yield anchor
    # Compare the second Rust-listed item for a slot against a consistent
    # native-equipped reference; avoid a whole-search explosion.
    for index in sorted(by_position):
        current = anchor_items[index].get("id", 0)
        for item_id in by_position[index][:3]:
            if item_id == current:
                continue
            proposal = copy.deepcopy(anchor)
            proposal["raid"]["parties"][0]["players"][0]["equipment"][
                "items"][index] = {"id": item_id}
            yield proposal


def _source_pet_alternatives(source: dict, options: dict):
    """Use Rust-advertised summons or its exact pinned protobuf enum source.

    An enum is a request proposal, not evidence the level/actor can summon it.
    Any non-executable pet is refused by the same native prepare/world scorer.
    """
    from itertools import islice
    choices = options.get("summons", options.get("pets"))
    if choices is None and options.get("schema_version") == 1:
        # The selected engine's generated request schema, not a Python
        # Warlock mechanics table. The current options API omits pet choices.
        schema_path = BRIDGE / "engine" / "data" / "proto-schema.json"
        try:
            schema = json.loads(schema_path.read_text())
            choices = [entry["name"] for entry in schema["enums"][
                "proto.WarlockOptions.Summon"]]
        except (KeyError, ValueError, OSError, TypeError):
            choices = []
    if not isinstance(choices, list):
        return
    actor = source["raid"]["parties"][0]["players"][0]
    current = actor.get("warlock", {}).get("options", {}).get(
        "classOptions", {}).get("summon")
    seen = {current}
    if current in (None, "NoSummon", 0):
        # The old fixture's absent summon already means no active pet.
        # Do not spend another paid world on a synonymous NoSummon enum.
        seen.update((None, 0, "NoSummon"))
    for choice in islice(choices, 12):
        value = choice.get("name") if isinstance(choice, dict) else choice
        if not isinstance(value, (str, int)) or value in seen:
            continue
        seen.add(value)
        proposal = copy.deepcopy(source)
        cls = proposal["raid"]["parties"][0]["players"][0].setdefault(
            "warlock", {}).setdefault("options", {}).setdefault("classOptions", {})
        cls["summon"] = value
        yield proposal


def _level_aware_apl_variants(source: dict, prepared: dict, options: dict):
    """Re-rank/reorder learned native APL spells, then fall back to old probes.

    A spell must be registered with SpellFlagAPL on the prepared actor. Rust
    still decides every changed APL's legality and real combat effects.
    """
    prepared_spells = prepared.get("player", {}).get("spells", [])
    registry = {
        row["action_id"]["spell_id"] for row in prepared_spells
        if isinstance(row, dict) and "SpellFlagAPL" in row.get("flags", [])
        and isinstance(row.get("action_id"), dict)
        and type(row["action_id"].get("spell_id")) is int
    } if isinstance(prepared_spells, list) else set()
    source_spells = {
        row["spell_id"]: row for row in options.get("spells", [])
        if isinstance(row, dict) and type(row.get("spell_id")) is int
    }
    actor = source["raid"]["parties"][0]["players"][0]
    original = actor.get("rotation", {}).get("priorityList", [])
    seen = {json.dumps(original, sort_keys=True)}
    if isinstance(original, list) and not original:
        # The level-correct native actor may prepare only after clearing an
        # inherited APL with a now-unregistered rank. Its registered spells,
        # NOT the invalid L20/L40 fixture or raw spell family options, are the
        # sole source for new, independently prepared and paid rotations.
        registered = [
            spell for spell in prepared_spells
            if isinstance(spell, dict) and
            "SpellFlagAPL" in spell.get("flags", [])
            and isinstance(spell.get("action_id"), dict)
            and type(spell["action_id"].get("spell_id")) is int
            and spell["action_id"]["spell_id"] > 0
        ] if isinstance(prepared_spells, list) else []
        observed: set[int] = set()
        enabled = []
        for spell in registered:
            sid = spell["action_id"]["spell_id"]
            if sid not in observed:
                observed.add(sid)
                enabled.append(spell)
        # Prefer native-reported combat effects, yet retain other registered
        # APL actions when the prepared contract lacks effect annotations.
        effectful = [spell for spell in enabled
                     if isinstance(spell.get("dot"), dict)
                     or isinstance(spell.get("damage_effect"), dict)]
        selected = effectful or enabled
        def action_for(spell):
            sid = spell["action_id"]["spell_id"]
            action = {"action": {"castSpell": {
                "spellId": {"spellId": sid}}}}
            if isinstance(spell.get("dot"), dict):
                action["action"]["condition"] = {"not": {"val": {
                    "dotIsActive": {"spellId": {"spellId": sid}}}}}
            return action
        variants = [[action_for(spell)] for spell in selected[:8]]
        dots = [spell for spell in selected
                if isinstance(spell.get("dot"), dict)]
        directs = [spell for spell in selected
                   if isinstance(spell.get("damage_effect"), dict)]
        for dot in dots[:2]:
            for direct in directs[:2]:
                if dot["action_id"]["spell_id"] != direct["action_id"]["spell_id"]:
                    variants.insert(0, [action_for(dot), action_for(direct)])
        for priorities in variants:
            signature = json.dumps(priorities, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            proposal = copy.deepcopy(source)
            proposal["raid"]["parties"][0]["players"][0][
                "rotation"]["priorityList"] = priorities
            yield proposal
        return
    # Replace existing spell ranks with the last registered source rank of
    # the *same named spell*. No item/spell learnability is inferred from
    # get_options alone; intersection with prepared registry is mandatory.
    if isinstance(original, list):
        for index, priority in enumerate(original):
            action = priority.get("action", {}) if isinstance(priority, dict) else {}
            cast = action.get("castSpell", {})
            original_id = cast.get("spellId", {}).get("spellId")
            old = source_spells.get(original_id, {})
            name = old.get("name")
            if not name:
                continue
            ranked = [row for sid, row in source_spells.items()
                      if sid in registry and row.get("name") == name
                      and sid != original_id]
            def rank_number(row):
                import re
                match = re.search(r"\d+", str(row.get("rank", "")))
                return int(match.group()) if match else 0
            ranked.sort(key=lambda row: (rank_number(row), row["spell_id"]),
                        reverse=True)
            for row in ranked[:1]:
                candidate = copy.deepcopy(source)
                priority_list = candidate["raid"]["parties"][0]["players"][0][
                    "rotation"]["priorityList"]
                # Update the requested rank and any matching native dot guard.
                edited = priority_list[index]["action"]
                edited["castSpell"]["spellId"]["spellId"] = row["spell_id"]
                guard = edited.get("condition", {}).get(
                    "not", {}).get("val", {}).get("dotIsActive")
                if isinstance(guard, dict):
                    spell = guard.get("spellId")
                    if isinstance(spell, dict) and spell.get("spellId") == original_id:
                        spell["spellId"] = row["spell_id"]
                signature = json.dumps(priority_list, sort_keys=True)
                if signature not in seen:
                    seen.add(signature)
                    yield candidate
        for proposal in _native_apl_variants(source, prepared):
            signature = json.dumps(proposal["raid"]["parties"][0][
                "players"][0]["rotation"]["priorityList"], sort_keys=True)
            if signature not in seen:
                seen.add(signature)
                yield proposal
        # Priority is a genuine search dimension even when no new spell is
        # available: source-native prepare and ACK judge reordered policies.
        for index in range(len(original) - 1):
            candidate = copy.deepcopy(source)
            actions = candidate["raid"]["parties"][0]["players"][0][
                "rotation"]["priorityList"]
            actions[index], actions[index + 1] = actions[index + 1], actions[index]
            signature = json.dumps(actions, sort_keys=True)
            if signature not in seen:
                seen.add(signature)
                yield candidate


def _described_build(source: dict, options: dict) -> dict:
    """Human-readable native *proposal* labels, never gameplay certificates."""
    actor = source["raid"]["parties"][0]["players"][0]
    item_by_id = {row["item_id"]: row for row in options.get("items", [])
                  if isinstance(row, dict) and type(row.get("item_id")) is int}
    spell_by_id = {row["spell_id"]: row for row in options.get("spells", [])
                   if isinstance(row, dict) and type(row.get("spell_id")) is int}
    gear = []
    for pos, row in enumerate(actor.get("equipment", {}).get("items", [])):
        item_id = row.get("id") if isinstance(row, dict) else None
        item = item_by_id.get(item_id, {})
        metadata = item.get("native") or item.get("legacy_wowhead") or {}
        gear.append({"position": pos, "item_id": item_id,
                     "name": metadata.get("name"),
                     "native_slot": (item.get("native") or {}).get("slot")})
    spells = []
    for pos, row in enumerate(actor.get("rotation", {}).get("priorityList", [])):
        action = row.get("action", {}) if isinstance(row, dict) else {}
        spell_id = action.get("castSpell", {}).get("spellId", {}).get("spellId")
        native = spell_by_id.get(spell_id, {})
        spells.append({"priority": pos + 1, "spell_id": spell_id,
                       "name": native.get("name"), "rank": native.get("rank"),
                       "condition": action.get("condition")})
    talents = []
    encoded = actor.get("talentsString", "").split("-")
    for tree_index, tree in enumerate(options.get("talents", {}).get("trees", [])):
        digits = encoded[tree_index] if tree_index < len(encoded) else ""
        for row in tree.get("talents", []):
            index = row.get("index")
            rank = int(digits[index]) if type(index) is int and index < len(
                digits) else 0
            if rank:
                talents.append({"tree": tree.get("name"), "name": row.get("name"),
                                "rank": rank, "max_rank": row.get("max_rank")})
    return {"talent_names": talents, "equipped_item_names_ids": gear,
            "ordered_apl_spells": spells}

class NativeApiRefusal(ValueError):
    """Keep the Rust refusal code structured across the NDJSON transport."""

    def __init__(self, error):
        self.code = error.get("code") if isinstance(error, dict) else None
        self.reason = error.get("reason") if isinstance(error, dict) else str(error)
        super().__init__("RUST_NATIVE_API_REFUSAL:" + str(error)[-1200:])


class NativeApiSession:
    """One pinned binary and one ordered NDJSON stream for all sampled levels."""

    def __init__(self, binary: Path):
        self.process = subprocess.Popen(
            [str(binary.resolve()), "api"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
            env=dict(os.environ, FOREVER_GSIM_WORLD_BRIDGE="1"),
        )

    def request(self, payload: dict) -> dict:
        if self.process.poll() is not None:
            raise RuntimeError("RUST_NATIVE_API_PROCESS_EXITED")
        self.process.stdin.write(json.dumps(payload, sort_keys=True) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("RUST_NATIVE_API_NO_RESPONSE")
        response = json.loads(line)
        if response.get("ok") is not True:
            # Rust emits a human-readable error beside a structured refusal.
            # Forward the native code/reason when supplied; older engine pins
            # only carry the legacy string error.
            refusal = response.get("refusal")
            raise NativeApiRefusal(
                refusal if isinstance(refusal, dict) else response.get("error"))
        if not isinstance(response.get("result"), dict):
            raise ValueError("RUST_NATIVE_API_RESULT_INVALID")
        return response["result"]

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdout.close()
        self.process.stderr.close()


ROLLING_WORLD_APL_50 = {
    "pull_mode": "rolling",
    "switch_trigger": {
        "type": "current_target_hp_fraction_at_most",
        "fraction": 0.5,
    },
    "max_live_targets": 2,
}


class UnverifiedNativeWorldReceipt(ValueError):
    """The native world ran but its returned receipt cannot certify overlap."""

    def __init__(self, receipt_path: Path, receipt_sha256: str):
        super().__init__("RUST_WORLD_NATIVE_ROLLING_APL_NOT_PROVEN")
        self.receipt_path = str(receipt_path)
        self.receipt_sha256 = receipt_sha256


def _native_world_policy(rest_health: float, rest_mana: float,
                         world_apl: dict | None = None) -> dict:
    return {
        "pull_mode": "rolling" if world_apl is not None else "serial",
        "rest_when_health_below": rest_health,
        "rest_when_mana_below": rest_mana,
        "rest_until": "full_when_triggered",
        "terminal_full_hp_and_mana": True,
        **({"world_apl": copy.deepcopy(world_apl)}
           if world_apl is not None else {}),
    }


def _native_rolling_receipt_verified(receipt: dict, world_apl: dict | None) -> bool:
    """Never reuse an overlap receipt without its source/gsim target-ID join."""
    if world_apl is None:
        # An omitted policy is the serial control only when native Rust
        # did not independently report applying a rolling World-APL.
        return (receipt.get("native_world_apl") is None
                and receipt.get("native_world_overlap_verified") is not True
                and receipt.get("native_world_overlap") is None)
    overlap = receipt.get("native_world_overlap")
    kills = receipt.get("world_kills")
    if (receipt.get("native_world_apl") != world_apl
            or receipt.get("native_world_overlap_verified") is not True
            or not isinstance(overlap, dict)
            or overlap.get("max_concurrent_alive_targets") != 2
            or type(overlap.get("old_target_dot_ticks_after_switch_acked")) is not int
            or overlap["old_target_dot_ticks_after_switch_acked"] < 1
            or not isinstance(kills, list) or len(kills) != 2
            or any(not isinstance(kill, dict) for kill in kills)):
        return False
    target_ids = [kill.get("target_id") for kill in kills]
    ack_ids = [kill.get("ack_sha256") for kill in kills]
    live_ids = overlap.get("simultaneously_alive_world_target_ids")
    mapping = overlap.get("native_target_to_world_id")
    return (
        all(isinstance(value, str) and value
            for value in (*target_ids, *ack_ids))
        and len(set(target_ids)) == 2 and len(set(ack_ids)) == 2
        and isinstance(live_ids, list) and len(live_ids) == 2
        and all(isinstance(value, str) and value for value in live_ids)
        and set(live_ids) == set(target_ids)
        and isinstance(mapping, dict) and len(mapping) == 2
        # Native slots are 0 and 1 for this exact two-world-target API.
        # Arbitrary numeric keys would permit a mismapped paid cache hit.
        and set(mapping) == {"0", "1"}
        and all(isinstance(value, str) and value
                for value in mapping.values())
        and set(mapping.values()) == set(target_ids)
    )


class PersistentNativeEvaluator:
    """Callable native candidate evaluator shared by stride 20/10/5/1.

    The session and exact-compatible paid cache outlive individual levels.
    Every candidate consumes one Rust prepare attempt; failures stay visible.
    """

    def __init__(self, binary: Path, source: Path, artifact_dir: Path, *,
                 target_hp: float | None = None,
                 session_factory: Callable = NativeApiSession,
                 run_world: Callable | None = None,
                 compare_world_rest_30: bool = False,
                 compare_world_rolling_50: bool = False):
        self.binary = binary
        self.compare_world_rest_30 = compare_world_rest_30
        self.compare_world_rolling_50 = compare_world_rolling_50
        self.template = json.loads(source.read_text())
        self.artifact_dir = artifact_dir
        self.target_hp = target_hp
        self.session = session_factory(binary)
        if run_world is None:
            from live_two_world_pulls import run as run_world
        self.run_world = run_world
        self.engine_sha = _file_digest(binary)
        # The binary and checkout are fixed for this native API session.
        # Initialize the expensive Git/binary cache identity at the *first
        # paid proposal*, not from a source fixture (which can omit level).
        # A session with only native prepare refusals pays no cache setup.
        self._paid_cache_identity_seed: dict | None = None
        self._paid_cache_identity_initialized = False
        # Reuse identical paid worlds within this immutable native API session
        # even when a dirty/unavailable Git checkout disables disk cache reuse.
        # Never persist this unverified identity across sessions.
        self._session_paid: dict[tuple, tuple[dict, float, Path, str]] = {}
        self.options: dict[int, dict] = {}
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def close(self):
        self.session.close()

    def _options(self, level: int) -> dict:
        if level not in self.options:
            self.options[level] = self.session.request(
                {"op": "options", "class": "warlock", "level": level})
        return self.options[level]

    def _source(self, level: int, talents: str | None, *,
                apl_source: dict | None = None) -> dict:
        source = copy.deepcopy(apl_source if apl_source is not None else self.template)
        actor = source["raid"]["parties"][0]["players"][0]
        actor["level"] = level
        source["encounter"]["targets"][0]["level"] = level
        # The original L20 fixture has a 12s stationary smoke horizon.
        # Full level-scaled mobs at L40/L60 can require longer to die.
        # This is only a generous source-native fight timeout, never elapsed
        # charged time: Rust/gsim uses actual lethal ACK and recovery clocks.
        source["encounter"]["duration"] = max(
            180, int(source["encounter"].get("duration", 0)))
        if talents is not None:
            actor["talentsString"] = talents
        return source

    def _paid(self, source: dict, prepared: dict, *, level: int, mobs: int,
              target_hp: float, cid: str, fresh_world: bool = False,
              health_threshold: float = 1.0,
              mana_threshold: float = 1.0,
              world_apl: dict | None = None) -> tuple[dict, float, bool, Path]:
        native_sha = prepared["request_sha256"]
        rest_policy = (float(health_threshold), float(mana_threshold))
        # Cache includes the exact source-produced prepared actor, not a
        # raw-JSON SHA wrongly equated to Rust's protobuf request digest.
        prepared_digest = _digest(json.dumps(
            prepared, sort_keys=True, separators=(",", ":")).encode())
        # The native source/actor and paid world configuration must match
        # exactly. A fresh actor is prepared for every independent sample;
        # this memo never substitutes for a retained-state/XP transition.
        policy_key = (json.dumps(world_apl, sort_keys=True)
                      if world_apl is not None else None)
        session_key = (native_sha, prepared_digest, level, mobs,
                       float(target_hp), rest_policy, policy_key)
        previous = None if fresh_world else self._session_paid.get(session_key)
        if previous is not None:
            old_receipt, old_elapsed, old_path, old_digest = previous
            try:
                if (_file_digest(old_path) == old_digest
                        and _native_rolling_receipt_verified(old_receipt, world_apl)
                        and score_native_chain(
                            old_receipt, prepared, mob_count=mobs,
                            expected_target_hp=target_hp
                        ) == (old_elapsed, "MEASURED_NATIVE_FULLY_RECOVERED")):
                    return old_receipt, old_elapsed, True, old_path
            except (ValueError, TypeError, OSError, KeyError):
                pass
            self._session_paid.pop(session_key, None)

        def retain(receipt: dict, elapsed: float, reused: bool, path: Path):
            self._session_paid[session_key] = (
                receipt, elapsed, path, _file_digest(path))
            return receipt, elapsed, reused, path

        if not self._paid_cache_identity_initialized:
            # The helper hashes the pinned binary and checks the clean Git
            # checkout only once; target-specific fields are overwritten for
            # every later native receipt. A dirty tree never gains cache reuse.
            self._paid_cache_identity_seed = _exact_paid_cache_identity(
                self.binary, actor_level=level, mob_count=mobs,
                target_hp=float(target_hp))
            self._paid_cache_identity_initialized = True
        identity = (
            dict(self._paid_cache_identity_seed, actor_level=level,
                 mob_count=mobs, target_hp=float(target_hp))
            if self._paid_cache_identity_seed is not None else None
        )
        if identity is not None:
            identity = dict(identity, source_sha256=native_sha,
                            prepared_sha256=prepared_digest)
            if rest_policy != (1.0, 1.0):
                # Historical full-rest cache keys remain unchanged.
                # Changed policies cannot borrow the serial paid evidence.
                identity["native_world_rest_thresholds"] = {
                    "health_fraction": rest_policy[0],
                    "mana_fraction": rest_policy[1],
                }
            if world_apl is not None:
                identity["native_world_apl"] = world_apl
            key = _digest(json.dumps(identity, sort_keys=True).encode())
        else:
            key = _digest((native_sha + cid + repr(rest_policy)
                           + repr(policy_key)).encode())
        path = self.artifact_dir / (key + ".native.json")
        meta = self.artifact_dir / (key + ".native.cache.json")
        cached = False
        if not fresh_world and identity is not None and path.is_file() and meta.is_file():
            try:
                record = json.loads(meta.read_text())
                if record == dict(identity, native_raw_receipt_sha256=_file_digest(path)):
                    receipt = json.loads(path.read_text())
                    elapsed, verdict = score_native_chain(
                        receipt, prepared, mob_count=mobs, expected_target_hp=target_hp)
                    if (elapsed is not None
                            and verdict == "MEASURED_NATIVE_FULLY_RECOVERED"
                            and _native_rolling_receipt_verified(receipt, world_apl)):
                        return retain(receipt, elapsed, True, path)
            except (ValueError, TypeError, OSError, KeyError):
                pass
        # Earlier density runs wrote schema-1 records with a whole-commit
        # key. A workflow/cache-helper-only change must not repay those mobs:
        # verify historical source-world Git objects plus the complete native
        # identity, original raw digest and CURRENT strict recovery scorer.
        # Never rewrite the historical receipt or metadata.
        if not fresh_world and identity is not None and world_apl is None:
            for legacy_meta in sorted(self.artifact_dir.glob("*.native.cache.json")):
                if legacy_meta == meta:
                    continue
                try:
                    old_record = json.loads(legacy_meta.read_text())
                    if not _verified_legacy_paid_cache(old_record, identity):
                        continue
                    old_path = legacy_meta.with_name(
                        legacy_meta.name.removesuffix(".native.cache.json")
                        + ".native.json")
                    if _file_digest(old_path) != old_record["native_raw_receipt_sha256"]:
                        continue
                    old_receipt = json.loads(old_path.read_text())
                    old_elapsed, old_verdict = score_native_chain(
                        old_receipt, prepared, mob_count=mobs,
                        expected_target_hp=target_hp)
                    if (old_elapsed is not None
                            and old_verdict == "MEASURED_NATIVE_FULLY_RECOVERED"):
                        return retain(old_receipt, old_elapsed, True, old_path)
                except (ValueError, TypeError, OSError, KeyError):
                    continue
        receipt = self.run_world(
            self.binary, None, target_count=mobs, mob_health=target_hp,
            rng_mode="balanced", recovery_policy="decisions",
            health_threshold=rest_policy[0], mana_threshold=rest_policy[1],
            api_process=self.session.process, prepared_payload=prepared,
            require_native_health_damage=False,
            **({"world_apl": world_apl} if world_apl is not None else {}),
        )
        if not _native_rolling_receipt_verified(receipt, world_apl):
            # A complete native/2D response for an ignored or unproved rolling
            # policy is still original execution evidence. Never cache/rank it
            # as a paid success, and never overwrite an earlier refused run.
            # Keep a distinct extension so the successful .native.json cache
            # and its legacy lookup cannot ingest this observation.
            raw = json.dumps(receipt, indent=2, allow_nan=False) + "\n"
            attempt = 0
            while True:
                suffix = f"-{attempt}" if attempt else ""
                refused_path = self.artifact_dir / (
                    f"{key}-{cid}{suffix}.native.unverified.json")
                try:
                    with refused_path.open("x", encoding="utf-8") as handle:
                        handle.write(raw)
                    break
                except FileExistsError:
                    attempt += 1
            raise UnverifiedNativeWorldReceipt(
                refused_path, _file_digest(refused_path))
        elapsed, verdict = score_native_chain(
            receipt, prepared, mob_count=mobs, expected_target_hp=target_hp)
        if elapsed is None or verdict != "MEASURED_NATIVE_FULLY_RECOVERED":
            raise ValueError("RUST_NATIVE_PAID_SCORE_REFUSED:" + verdict)
        # Keep actual original bytes and pin the digest. An inconsistent old
        # cache entry is never overwritten and never becomes a paid result.
        if not path.exists() and not meta.exists():
            path.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
            if identity is not None:
                meta.write_text(json.dumps(
                    dict(identity, native_raw_receipt_sha256=_file_digest(path)),
                    sort_keys=True, indent=2) + "\n")
        else:
            # An orphaned metadata sidecar must not silently discard a new
            # paid result. Preserve both old metadata and any conflicting
            # raw receipt, including earlier collision fallback files.
            suffix = 0
            while True:
                name = key + "-" + cid + (f"-{suffix}" if suffix else "")
                other = self.artifact_dir / (name + ".native.json")
                try:
                    with other.open("x") as handle:
                        handle.write(json.dumps(
                            receipt, indent=2, allow_nan=False) + "\n")
                    break
                except FileExistsError:
                    suffix += 1
            path = other
        return retain(receipt, elapsed, cached, path)

    def __call__(self, *, level: int, parent: dict | None, mob_count: int,
                 budget: int, rng_mode: str, iterations: int,
                 recover_to_full: bool, search_mode: str = "independent",
                 candidate_hints: list | None = None,
                 fresh_paid_world: bool = False,
                 stop_after_first_paid: bool = False) -> list[dict]:
        if (parent is not None or search_mode != "independent"
                or rng_mode != "balanced" or iterations != 1
                or recover_to_full is not True or not 2 <= mob_count <= 100):
            raise ValueError("NATIVE_API_SUPPORTS_SAMPLED_INDEPENDENT_ROOTS_ONLY")
        if budget < 1:
            return []
        try:
            options = self._options(level)
            talents = options["talents"]
            trees = talents["trees"]
            points = talents["points_available"]
            if (talents["status"] != "ok" or options["level"] != level
                    or len(trees) != 3):
                raise ValueError("RUST_NATIVE_TALENT_OPTIONS_INCOMPLETE")
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            return [{"status": "NATIVE_OPTIONS_REFUSED", "level": level,
                     "native_refusal": str(exc)[-1200:]}]

        seed = self._source(level, None)
        seed_talents = seed["raid"]["parties"][0]["players"][0]["talentsString"]
        proposed_talents = list(_forward_native_talent_hints(
            candidate_hints, level=level, points_available=points,
            trees=trees))
        proposed_talents.extend(_backward_ancestor_variants(
            candidate_hints, points_available=points))
        from itertools import islice
        proposed_talents.extend(islice(
            _variants(seed_talents, trees, points_available=points),
            max(8, budget * 4)))
        native_family_talents = list(dict.fromkeys(proposed_talents))
        # Spend the limited paid budget on Rust-advertised equipment first.
        # The historical L20 seed contains IDs that newer source options
        # no longer offer. Its unmodified forms remain available as explicit
        # native-prepare attempts, but must not crowd out clean competing
        # tree families at the start of a bounded search.
        variants = native_family_talents[:3]
        if seed_talents not in variants:
            variants.append(seed_talents)
        variants.extend(variant for variant in native_family_talents[3:]
                        if variant != seed_talents)
        sources = []
        deferred_unmodified = []
        axis_gear = []
        axis_pets = []
        equipped_anchor = None
        for variant in variants:
            proposal = self._source(level, variant)
            item_variants = list(islice(_source_item_alternatives(
                proposal, options), 28))
            cleaned = item_variants[0] if item_variants else proposal
            if equipped_anchor is None:
                # The original gear can contain legacy IDs absent from Rust
                # options. A sanitized, possibly naked actor must not be the
                # *only* reference used to judge pets, APLs or talent families.
                # Select one Rust-advertised equipped proposal as a common
                # search reference. Only native prepare validates it.
                equipped = item_variants[1] if len(item_variants) > 1 else cleaned
                equipped_anchor = copy.deepcopy(
                    equipped["raid"]["parties"][0]["players"][0]["equipment"])
                axis_gear = [row for row in item_variants[1:]
                             if row["raid"]["parties"][0]["players"][0][
                                 "equipment"] != equipped_anchor][:8]
                axis_pets = list(islice(
                    _source_pet_alternatives(equipped, options), 4))
                if equipped["raid"]["parties"][0]["players"][0][
                        "equipment"] != cleaned["raid"]["parties"][0][
                            "players"][0]["equipment"]:
                    # Preserve the sanitized baseline as an explicit later
                    # candidate, without spending the first paid attempts
                    # on an avoidably under-equipped pet or APL.
                    deferred_unmodified.append(cleaned)
            source = copy.deepcopy(cleaned)
            source["raid"]["parties"][0]["players"][0][
                "equipment"] = copy.deepcopy(equipped_anchor)
            sources.append(source)
            if source != proposal:
                deferred_unmodified.append(proposal)
        # Reserve early native prepare/paid attempts for *each* source axis.
        # Talent-family probes remain, but cannot monopolize a small budget.
        from itertools import zip_longest
        axis_sources = []
        for gear, pet in zip_longest(axis_gear, axis_pets):
            if gear is not None:
                axis_sources.append((gear, "gear"))
            if pet is not None:
                axis_sources.append((pet, "pet"))
        first = sources.pop(0)
        sources = [(first, "talent"), *(
                       [(copy.deepcopy(first), "world_rest_30pct", 0.3, 0.3)]
                       if self.compare_world_rest_30 else []), *(
                       [(copy.deepcopy(first), "world_rolling_50pct",
                         1.0, 1.0, copy.deepcopy(ROLLING_WORLD_APL_50))]
                       if self.compare_world_rolling_50 else []),
                   *axis_sources,
                   *((source, "talent") for source in sources),
                   *((source, "legacy_seed") for source in deferred_unmodified)]
        seen: set[str] = set()
        results: list[dict] = []
        apl_expanded = False
        bootstrap_attempted = False
        target_hp = (float(representative_hp(level))
                     if self.target_hp is None else self.target_hp)
        index = 0
        while index < len(sources) and len(results) < budget:
            candidate = sources[index]
            source, proposal_axis = candidate[:2]
            rest_health, rest_mana = (
                candidate[2:4] if len(candidate) >= 4 else (1.0, 1.0))
            world_apl = candidate[4] if len(candidate) == 5 else None
            index += 1
            identity = json.dumps(
                [source, rest_health, rest_mana, world_apl], sort_keys=True)
            if identity in seen:
                continue
            seen.add(identity)
            cid = f"L{level}_api_{len(results):03d}"
            prepared_ok = False
            try:
                prepared = self.session.request(
                    {"op": "prepare", "request": source, "actor_level": level})
                player = prepared["player"]
                if (player.get("class") != "ClassWarlock"
                        or player.get("level") != level
                        or not isinstance(prepared.get("request_sha256"), str)
                        or len(prepared["request_sha256"]) != 64):
                    raise ValueError("RUST_NATIVE_PREPARED_ACTOR_INVALID")
                prepared_ok = True
                if not apl_expanded:
                    apl_expanded = True
                    # Only prepared-native SpellFlagAPL actions may enter a
                    # changed rotation. The new candidate must prepare again.
                    # The first successfully prepared high-level actor may
                    # still fail to kill a level-scaled hostile mob using the
                    # low-level fixture's rotation. Give its Rust-advertised
                    # executable APL alternatives a bounded *early* chance,
                    # not a tail slot beyond the current paid budget.
                    apl_choices = list(islice(
                        _level_aware_apl_variants(source, prepared, options), 6))
                    # Under the normal budget, first gear and pet attempts
                    # precede APL; with no source axes, APL follows the seed.
                    insert_at = min(len(sources), index + min(2, len(axis_sources)))
                    if self.compare_world_rest_30 or self.compare_world_rolling_50:
                        # The opt-in world-policy challenger gets a bounded
                        # native attempt before APL variants spend the budget.
                        insert_at = max(insert_at, index + 1)
                    sources[insert_at:insert_at] = [
                        (row, "apl") for row in apl_choices]
                receipt, elapsed, cached, raw_path = self._paid(
                    source, prepared, level=level, mobs=mob_count,
                    target_hp=target_hp, cid=cid,
                    fresh_world=fresh_paid_world,
                    health_threshold=rest_health,
                    mana_threshold=rest_mana, world_apl=world_apl)
                terminal = receipt["native_terminal_recovery"]
                actor = source["raid"]["parties"][0]["players"][0]
                cls_options = actor.get("warlock", {}).get(
                    "options", {}).get("classOptions", {})
                results.append({
                    "status": "MEASURED_NATIVE_FULLY_RECOVERED",
                    "candidate_id": cid, "level": level, "mob_count": mob_count,
                    "targets_killed": receipt["world_targets_killed"],
                    "rng_mode": rng_mode, "iterations": iterations,
                    "native_prepared": True,
                    "native_world_ack": receipt["actual_2d_ack"] is True,
                    "source_request_sha256": prepared["request_sha256"],
                    "engine_binary_sha256": self.engine_sha,
                    "native_full_recovery_paid": terminal.get("paid") is True
                        and terminal.get("native_clock_accounted") is True,
                    "recover_to_full": True,
                    "terminal_hp": terminal["health_after"],
                    "terminal_max_hp": terminal["max_health"],
                    "terminal_mana": terminal["mana_after"],
                    "terminal_max_mana": terminal["max_mana"],
                    "elapsed_seconds": elapsed,
                    "terminal_recovery_seconds":
                        (terminal["end_clock_ns"] - terminal["start_clock_ns"]) / 1e9,
                    "talents": actor["talentsString"],
                    "proposal_axis": proposal_axis,
                    "native_world_policy": _native_world_policy(
                        rest_health, rest_mana, world_apl),
                    "native_world_target_hp": receipt["world_target_hp"],
                    "native_named_build": _described_build(source, options),
                    "native_options_coverage": options.get("coverage"),
                    "gear": actor.get("equipment"),
                    "apl": actor.get("rotation"),
                    "pet": cls_options.get("summon"),
                    "native_world_apl": receipt.get("native_world_apl"),
                    "native_world_overlap_verified":
                        receipt.get("native_world_overlap_verified") is True,
                    "native_world_overlap": receipt.get("native_world_overlap"),
                    "native_world_kills": receipt.get("world_kills")
                        if world_apl is not None else None,
                    "native_raw_receipt_file": str(raw_path),
                    "native_raw_receipt_sha256": _file_digest(raw_path),
                    "reused_exact_native_paid_receipt": cached,
                })
                if stop_after_first_paid:
                    break
            except (KeyError, ValueError, TypeError, RuntimeError, AssertionError,
                    OSError, subprocess.SubprocessError) as exc:
                results.append({
                    "status": "NATIVE_API_CANDIDATE_REFUSED",
                    "candidate_id": cid, "level": level,
                    "native_prepared": prepared_ok,
                    "proposal_axis": proposal_axis,
                    "native_world_policy": _native_world_policy(
                        rest_health, rest_mana, world_apl),
                    "native_refusal_code": getattr(exc, "code", None),
                    "native_refusal": str(exc)[-1500:],
                    **({"native_unverified_receipt_file": exc.receipt_path,
                        "native_unverified_receipt_sha256": exc.receipt_sha256}
                       if isinstance(exc, UnverifiedNativeWorldReceipt) else {}),
                })
                # A genuinely refused legacy rotation must not eliminate
                # every registered level-rank candidate. Ask the SAME Rust
                # session to prepare the SAME actor/build without that APL,
                # solely to query its registered SpellFlagAPL repertoire.
                # Bootstrap is not paid, never ranked and never called legal
                # by Python. Each generated candidate is prepared and paid.
                if (not prepared_ok and not apl_expanded
                        and not bootstrap_attempted
                        and isinstance(exc, NativeApiRefusal)
                        and source["raid"]["parties"][0]["players"][0].get(
                            "rotation", {}).get("priorityList")):
                    bootstrap_attempted = True
                    bootstrap = copy.deepcopy(source)
                    bootstrap["raid"]["parties"][0]["players"][0][
                        "rotation"]["priorityList"] = []
                    try:
                        learned = self.session.request({
                            "op": "prepare", "request": bootstrap,
                            "actor_level": level,
                        })
                        player = learned.get("player", {})
                        if (player.get("class") != "ClassWarlock"
                                or player.get("level") != level):
                            raise ValueError("NATIVE_APL_BOOTSTRAP_WRONG_ACTOR")
                        repaired = list(islice(_level_aware_apl_variants(
                            bootstrap, learned, options), 8))
                        if not repaired:
                            raise ValueError("NATIVE_APL_BOOTSTRAP_NO_REGISTERED_ACTIONS")
                        sources[index:index] = [
                            (candidate, "native_apl_bootstrap")
                            for candidate in repaired]
                        apl_expanded = True
                    except (ValueError, TypeError, KeyError, RuntimeError,
                            OSError, subprocess.SubprocessError) as boot_error:
                        if len(results) < budget:
                            results.append({
                                "status": "NATIVE_API_CANDIDATE_REFUSED",
                                "candidate_id": f"L{level}_apl_bootstrap",
                                "level": level, "native_prepared": False,
                                "proposal_axis": "native_apl_bootstrap",
                                "native_refusal_code":
                                    getattr(boot_error, "code", None),
                                "native_refusal": str(boot_error)[-1500:],
                            })
        return results

    def probe_native_level_transition(self, *, from_level: int, to_level: int,
                                      mob_count: int = 2,
                                      candidate_budget: int = 6) -> dict:
        """One NEW paid world, then native state/advance on the SAME Rust process.

        Source-prepared next-level snapshots are never counted as earned XP.
        Historic paid sample caches cannot establish a retained actor; bypass
        them only for this distinct M0.6 continuity probe.
        """
        if (type(from_level) is not int or type(to_level) is not int
                or to_level != from_level + 1 or not 20 <= from_level < 60
                or type(mob_count) is not int or not 2 <= mob_count <= 100
                or type(candidate_budget) is not int or candidate_budget < 1):
            raise ValueError("NATIVE_CONTINUITY_PROBE_ARGUMENTS_INVALID")
        base = {
            "from_level": from_level, "to_level": to_level,
            "mob_count": mob_count, "kind": "retained_actor_native_probe",
            "continuous_leveling_proven": False,
            "historical_sample_used_as_continuity": False,
        }
        # Stop immediately at the first genuinely paid candidate: later
        # prepare operations would erase Rust's last_paid_world observation.
        rows = self(
            level=from_level, parent=None, mob_count=mob_count,
            budget=candidate_budget, rng_mode="balanced", iterations=1,
            recover_to_full=True, fresh_paid_world=True,
            stop_after_first_paid=True,
        )
        paid = next((row for row in rows
                     if row.get("status") == "MEASURED_NATIVE_FULLY_RECOVERED"), None)
        if paid is None:
            return dict(base, status="NATIVE_FIRST_WORLD_UNAVAILABLE",
                        candidate_attempts=rows)
        if paid.get("reused_exact_native_paid_receipt") is not False:
            raise AssertionError("NATIVE_CONTINUITY_PROBE_REUSED_CACHED_WORLD")
        base["paid_first_world"] = paid
        base["candidate_attempts"] = len(rows)
        try:
            state = self.session.request({"op": "state"})
        except (ValueError, RuntimeError) as error:
            return dict(base, status="NATIVE_STATE_UNAVAILABLE",
                        native_refusal=str(error))
        base["native_state_after_world"] = state
        world = state.get("last_paid_world")
        if (state.get("actor_level") != from_level
                or state.get("source_sha256") != paid["source_request_sha256"]
                or not isinstance(world, dict)
                or world.get("source_sha256") != paid["source_request_sha256"]
                or world.get("actor_level") != from_level
                or world.get("world_targets_killed") != mob_count):
            return dict(base, status="NATIVE_PAID_STATE_NOT_RETAINED",
                        native_refusal="same-session paid world identity/ACK missing")
        try:
            advanced = self.session.request({
                "op": "advance", "from_level": from_level,
                "to_level": to_level,
            })
        except (ValueError, RuntimeError) as error:
            return dict(base, status="NATIVE_LEVEL_TRANSITION_UNSUPPORTED",
                        native_advance_refusal_code=getattr(error, "code", None),
                        native_refusal=str(error))
        # An 'ok' on an advance response is not proof of an earned level.
        # Confirm native post-transition state, with actual XP and retained
        # combat runtime, rather than independently preparing L21.
        try:
            next_state = self.session.request({"op": "state"})
        except (ValueError, RuntimeError) as error:
            return dict(base, status="NATIVE_ADVANCE_UNVERIFIED",
                        native_advance_response=advanced,
                        native_refusal=str(error))
        base["native_advance_response"] = advanced
        base["native_state_after_advance"] = next_state
        xp = next_state.get("xp_earned")
        if (next_state.get("actor_level") == to_level
                and next_state.get("retained_combat_runtime") is True
                and next_state.get("retained_xp") is True
                and next_state.get("level_transition_supported") is True
                and type(xp) in (int, float) and xp > 0):
            return dict(base, status="NATIVE_RETAINED_LEVEL_ADVANCED",
                        continuous_leveling_proven=True)
        return dict(base, status="NATIVE_ADVANCE_UNVERIFIED",
                    native_refusal="native XP/retained-runtime progression not proved")
