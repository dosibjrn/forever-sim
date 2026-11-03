"""Single-action P1 behavior executor through the selected MythicSim PreparedV2.

This is an execution adapter, not a spell-acquisition/legality proof and not a
P1 certification. The source action identity selects the request; MythicSim
alone decides whether the request can be prepared and executed.
"""
from __future__ import annotations

import copy
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from .native_p2_rank_probe import (
    NativeP2ProbeError,
    NativeRngMode,
    _compact_prepare_receipt,
    _simulate_prepared,
    prepare_native_request,
)


def _failure(
    status: str,
    stage: str,
    reason: str,
    *,
    action_id: str,
    spell_id: int,
    source_level_hint: int | None,
    engine_sha: str | None,
    **details: Any,
) -> dict[str, object]:
    return {
        "status": status,
        "stage": stage,
        "reason": reason,
        "effect_observed": False,
        "p1_certified": False,
        "accepted_for_p1": False,
        "action_id": action_id,
        "source_spell_id": spell_id,
        "source_level_hint": source_level_hint,
        "native_player_level_modeled": False,
        "native_player_level_note": (
            "The selected PreparedV2 Player schema has no level field. "
            "This is a single-action effect observation, not a level-20 "
            "castability or acquisition verdict."
        ),
        "engine_commit_sha": engine_sha,
        **details,
    }


def _player(request: dict[str, object]) -> dict[str, object]:
    try:
        raid = request["raid"]
        parties = raid["parties"]
        players = parties[0]["players"]
        player = players[0]
    except (KeyError, IndexError, TypeError) as exc:
        raise NativeP2ProbeError("NATIVE_P1_FERAL_CAT_REQUEST_SHAPE_INVALID") from exc
    if (
        not isinstance(player, dict)
        or player.get("class") != "ClassDruid"
        or not isinstance(player.get("feralCatDruid"), dict)
    ):
        raise NativeP2ProbeError("NATIVE_P1_EXPECTED_FERAL_CAT_DRUID_FIXTURE")
    rotation = player.get("rotation")
    if not isinstance(rotation, dict) or rotation.get("type") != "TypeAPL":
        raise NativeP2ProbeError("NATIVE_P1_FERAL_CAT_APL_MISSING")
    return player


def _sim_receipt(result: dict[str, object]) -> dict[str, object]:
    keys = (
        "status", "stage", "reason", "dps", "elapsed_seconds",
        "report_sha256", "prepared_input_sha256", "engine_identity",
        "coverage", "returncode", "stdout_tail", "stderr_tail",
    )
    return {key: result[key] for key in keys if key in result}


