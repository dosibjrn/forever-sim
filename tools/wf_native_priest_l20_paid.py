"""Paid native Priest L20 whole-build entry for the active P4/P5 search.

The request is an explicit source/native build, not one reconstructed from
Forever GameIR. MythicSim decides whether it can prepare and execute it.
This transport does NOT certify the paid native/2D 100-mob screen.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


def _native_scorer():
    # The selected native subprocess adapter lives in the existing integration.
    integration = Path(__file__).resolve().parents[1] / "integrations" / "mythicsim-rust"
    if str(integration) not in sys.path:
        sys.path.insert(0, str(integration))
    from native_joint_two_class import native_score_request
    return native_score_request


def _source_cast_identifiers(player: dict) -> set[str]:
    """Preserve exact native ActionID identity; never infer game legality."""
    rotation = player.get("rotation")
    actions = rotation.get("priorityList") if isinstance(rotation, dict) else None
    if not isinstance(actions, list):
        return set()
    ids = set()
    for entry in actions:
        action = entry.get("action") if isinstance(entry, dict) else None
        cast = action.get("castSpell") if isinstance(action, dict) else None
        identity = cast.get("spellId") if isinstance(cast, dict) else None
        if isinstance(identity, dict) and identity:
            ids.add(json.dumps(identity, sort_keys=True, separators=(",", ":")))
    return ids


def score_source_priest_l20(binary: str | Path, request_file: str | Path, *,
                            score_request=None, budget_s: float = 6.0) -> dict:
    """Pay for one *real* selected-Rust complete request, with no gate credit.

    Callers must supply an existing, inspectable level-20 Priest source request.
    Never silently rewrite a level-60 actor, talents or APL into a L20 build.
    """
    try:
        request = json.loads(Path(request_file).read_text(encoding="utf-8"))
        player = request["raid"]["parties"][0]["players"][0]
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise ValueError("P4_P5_NATIVE_SOURCE_REQUEST_UNREADABLE") from exc
    if (not isinstance(player, dict) or player.get("class") != "ClassPriest"
            or type(player.get("level")) is not int or player["level"] != 20
            or not isinstance(request.get("simOptions"), dict)):
        raise ValueError("P4_P5_NATIVE_PRIEST_L20_SOURCE_REQUEST_REQUIRED")
    source_ids = _source_cast_identifiers(player)
    if not source_ids:
        raise ValueError("P4_P5_NATIVE_SOURCE_APL_CAST_REQUIRED")
    scorer = score_request if score_request is not None else _native_scorer()
    record, _raw = scorer(
        Path(binary), request, iterations=1, seed=42, rng_mode="balanced",
        deadline=time.monotonic() + budget_s, objective="DPS",
    )
    # Only exact native action IDs found in the supplied source APL count.
    # In particular, tagged procs must not masquerade as source casts.
    casts = {}
    for receipt in record.get("native_action_cast_receipts") or ():
        if not isinstance(receipt, dict) or not isinstance(receipt.get("id"), dict):
            continue
        count = receipt.get("casts")
        if type(count) is not int or count <= 0:
            continue
        identity = json.dumps(receipt["id"], sort_keys=True, separators=(",", ":"))
        if identity in source_ids:
            casts[identity] = casts.get(identity, 0) + count
    return {
        "native_paid_whole_builds": 1,
        "native_request_sha256": record["effective_request_sha256"],
        "native_score": record["score"],
        "native_score_objective": "DPS",
        "native_source_action_casts": sum(casts.values()),
        "native_source_action_ids_cast": len(casts),
        "native_source_action_id_count": len(source_ids),
        "native_rng_mode": record["rng_mode"],
        "native_actor_requested_level": 20,
        # This is a single native fight; the independent paid 2D/100-mob
        # source-action screen has deliberately NOT been run.
        "native_2d_screen_complete": False,
    }



def couple_source_priest_l20_world(binary: str | Path,
                                  request_file: str | Path, *, world_run=None) -> dict:
    """Execute an actual single native↔gsim-2D ACKed fight for a paid L20 build.

    This reuses the existing live-world production integration. A successful
    single fight is NOT a continuous kill/recovery/100-mob P4/P5 screen.
    """
    from hashlib import sha256
    from math import isfinite

    path = Path(request_file)
    source = json.loads(path.read_text(encoding="utf-8"))
    try:
        actor = source["raid"]["parties"][0]["players"][0]
        target = source["encounter"]["targets"]
        distance = actor["distanceFromTarget"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("PRIEST_L20_WORLD_SOURCE_REQUEST_INCOMPLETE") from exc
    if (actor.get("class") != "ClassPriest" or type(actor.get("level")) is not int
            or actor["level"] != 20 or not isinstance(target, list)
            or len(target) != 1 or target[0].get("level") != 20
            or type(distance) not in (int, float) or not isfinite(distance)
            or distance <= 0):
        raise ValueError("PRIEST_L20_WORLD_ACTOR_TARGET_OR_DISTANCE_INVALID")
    if world_run is None:
        integration = Path(__file__).resolve().parents[1] / "integrations" / "mythicsim-rust"
        if str(integration) not in sys.path:
            sys.path.insert(0, str(integration))
        from live_world_probe import run as world_run
    proof = world_run(
        Path(binary), path, distance=float(distance), iterations=1,
        rng_mode="balanced", expected_target_level=20,
    )
    # The existing live-world runner checks native PID, protobuf identity,
    # causal world ACKs, applied damage, and native↔world DPS parity.
    if (proof.get("source_request_raw_sha256") != sha256(path.read_bytes()).hexdigest()
            or proof.get("iterations_done") != 1
            or type(proof.get("native_world_ticks")) is not int
            or proof["native_world_ticks"] < 1
            or type(proof.get("native_damage_events")) is not int
            or proof["native_damage_events"] < 1):
        raise RuntimeError("PRIEST_L20_LIVE_NATIVE_WORLD_RECEIPT_INCOMPLETE")
    source_events = proof.get("source_action_events_before")
    if not isinstance(source_events, dict) or not source_events:
        raise RuntimeError("PRIEST_L20_LIVE_WORLD_SOURCE_ACTION_EVENTS_MISSING")
    # Preserve the native bridge's event identifiers verbatim. These are NOT
    # invented Python spell IDs or proof of all source APL ActionID casts.
    return {
        "native_2d_fight_ack_complete": True,
        "native_2d_world_ticks": proof["native_world_ticks"],
        "native_2d_world_damage_events": proof["native_damage_events"],
        "native_2d_source_action_events": source_events,
        "native_2d_source_request_proto_sha256": proof["source_request_proto_sha256"],
        "native_2d_source_request_raw_sha256": proof["source_request_raw_sha256"],
        "native_2d_world_target_killed": proof.get("world_target_lethal_fights") == 1,
        "native_2d_screen_complete": False,
    }


def couple_source_priest_l20_persistent_world(binary: str | Path,
                                             request_file: str | Path, *,
                                             target_count: int = 2,
                                             world_run=None) -> dict:
    """Execute consecutive sourced targets on ONE native actor/2D ACK timeline.

    This is a real native-world-pulls integration, not independent reset
    fights. It deliberately does not claim paid recovery or P4/P5 completion.
    """
    from tempfile import TemporaryDirectory
    from tools.wf_gsim_go_live_range_probe import source_target_health_from_request

    if type(target_count) is not int or not 2 <= target_count <= 100:
        raise ValueError("PRIEST_L20_PERSISTENT_TARGET_COUNT_INVALID")
    path = Path(request_file)
    source = json.loads(path.read_text(encoding="utf-8"))
    try:
        player = source["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("PRIEST_L20_PERSISTENT_SOURCE_REQUEST_INCOMPLETE") from exc
    if (not isinstance(player, dict) or player.get("class") != "ClassPriest"
            or type(player.get("level")) is not int or player["level"] != 20):
        raise ValueError("PRIEST_L20_PERSISTENT_SOURCE_ACTOR_INVALID")
    health = source_target_health_from_request(
        path.read_bytes(), expected_target_level=20)
    if world_run is None:
        integration = Path(__file__).resolve().parents[1] / "integrations" / "mythicsim-rust"
        if str(integration) not in sys.path:
            sys.path.insert(0, str(integration))
        from live_two_world_pulls import run as world_run
    with TemporaryDirectory(prefix="priest-l20-persistent-native-") as folder:
        prepared = Path(folder) / "prepared.json"
        subprocess.run(
            [str(Path(binary).resolve()), "prepare", "--request",
             str(path.resolve()), "--outfile", str(prepared)],
            check=True, capture_output=True, text=True, timeout=25)
        native = json.loads(prepared.read_text(encoding="utf-8"))
        actor = native.get("player", {})
        if (not isinstance(actor, dict) or actor.get("class") != "ClassPriest"
                or type(actor.get("level")) is not int or actor["level"] != 20
                or not isinstance(native.get("request_sha256"), str)
                or len(native["request_sha256"]) != 64):
            raise RuntimeError("PRIEST_L20_PERSISTENT_NATIVE_PREPARED_ACTOR_INVALID")
        proof = world_run(
            Path(binary), prepared, mob_health=health, target_count=target_count,
            rng_mode="balanced")
    if (not isinstance(proof, dict)
            or proof.get("continuous_native_actor") is not True
            or proof.get("actual_2d_ack") is not True
            or proof.get("world_targets_killed") != target_count
            or len(proof.get("native_windows", ())) != target_count
            or proof.get("paid_recovery") is not False):
        raise RuntimeError("PRIEST_L20_PERSISTENT_NATIVE_WORLD_RECEIPT_INCOMPLETE")
    return {
        "native_2d_persistent_world_targets_killed": target_count,
        "native_2d_persistent_world_ticks": proof["world_ticks"],
        "native_2d_persistent_actor_verified": True,
        "native_2d_persistent_world_ack_verified": True,
        "native_2d_persistent_paid_recovery": False,
        "native_2d_screen_complete": False,
    }


def score_source_priest_l20_candidates(binary: str | Path,
                                      source_directory: str | Path, *,
                                      score_request=None, world_screen=None,
                                      persistent_world=None,
                                      budget_s: float = 6.0,
                                      max_paid_builds: int = 4) -> dict:
    """Pay a bounded cold frontier of explicit source/native build requests.

    Each JSON supplies its *own* gear, talents and APL. Forever never derives
    their Warcraft legality, copies L60 data, or reuses another winner.
    MythicSim evaluates each distinct whole build; no native fight becomes
    an invented continuous 2D/world gate screen.
    """
    from hashlib import sha256

    folder = Path(source_directory)
    if not folder.is_dir():
        raise ValueError("P4_P5_NATIVE_SOURCE_CANDIDATE_DIRECTORY_REQUIRED")
    if not (0 < budget_s <= 30 and 1 <= max_paid_builds <= 16):
        raise ValueError("P4_P5_NATIVE_CANDIDATE_BUDGET_INVALID")
    paths = sorted(folder.glob("*.json"))
    if not paths:
        raise ValueError("P4_P5_NATIVE_SOURCE_CANDIDATES_EMPTY")

    deadline = time.monotonic() + budget_s
    seen = set()
    rows = []
    comparable_encounter = None
    for path in paths:
        if len(rows) >= max_paid_builds or time.monotonic() >= deadline:
            break
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
            encounter = request["encounter"]
            player = request["raid"]["parties"][0]["players"][0]
            # A native-backed candidate must stay inside the same supplied
            # world scenario; comparing unlike mobs is not optimization.
            if not isinstance(encounter, dict) or not isinstance(player, dict):
                raise ValueError("P4_P5_NATIVE_SOURCE_CANDIDATE_INVALID")
            if comparable_encounter is None:
                comparable_encounter = encounter
            elif encounter != comparable_encounter:
                raise ValueError("P4_P5_NATIVE_CANDIDATE_ENCOUNTER_MISMATCH")
            candidate_key = sha256(json.dumps(
                request, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            if candidate_key in seen:
                continue
            seen.add(candidate_key)
            receipt = score_source_priest_l20(
                binary, path, score_request=score_request,
                budget_s=max(0.001, deadline - time.monotonic()))
            rows.append({"candidate": path.name, "source_request_sha256":
                         candidate_key, "status": "NATIVE_PAID",
                         **receipt})
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            # Explicit native refusal is a measured candidate failure, never
            # a successful paid screen or a reason to try a Python model.
            rows.append({"candidate": path.name, "status": "NATIVE_REFUSED",
                         "reason": str(exc)[-400:]})

    paid = [row for row in rows if row["status"] == "NATIVE_PAID"]
    # The selected paid candidate, not a synthetic world-only request, reaches
    # the existing live Rust↔2D ACK loop once per bounded diagnostic.
    # A strong native-only score cannot prove that the same build works in
    # the ACKed 2D world. Try the next genuinely paid source candidate if the
    # first live request fails or remains nonlethal, within the native-paid frontier budget.
    # Neither result may count as a persistent 100-mob paid screen.
    live_attempted = 0
    live_verified = 0
    live_killed = 0
    live_kill_candidate = None
    live_kill_request_sha256 = None
    persistent_attempted = 0
    persistent_verified = 0
    persistent_targets_killed = 0
    if world_screen is not None:
        from tempfile import TemporaryDirectory
        ranked = sorted(
            (row for row in paid if row["native_source_action_casts"] > 0),
            key=lambda row: row["native_score"], reverse=True)
        # Native DPS alone is not a 2D kill criterion: every already-paid
        # source build in this bounded frontier can be genuinely world-tested.
        # Stop at the first ACKed lethal world result, never at a nonlethal ACK.
        for candidate in ranked[:max_paid_builds]:
            live_attempted += 1
            try:
                # Replay the exact normalized request paid by the native scorer.
                # The original source JSON and candidate directory are read-only:
                # never leak the synthesized replay into later cold frontiers.
                effective = json.loads(
                    (folder / candidate["candidate"]).read_text(encoding="utf-8"))
                effective["simOptions"]["iterations"] = 1
                effective["simOptions"]["randomSeed"] = "42"
                effective_sha = sha256(json.dumps(
                    effective, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")).hexdigest()
                if effective_sha != candidate["native_request_sha256"]:
                    raise RuntimeError(
                        "PRIEST_L20_PAID_WORLD_EFFECTIVE_REQUEST_IDENTITY_MISMATCH")
                # The live runner checks its raw request identity, prepared
                # native protobuf identity, real world ticks and damage ACKs.
                with TemporaryDirectory(prefix="priest-l20-live-world-") as directory:
                    execution_request = Path(directory) / "source.json"
                    execution_request.write_text(
                        json.dumps(effective, sort_keys=True), encoding="utf-8")
                    live = world_screen(binary, execution_request)
                    if (isinstance(live, dict)
                            and live.get("native_2d_fight_ack_complete") is True
                            and live.get("native_2d_world_target_killed") is True
                            and persistent_world is not None):
                        persistent_attempted += 1
                        try:
                            retained = persistent_world(binary, execution_request)
                            if (not isinstance(retained, dict)
                                    or retained.get("native_2d_persistent_actor_verified") is not True
                                    or retained.get("native_2d_persistent_world_ack_verified") is not True
                                    or type(retained.get("native_2d_persistent_world_targets_killed")) is not int
                                    or retained["native_2d_persistent_world_targets_killed"] < 2
                                    or retained.get("native_2d_screen_complete") is not False):
                                raise RuntimeError("PRIEST_L20_PERSISTENT_WORLD_RECEIPT_INVALID")
                            candidate["native_2d_persistent_world"] = retained
                            persistent_verified += 1
                            persistent_targets_killed = retained[
                                "native_2d_persistent_world_targets_killed"]
                        except (OSError, ValueError, RuntimeError, TimeoutError,
                                AssertionError, KeyError, TypeError,
                                subprocess.SubprocessError) as exc:
                            candidate["native_2d_persistent_error"] = str(exc)[-500:]
                if (not isinstance(live, dict)
                        or live.get("native_2d_fight_ack_complete") is not True):
                    raise RuntimeError("PRIEST_L20_PAID_WORLD_ACK_NOT_VERIFIED")
                candidate["native_2d_fight"] = live
                live_verified += 1
                # ACK alone can leave the sourced target alive. Retain that
                # honest receipt and try the next paid whole build for a real
                # lethal world ACK, without treating either as a 100-mob screen.
                if live.get("native_2d_world_target_killed") is True:
                    live_killed += 1
                    live_kill_candidate = candidate["candidate"]
                    live_kill_request_sha256 = candidate["native_request_sha256"]
                    break
            except (OSError, ValueError, RuntimeError, TimeoutError,
                    AssertionError, KeyError, TypeError,
                    subprocess.SubprocessError) as exc:
                candidate["native_2d_fight_error"] = str(exc)[-500:]
    return {
        "native_candidate_requests_attempted": len(rows),
        "native_paid_whole_builds": len(paid),
        "native_source_action_casts": sum(
            row["native_source_action_casts"] for row in paid),
        "native_source_action_ids_cast": max(
            (row["native_source_action_ids_cast"] for row in paid),
            default=0),
        "native_candidate_receipts": rows,
        "native_2d_live_ack_attempted": live_attempted,
        "native_2d_live_ack_verified": live_verified,
        "native_2d_live_world_kills": live_killed,
        "native_2d_live_kill_candidate": live_kill_candidate,
        "native_2d_live_kill_request_sha256": live_kill_request_sha256,
        "native_2d_persistent_attempted": persistent_attempted,
        "native_2d_persistent_verified": persistent_verified,
        "native_2d_persistent_targets_killed": persistent_targets_killed,
        "native_2d_screen_complete": False,
        "native_candidate_search_budget_s": budget_s,
    }


def score_native_priest_l20_item_candidates(binary: str | Path,
                                          request_file: str | Path,
                                          native_item_options: list[dict], *,
                                          score_request=None, world_screen=None,
                                          persistent_world=None,
                                          budget_s: float = 6.0,
                                          max_paid_builds: int = 4) -> dict:
    """Score progressive source-native multi-slot whole-build requests.

    The source retains its actor, talent, APL and world. Each candidate adds
    one more item from a *different native-reported slot*, so the real paid
    frontier can evaluate a useful equipped build rather than isolated
    one-item builds. Only MythicSim decides whether that complete request is
    legal/executable; Forever supplies no game stat or equipment rules.
    """
    import copy
    from tempfile import TemporaryDirectory

    try:
        source = json.loads(Path(request_file).read_text(encoding="utf-8"))
        actor = source["raid"]["parties"][0]["players"][0]
        items = actor["equipment"]["items"]
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("P4_P5_NATIVE_SOURCE_REQUEST_UNREADABLE") from exc
    if (not isinstance(actor, dict) or actor.get("class") != "ClassPriest"
            or type(actor.get("level")) is not int or actor["level"] != 20):
        raise ValueError("P4_P5_NATIVE_PRIEST_L20_SOURCE_REQUEST_REQUIRED")
    if items != []:
        raise ValueError("P4_P5_NATIVE_ITEM_PROPOSALS_REQUIRE_EMPTY_SOURCE_GEAR")
    if not isinstance(native_item_options, list):
        raise ValueError("P4_P5_NATIVE_ITEM_PROPOSALS_INVALID")

    # Propose a few different source-returned slots, not a duplicate list of
    # the same item type. Native Rust still has the only equip decision.
    proposals = []
    used_slots = set()
    for option in native_item_options:
        if not isinstance(option, dict):
            continue
        item_id, slot = option.get("item_id"), option.get("slot")
        if (type(item_id) is not int or item_id <= 0
                or not isinstance(slot, str) or not slot
                or slot in used_slots):
            continue
        used_slots.add(slot)
        proposals.append((item_id, slot))
        if len(proposals) >= max_paid_builds - 1:
            break

    with TemporaryDirectory(prefix="native-priest-l20-options-") as directory:
        folder = Path(directory)
        (folder / "000-source-baseline.json").write_text(
            json.dumps(source), encoding="utf-8")
        for index, (item_id, _slot) in enumerate(proposals, start=1):
            candidate = copy.deepcopy(source)
            # Progressive whole-build proposals retain every earlier
            # native-sourced distinct-slot item. These are mere requests:
            # Rust alone resolves equip slots, legality and actual effects.
            candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"] = [
                {"id": selected_id} for selected_id, _ in proposals[:index]]
            (folder / f"{index:03d}-native-item-{item_id}.json").write_text(
                json.dumps(candidate), encoding="utf-8")
        receipt = score_source_priest_l20_candidates(
            binary, folder, score_request=score_request,
            world_screen=world_screen, persistent_world=persistent_world,
            budget_s=budget_s, max_paid_builds=max_paid_builds)
    return {
        **receipt,
        "native_item_options_proposed": len(proposals),
        "native_item_option_source_slots_proposed": [slot for _, slot in proposals],
        "native_candidate_provenance": "MYTHICSIM_ITEM_OPTIONS_AND_SOURCE_L20_REQUEST",
    }
