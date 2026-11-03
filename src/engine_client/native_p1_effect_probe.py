"""Direct P1 single-action probe through the selected Rust PreparedV2 executor.

The positive and control requests differ only in the APL priorityList:
one selected castSpell versus no castSpell. MythicSim owns spell/rank
availability and all combat mechanics; this client does not consult a
Python spellbook, trainer ledger, source legality table, or GameIR action
implementation before sending the request.

A positive native effect delta is sufficient for a non-spatial direct effect.
Callers explicitly require the live gsim 2D world bridge only when the tested
effect depends on world-owned geometry, movement or crowd control. This is
diagnostic evidence only, never a formal P1 PASS.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time

from src.engine_client.native_p2_rank_probe import (
    NativeP2ProbeError,
    NativeRngMode,
    _simulate_prepared,
    prepare_native_request,
)

ROOT = Path(__file__).resolve().parents[2]
ENGINE_ROOT = ROOT / "integrations" / "mythicsim-rust" / "engine"
INTEGRATION_ROOT = ROOT / "integrations" / "mythicsim-rust"


def _player(request: dict) -> dict:
    try:
        return request["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("NATIVE_P1_REQUEST_PLAYER_PATH_MISSING") from exc


def _cast_spell_id(row: dict) -> int | None:
    if not isinstance(row, dict):
        return None
    action = row.get("action")
    cast = action.get("castSpell") if isinstance(action, dict) else None
    spell = cast.get("spellId") if isinstance(cast, dict) else None
    if isinstance(spell, dict):
        spell = spell.get("spellId")
    return spell if type(spell) is int and spell > 0 else None


def _minimal_cast_spell_row(spell_id: int) -> dict:
    """Serialize a candidate spell ID; native prepare owns acceptance/refusal."""
    return {"action": {"castSpell": {"spellId": {"spellId": spell_id}}}}


def native_single_action_pair(
    request: dict, spell_id: int, *, action_row: dict | None = None
) -> tuple[dict, dict]:
    """Build one-action and no-action requests without changing scenario data.

    Reuse the matching source APL row when present. If the request has no row
    for this candidate, serialize a minimal castSpell wire request instead;
    MythicSim alone decides whether the spell/rank is valid or supported.
    Callers may supply an explicit action_row for a real conditional trigger.
    The control has an empty priorityList. All other request fields are equal.
    """
    if type(spell_id) is not int or spell_id <= 0:
        raise ValueError("NATIVE_P1_SELECTED_SPELL_ID_INVALID")
    original = copy.deepcopy(request)
    player = _player(original)
    rotation = player.get("rotation")
    if not isinstance(rotation, dict) or not isinstance(rotation.get("priorityList"), list):
        raise ValueError("NATIVE_P1_APL_PRIORITY_LIST_MISSING")

    # Do not silently leave a second action channel active in the control.
    for key, value in rotation.items():
        if key != "priorityList" and isinstance(value, list) and value:
            raise ValueError("NATIVE_P1_UNCONTROLLED_ROTATION_CHANNEL:" + key)
    for key in ("majorCooldowns", "cooldowns", "itemSwap"):
        if player.get(key):
            raise ValueError("NATIVE_P1_UNCONTROLLED_PLAYER_ACTION_CHANNEL:" + key)

    matches = [
        row for row in rotation["priorityList"]
        if _cast_spell_id(row) == spell_id
    ]
    if action_row is not None:
        if _cast_spell_id(action_row) != spell_id:
            raise ValueError("NATIVE_P1_ACTION_ROW_SPELL_ID_MISMATCH:" + str(spell_id))
        selected_row = copy.deepcopy(action_row)
    elif len(matches) == 1:
        selected_row = copy.deepcopy(matches[0])
    elif not matches:
        # A source candidate does not need to already exist in a Python-built
        # APL before native gets to decide its status.
        selected_row = _minimal_cast_spell_row(spell_id)
    else:
        raise ValueError("NATIVE_P1_SELECTED_SPELL_AMBIGUOUS_IN_APL:" + str(spell_id))

    positive = copy.deepcopy(original)
    control = copy.deepcopy(original)
    _player(positive)["rotation"]["priorityList"] = [selected_row]
    _player(control)["rotation"]["priorityList"] = []

    positive_normalized = copy.deepcopy(positive)
    control_normalized = copy.deepcopy(control)
    _player(positive_normalized)["rotation"]["priorityList"] = ["SELECTED_ACTION"]
    _player(control_normalized)["rotation"]["priorityList"] = ["SELECTED_ACTION"]
    if positive_normalized != control_normalized:
        raise ValueError("NATIVE_P1_PAIR_CHANGED_NON_ACTION_REQUEST_FIELDS")
    if len(_player(positive)["rotation"]["priorityList"]) != 1:
        raise ValueError("NATIVE_P1_POSITIVE_ACTION_COUNT_INVALID")
    if _player(control)["rotation"]["priorityList"]:
        raise ValueError("NATIVE_P1_CONTROL_IS_NOT_NO_ACTION")
    return positive, control


def _sha256_json(value: dict) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()



def native_prepared_action_inventory(prepare_receipt: dict) -> dict[str, object]:
    """Expose the selected engine's prepared spell/action records without interpretation.

    This is a native PreparedV2 inventory for the exact prepared build, not a
    source denominator, Python legality decision, role classifier or P1 proof.
    Preserve every native spell record (including passive/unaddressable entries)
    and the separate native major-cooldown channel; do not rank-filter or sort.
    """
    unavailable = {
        "status": "UNAVAILABLE",
        "reason": "NATIVE_PREPARED_ACTION_INVENTORY_MISSING",
        "p1_certified": False,
    }
    if not isinstance(prepare_receipt, dict) or prepare_receipt.get("status") != "PREPARED":
        return {**unavailable, "reason": "NATIVE_PREPARE_RECEIPT_NOT_PREPARED"}
    prepared = prepare_receipt.get("prepared")
    if not isinstance(prepared, dict):
        return {**unavailable, "reason": "NATIVE_PREPARED_PAYLOAD_MISSING"}
    player = prepared.get("player")
    if not isinstance(player, dict):
        return {**unavailable, "reason": "NATIVE_PREPARED_PLAYER_MISSING"}
    spells = player.get("spells")
    if not isinstance(spells, list) or any(not isinstance(spell, dict) for spell in spells):
        return {**unavailable, "reason": "NATIVE_PREPARED_SPELLBOOK_MISSING"}
    major_cooldowns = player.get("major_cooldowns", [])
    if major_cooldowns is None:
        major_cooldowns = []
    if not isinstance(major_cooldowns, list):
        return {**unavailable, "reason": "NATIVE_PREPARED_MAJOR_COOLDOWNS_INVALID"}
    return {
        "status": "AVAILABLE",
        "engine_identity": prepare_receipt.get("engine_identity"),
        "prepared_sha256": prepare_receipt.get("prepared_sha256"),
        "player_class": player.get("class"),
        "player_level": player.get("level"),
        "talents_string": player.get("talents_string"),
        "talents": copy.deepcopy(player.get("talents")),
        "spell_count": len(spells),
        "spell_records_with_action_id": sum(
            spell.get("action_id") is not None for spell in spells
        ),
        "major_cooldown_count": len(major_cooldowns),
        "spells": copy.deepcopy(spells),
        "major_cooldowns": copy.deepcopy(major_cooldowns),
        "p1_certified": False,
    }


def _compact(receipt: dict) -> dict:
    keys = (
        "status", "stage", "reason", "engine_identity", "request_sha256",
        "prepared_sha256", "elapsed_seconds", "refusal", "returncode",
        "stdout_tail", "stderr_tail", "dps", "iterations_done",
        "zero_dps_due_to_absent_avg", "report_sha256", "prepared_input_sha256",
    )
    return {key: receipt[key] for key in keys if key in receipt}


def _run_world_bridge(
    binary_path: Path,
    prepared: dict,
    *,
    target_count: int,
    mob_health: float | None,
) -> dict:
    if str(INTEGRATION_ROOT) not in sys.path:
        sys.path.insert(0, str(INTEGRATION_ROOT))
    import live_two_world_pulls

    with tempfile.TemporaryDirectory(prefix="forever-p1-native-world-") as directory:
        prepared_path = Path(directory) / "prepared.json"
        prepared_path.write_text(
            json.dumps(prepared, sort_keys=True, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
        return live_two_world_pulls.run(
            binary_path,
            prepared_path,
            mob_health=mob_health,
            target_count=target_count,
        )


def run_native_p1_direct_effect_probe(
    *,
    binary: str | Path,
    request: dict,
    spell_id: int,
    engine_root: str | Path = ENGINE_ROOT,
    timeout_seconds: float = 120.0,
    iterations: int = 10,
    seed: int = 647003,
    target_count: int = 2,
    world_mob_health: float | None = 1200.0,
    action_row: dict | None = None,
    requires_2d_world: bool = True,
) -> dict[str, object]:
    """Run a native action/control pair, with 2D only for world-dependent effects.

    Set requires_2d_world=False only when the caller has established that
    the tested effect does not depend on world geometry, movement or CC.
    """
    if isinstance(iterations, bool) or type(iterations) is not int or iterations < 1:
        raise ValueError("NATIVE_P1_ITERATIONS_INVALID")
    if isinstance(seed, bool) or type(seed) is not int:
        raise ValueError("NATIVE_P1_SEED_INVALID")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) \
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("NATIVE_P1_TIMEOUT_INVALID")
    if type(requires_2d_world) is not bool:
        raise ValueError("NATIVE_P1_WORLD_REQUIREMENT_INVALID")
    if requires_2d_world:
        if type(target_count) is not int or not 2 <= target_count <= 100:
            raise ValueError("NATIVE_P1_WORLD_TARGET_COUNT_INVALID")
        if world_mob_health is not None and (
            isinstance(world_mob_health, bool)
            or not isinstance(world_mob_health, (int, float))
            or not math.isfinite(world_mob_health)
            or world_mob_health <= 0
        ):
            raise ValueError("NATIVE_P1_WORLD_MOB_HEALTH_INVALID")

    binary_path = Path(binary)
    root = Path(engine_root)
    if not binary_path.is_file():
        return {
            "status": "BLOCKED", "stage": "prepare",
            "reason": "SELECTED_RUST_BINARY_MISSING",
            "native_executed": False, "effect_observed": False,
            "p1_certified": False,
        }
    try:
        binary_path.resolve().relative_to(root.resolve())
    except ValueError:
        return {
            "status": "BLOCKED", "stage": "prepare",
            "reason": "BINARY_NOT_FROM_SELECTED_ENGINE_ROOT",
            "native_executed": False, "effect_observed": False,
            "p1_certified": False,
        }

    try:
        positive_request, control_request = native_single_action_pair(
            request, spell_id, action_row=action_row
        )
        for payload in (positive_request, control_request):
            options = payload.get("simOptions")
            if not isinstance(options, dict):
                raise ValueError("NATIVE_P1_SIM_OPTIONS_MISSING")
            options["iterations"] = iterations
            options["randomSeed"] = str(seed)
            options["debugFirstIteration"] = False
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "status": "INVALID", "stage": "request",
            "reason": str(exc), "native_executed": False,
            "effect_observed": False, "p1_certified": False,
        }

    deadline = time.monotonic() + float(timeout_seconds)
    player_class = str(_player(request).get("class") or "unknown").strip()
    if player_class.startswith("Class"):
        player_class = player_class[5:]
    scenario_class = player_class.lower().replace(" ", "-") or "unknown"
    scenario = f"p1-{scenario_class}-single-action-{spell_id}"
    try:
        positive_prepare = prepare_native_request(
            binary=binary_path,
            request=positive_request,
            scenario=scenario + "-with-action",
            deadline=deadline,
        )
        # A native refusal of the selected action is already conclusive.
        # Do not run an unrelated control prepare after that refusal.
        if positive_prepare.get("status") != "PREPARED":
            return {
                "status": positive_prepare.get("status", "ERROR"),
                "stage": positive_prepare.get("stage", "prepare"),
                "reason": positive_prepare.get(
                    "reason", "NATIVE_P1_POSITIVE_PREPARE_NOT_READY"
                ),
                "positive_prepare": _compact(positive_prepare),
                "native_executed": False, "effect_observed": False,
                "p1_certified": False,
            }
        control_prepare = prepare_native_request(
            binary=binary_path,
            request=control_request,
            scenario=scenario + "-no-action",
            deadline=deadline,
        )
    except (NativeP2ProbeError, OSError, ValueError, TypeError) as exc:
        return {
            "status": "ERROR", "stage": "prepare",
            "reason": f"NATIVE_P1_PREPARE_ADAPTER_FAILED:{type(exc).__name__}:{exc}",
            "native_executed": False, "effect_observed": False,
            "p1_certified": False,
        }

    if positive_prepare.get("status") != "PREPARED" or control_prepare.get("status") != "PREPARED":
        failed = (
            positive_prepare if positive_prepare.get("status") != "PREPARED"
            else control_prepare
        )
        return {
            "status": failed.get("status", "ERROR"),
            "stage": failed.get("stage", "prepare"),
            "reason": failed.get("reason", "NATIVE_P1_PREPARE_PAIR_NOT_READY"),
            "positive_prepare": _compact(positive_prepare),
            "control_prepare": _compact(control_prepare),
            "native_executed": False, "effect_observed": False,
            "p1_certified": False,
        }

    if (
        positive_prepare.get("engine_identity") != control_prepare.get("engine_identity")
        or not positive_prepare.get("request_sha256")
        or not control_prepare.get("request_sha256")
        or positive_prepare.get("request_sha256") == control_prepare.get("request_sha256")
    ):
        return {
            "status": "ERROR", "stage": "prepare",
            "reason": "NATIVE_P1_PREPARED_PAIR_IDENTITY_OR_HASH_INVALID",
            "positive_prepare": _compact(positive_prepare),
            "control_prepare": _compact(control_prepare),
            "native_executed": False, "effect_observed": False,
            "p1_certified": False,
        }

    try:
        positive_sim = _simulate_prepared(
            binary_path=binary_path,
            prepared=positive_prepare["prepared"],
            rng_mode=NativeRngMode.BALANCED,
            iterations=iterations,
            seed=seed,
            deadline=deadline,
        )
        # A native refusal of the selected action is final. Do not spend a
        # second native execution on an unrelated no-action control, or
        # replace the selected action's refusal with a control failure.
        if positive_sim.get("status") != "EXECUTED":
            return {
                "status": positive_sim.get("status", "ERROR"),
                "stage": positive_sim.get("stage", "sim"),
                "reason": positive_sim.get("reason", "NATIVE_P1_POSITIVE_SIM_NOT_EXECUTED"),
                "positive_prepare": _compact(positive_prepare),
                "control_prepare": _compact(control_prepare),
                "positive_sim": _compact(positive_sim),
                "native_executed": False, "effect_observed": False,
                "p1_certified": False,
            }
        # A no-action control can produce a valid native report with no
        # dps.avg. Accept zero only when the native report confirms all fights
        # completed; the positive action and all P2 callers stay strict.
        control_sim = _simulate_prepared(
            binary_path=binary_path,
            prepared=control_prepare["prepared"],
            rng_mode=NativeRngMode.BALANCED,
            iterations=iterations,
            seed=seed,
            deadline=deadline,
            allow_zero_dps_if_avg_absent=True,
        )
    except Exception as exc:
        return {
            "status": "ERROR", "stage": "sim",
            "reason": f"NATIVE_P1_SIM_ADAPTER_FAILED:{type(exc).__name__}:{exc}",
            "positive_prepare": _compact(positive_prepare),
            "control_prepare": _compact(control_prepare),
            "native_executed": False, "effect_observed": False,
            "p1_certified": False,
        }
    if control_sim.get("status") != "EXECUTED":
        return {
            "status": control_sim.get("status", "ERROR"),
            "stage": control_sim.get("stage", "sim"),
            "reason": control_sim.get("reason", "NATIVE_P1_CONTROL_SIM_NOT_EXECUTED"),
            "positive_prepare": _compact(positive_prepare),
            "control_prepare": _compact(control_prepare),
            "positive_sim": _compact(positive_sim),
            "control_sim": _compact(control_sim),
            "native_executed": False, "effect_observed": False,
            "p1_certified": False,
        }

    try:
        positive_dps = float(positive_sim["dps"])
        control_dps = float(control_sim["dps"])
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "status": "ERROR", "stage": "sim",
            "reason": f"NATIVE_P1_DPS_MISSING_OR_INVALID:{type(exc).__name__}:{exc}",
            "positive_sim": _compact(positive_sim),
            "control_sim": _compact(control_sim),
            "native_executed": True, "effect_observed": False,
            "p1_certified": False,
        }
    if not math.isfinite(positive_dps) or not math.isfinite(control_dps):
        return {
            "status": "ERROR", "stage": "sim",
            "reason": "NATIVE_P1_DPS_NONFINITE",
            "positive_sim": _compact(positive_sim),
            "control_sim": _compact(control_sim),
            "native_executed": True, "effect_observed": False,
            "p1_certified": False,
        }
    dps_delta = positive_dps - control_dps
    common = {
        "spell_id": spell_id,
        "positive_action_count": 1,
        "control_action_count": 0,
        "positive_request_sha256": _sha256_json(positive_request),
        "control_request_sha256": _sha256_json(control_request),
        "positive_prepare": _compact(positive_prepare),
        "control_prepare": _compact(control_prepare),
        "native_prepared_action_inventory": native_prepared_action_inventory(positive_prepare),
        "positive_sim": _compact(positive_sim),
        "control_sim": _compact(control_sim),
        "dps_with_action": positive_dps,
        "dps_without_action": control_dps,
        "dps_delta": dps_delta,
        "engine_identity": positive_prepare["engine_identity"],
        "native_executed": True,
        "world_bridge_required": requires_2d_world,
        "p1_certified": False,
    }
    if dps_delta <= 0:
        return {
            **common,
            "status": "NO_DIRECT_EFFECT_OBSERVED",
            "effect_observed": False,
            "proof_kind": "NATIVE_DIRECT_EFFECT",
            "executor": "msim-rust",
            "controlled_behavior_assertion_passed": False,
        }

    if not requires_2d_world:
        return {
            **common,
            "status": "NATIVE_DIRECT_EFFECT_VERIFIED",
            "effect_observed": True,
            "proof_kind": "NATIVE_DIRECT_EFFECT",
            "executor": "msim-rust",
            "controlled_behavior_assertion_passed": True,
            "world_bridge_status": "NOT_REQUIRED_NONSPATIAL_EFFECT",
            "observable_effects": {
                "dps_with_action": positive_dps,
                "dps_without_action": control_dps,
                "dps_delta": dps_delta,
            },
        }

    try:
        world = _run_world_bridge(
            binary_path,
            positive_prepare["prepared"],
            target_count=target_count,
            mob_health=world_mob_health,
        )
    except Exception as exc:
        return {
            **common,
            "status": "ERROR", "stage": "world",
            "reason": f"NATIVE_P1_WORLD_BRIDGE_FAILED:{type(exc).__name__}:{exc}",
            "effect_observed": False,
            "proof_kind": "NATIVE_DIRECT_EFFECT",
            "executor": "msim-rust",
            "controlled_behavior_assertion_passed": False,
        }

    world_ok = (
        isinstance(world, dict)
        and world.get("actual_2d_ack") is True
        and world.get("continuous_native_actor") is True
        and type(world.get("world_targets_killed")) is int
        and world["world_targets_killed"] == target_count
        and isinstance(world.get("world_kills"), list)
        and len(world["world_kills"]) == target_count
        and isinstance(world.get("native_windows"), list)
        and len(world["native_windows"]) == target_count
        and type(world.get("native_damage_events")) is int
        and world["native_damage_events"] >= target_count
        and world.get("checkpoint_certified") is False
    )
    if not world_ok:
        return {
            **common,
            "status": "ERROR", "stage": "world",
            "reason": "NATIVE_P1_WORLD_BRIDGE_CAUSALITY_NOT_CONFIRMED",
            "world_bridge": world,
            "effect_observed": False,
            "proof_kind": "NATIVE_DIRECT_EFFECT",
            "executor": "msim-rust",
            "controlled_behavior_assertion_passed": False,
        }

    observable = {
        "dps_with_action": positive_dps,
        "dps_without_action": control_dps,
        "dps_delta": dps_delta,
        "world_targets_requested": target_count,
        "world_targets_killed": world["world_targets_killed"],
        "native_damage_events": world["native_damage_events"],
        "actual_2d_ack": world["actual_2d_ack"],
        "world_elapsed_seconds": world.get("world_elapsed_seconds"),
    }
    return {
        **common,
        "status": "NATIVE_DIRECT_BEHAVIOR_VERIFIED",
        "effect_observed": True,
        "proof_kind": "NATIVE_DIRECT_EFFECT",
        "executor": "msim-rust",
        "controlled_behavior_assertion_passed": True,
        "observable_effects": observable,
        "world_bridge": world,
    }