def _engine_commit(engine_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(engine_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else None


def run_native_p1_action(
    *,
    binary: str | Path | None,
    engine_root: str | Path,
    spell_id: int,
    action_id: str,
    source_level_hint: int | None,
    engine_sha: str | None = None,
    iterations: int = 100,
    seed: int = 647003,
    timeout_seconds: float = 180.0,
) -> dict[str, object]:
    """Observe one source-selected Druid Claw effect using native PreparedV2.

    The positive and control requests share the exact same selected-engine
    fixture and simulation options. The sole request difference is the APL:
    one native castSpell action versus an empty priority list. No local
    spellbook, acquisition, rank, or GameIR legality check is performed.
    """
    if isinstance(spell_id, bool) or not isinstance(spell_id, int) or spell_id <= 0:
        return _failure(
            "ERROR", "request", "NATIVE_P1_SOURCE_SPELL_ID_INVALID",
            action_id=str(action_id), spell_id=0, source_level_hint=source_level_hint,
            engine_sha=engine_sha,
        )
    if not isinstance(action_id, str) or not action_id.strip():
        return _failure(
            "ERROR", "request", "NATIVE_P1_SOURCE_ACTION_ID_INVALID",
            action_id="", spell_id=spell_id, source_level_hint=source_level_hint,
            engine_sha=engine_sha,
        )
    if (
        isinstance(iterations, bool) or not isinstance(iterations, int)
        or iterations < 1 or isinstance(seed, bool) or not isinstance(seed, int)
        or not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0
    ):
        return _failure(
            "ERROR", "request", "NATIVE_P1_SIM_OPTIONS_INVALID",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=engine_sha,
        )

    if binary is None or not str(binary).strip():
        return _failure(
            "BLOCKED", "prepare", "SELECTED_RUST_BINARY_NOT_CONFIGURED",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=engine_sha,
        )
    binary_path = Path(binary).expanduser()
    engine_path = Path(engine_root).expanduser()
    try:
        resolved_binary = binary_path.resolve(strict=True)
        resolved_engine = engine_path.resolve(strict=True)
    except OSError as exc:
        return _failure(
            "BLOCKED", "prepare", f"SELECTED_RUST_PATH_UNAVAILABLE:{type(exc).__name__}",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=engine_sha,
        )
    if not resolved_binary.is_file() or not resolved_engine.is_dir():
        return _failure(
            "BLOCKED", "prepare", "SELECTED_RUST_BINARY_OR_ENGINE_ROOT_MISSING",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=engine_sha,
        )
    try:
        resolved_binary.relative_to(resolved_engine)
    except ValueError:
        return _failure(
            "BLOCKED", "prepare", "BINARY_NOT_FROM_SELECTED_ENGINE_SUBMODULE",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=engine_sha,
        )

    fixture_path = resolved_engine / "tests/classes/druid/prepare/cat.request.json"
    if not fixture_path.is_file():
        return _failure(
            "BLOCKED", "prepare", "SELECTED_RUST_FERAL_CAT_REQUEST_FIXTURE_MISSING",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=engine_sha,
        )
    try:
        template = json.loads(fixture_path.read_text(encoding="utf-8"))
        if not isinstance(template, dict):
            raise ValueError("fixture root is not an object")
        player = _player(template)
        options = template.get("simOptions")
        if not isinstance(options, dict):
            raise NativeP2ProbeError("NATIVE_P1_SIM_OPTIONS_MISSING")
        positive = copy.deepcopy(template)
        positive_player = _player(positive)
        positive_options = positive["simOptions"]
        positive_options["iterations"] = iterations
        positive_options["randomSeed"] = str(seed)
        positive_options["debugFirstIteration"] = False
        positive_player["rotation"]["priorityList"] = [
            {"action": {"castSpell": {"spellId": {"spellId": spell_id}}}}
        ]
        control = copy.deepcopy(positive)
        control_player = _player(control)
        control_player["rotation"]["priorityList"] = []
        expected_control = copy.deepcopy(positive)
        _player(expected_control)["rotation"]["priorityList"] = []
        if control != expected_control:
            raise NativeP2ProbeError("NATIVE_P1_CONTROL_CHANGED_MORE_THAN_APL")
        # Do not synthesize a player level: the selected PreparedV2 contract
        # does not carry one, and this adapter must not invent level legality.
        if "level" in positive_player:
            raise NativeP2ProbeError("NATIVE_P1_FIXTURE_UNEXPECTED_PLAYER_LEVEL_FIELD")
    except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError, NativeP2ProbeError) as exc:
        return _failure(
            "ERROR", "request", f"NATIVE_P1_REQUEST_BUILD_FAILED:{type(exc).__name__}:{exc}",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=engine_sha,
        )

    selected_sha = engine_sha or _engine_commit(resolved_engine)
    deadline = time.monotonic() + timeout_seconds
    scenarios = (
        f"p1-{action_id}-{spell_id}-with-action",
        f"p1-{action_id}-{spell_id}-no-action-control",
    )
    try:
        with_action = prepare_native_request(
            binary=resolved_binary, request=positive,
            scenario=scenarios[0], deadline=deadline,
        )
    except (NativeP2ProbeError, OSError, ValueError, TypeError) as exc:
        return _failure(
            "ERROR", "prepare_with_action",
            f"NATIVE_P1_PREPARE_ADAPTER_ERROR:{type(exc).__name__}:{exc}",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
        )
    if with_action.get("status") != "PREPARED":
        return _failure(
            str(with_action.get("status") or "ERROR"), "prepare_with_action",
            str(with_action.get("reason") or "NATIVE_P1_PREPARE_WITH_ACTION_NOT_PREPARED"),
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
            with_action_prepare=_compact_prepare_receipt(with_action),
        )

    try:
        no_action = prepare_native_request(
            binary=resolved_binary, request=control,
            scenario=scenarios[1], deadline=deadline,
        )
    except (NativeP2ProbeError, OSError, ValueError, TypeError) as exc:
        return _failure(
            "ERROR", "prepare_no_action",
            f"NATIVE_P1_CONTROL_PREPARE_ADAPTER_ERROR:{type(exc).__name__}:{exc}",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
            with_action_prepare=_compact_prepare_receipt(with_action),
        )
    if no_action.get("status") != "PREPARED":
        return _failure(
            str(no_action.get("status") or "ERROR"), "prepare_no_action",
            str(no_action.get("reason") or "NATIVE_P1_NO_ACTION_CONTROL_NOT_PREPARED"),
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
            with_action_prepare=_compact_prepare_receipt(with_action),
            no_action_prepare=_compact_prepare_receipt(no_action),
        )

    if (
        not with_action.get("request_sha256")
        or not no_action.get("request_sha256")
        or with_action.get("request_sha256") == no_action.get("request_sha256")
        or with_action.get("engine_identity") != no_action.get("engine_identity")
    ):
        return _failure(
            "ERROR", "prepare_pair", "NATIVE_P1_PREPARED_REQUEST_IDENTITY_MISMATCH",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
            with_action_prepare=_compact_prepare_receipt(with_action),
            no_action_prepare=_compact_prepare_receipt(no_action),
        )

    try:
        with_action_sim = _simulate_prepared(
            binary_path=resolved_binary, prepared=with_action["prepared"],
            rng_mode=NativeRngMode.BALANCED, iterations=iterations,
            seed=seed, deadline=deadline,
        )
    except (NativeP2ProbeError, OSError, ValueError, TypeError) as exc:
        return _failure(
            "ERROR", "sim_with_action",
            f"NATIVE_P1_SIM_ADAPTER_ERROR:{type(exc).__name__}:{exc}",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
            with_action_prepare=_compact_prepare_receipt(with_action),
            no_action_prepare=_compact_prepare_receipt(no_action),
        )
    if with_action_sim.get("status") != "EXECUTED":
        return _failure(
            str(with_action_sim.get("status") or "ERROR"), "sim_with_action",
            str(with_action_sim.get("reason") or "NATIVE_P1_WITH_ACTION_SIM_NOT_EXECUTED"),
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
            with_action_prepare=_compact_prepare_receipt(with_action),
            no_action_prepare=_compact_prepare_receipt(no_action),
            with_action_sim=_sim_receipt(with_action_sim),
        )

    try:
        no_action_sim = _simulate_prepared(
            binary_path=resolved_binary, prepared=no_action["prepared"],
            rng_mode=NativeRngMode.BALANCED, iterations=iterations,
            seed=seed, deadline=deadline,
        )
    except (NativeP2ProbeError, OSError, ValueError, TypeError) as exc:
        return _failure(
            "ERROR", "sim_no_action",
            f"NATIVE_P1_CONTROL_SIM_ADAPTER_ERROR:{type(exc).__name__}:{exc}",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
            with_action_prepare=_compact_prepare_receipt(with_action),
            no_action_prepare=_compact_prepare_receipt(no_action),
            with_action_sim=_sim_receipt(with_action_sim),
        )
    if no_action_sim.get("status") != "EXECUTED":
        return _failure(
            str(no_action_sim.get("status") or "ERROR"), "sim_no_action",
            str(no_action_sim.get("reason") or "NATIVE_P1_NO_ACTION_CONTROL_NOT_EXECUTED"),
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
            with_action_prepare=_compact_prepare_receipt(with_action),
            no_action_prepare=_compact_prepare_receipt(no_action),
            with_action_sim=_sim_receipt(with_action_sim),
            no_action_sim=_sim_receipt(no_action_sim),
        )

    if with_action_sim.get("engine_identity") != no_action_sim.get("engine_identity"):
        return _failure(
            "ERROR", "sim_pair", "NATIVE_P1_SIM_ENGINE_IDENTITY_MISMATCH",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
            with_action_prepare=_compact_prepare_receipt(with_action),
            no_action_prepare=_compact_prepare_receipt(no_action),
            with_action_sim=_sim_receipt(with_action_sim),
            no_action_sim=_sim_receipt(no_action_sim),
        )

    baseline_dps = float(with_action_sim["dps"])
    control_dps = float(no_action_sim["dps"])
    delta_dps = baseline_dps - control_dps
    if not all(math.isfinite(value) for value in (baseline_dps, control_dps, delta_dps)):
        return _failure(
            "ERROR", "sim_pair", "NATIVE_P1_EFFECT_DELTA_NONFINITE",
            action_id=action_id, spell_id=spell_id,
            source_level_hint=source_level_hint, engine_sha=selected_sha,
        )
    observed = delta_dps > 1e-9
    return {
        "status": "NATIVE_EFFECT_OBSERVED" if observed else "NATIVE_EFFECT_NOT_OBSERVED",
        "stage": "native_prepared_v2",
        "effect_observed": observed,
        "p1_certified": False,
        "accepted_for_p1": False,
        "action_id": action_id,
        "source_spell_id": spell_id,
        "source_level_hint": source_level_hint,
        "native_player_level_modeled": False,
        "native_player_level_note": (
            "The selected PreparedV2 Player schema has no level field. "
            "This is a single-action effect observation, not a level-20 "
            "castability or acquisition verdict."
        ),
        "native_authority": "MythicSim Rust PreparedV2",
        "control_kind": "same_request_no_action_apl",
        "rng_mode": NativeRngMode.BALANCED.value,
        "iterations": iterations,
        "seed": seed,
        "engine_commit_sha": selected_sha,
        "engine_identity": with_action.get("engine_identity"),
        "sim_engine_identity": with_action_sim.get("engine_identity"),
        "baseline_dps": baseline_dps,
        "control_dps": control_dps,
        "delta_dps": delta_dps,
        "with_action_prepare": _compact_prepare_receipt(with_action),
        "no_action_prepare": _compact_prepare_receipt(no_action),
        "with_action_sim": _sim_receipt(with_action_sim),
        "no_action_sim": _sim_receipt(no_action_sim),
    }
