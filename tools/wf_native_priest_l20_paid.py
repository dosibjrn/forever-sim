"""Paid native Priest L20 whole-build entry for the active P4/P5 search.

The request is an explicit source/native build, not one reconstructed from
Forever GameIR. MythicSim decides whether it can prepare and execute it.
This transport does NOT certify the paid native/2D 100-mob screen.
"""
from __future__ import annotations

import json
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


def score_source_priest_l20_candidates(binary: str | Path,
                                      source_directory: str | Path, *,
                                      score_request=None,
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
    return {
        "native_candidate_requests_attempted": len(rows),
        "native_paid_whole_builds": len(paid),
        "native_source_action_casts": sum(
            row["native_source_action_casts"] for row in paid),
        "native_source_action_ids_cast": max(
            (row["native_source_action_ids_cast"] for row in paid),
            default=0),
        "native_candidate_receipts": rows,
        "native_2d_screen_complete": False,
        "native_candidate_search_budget_s": budget_s,
    }


def score_native_priest_l20_item_candidates(binary: str | Path,
                                          request_file: str | Path,
                                          native_item_options: list[dict], *,
                                          score_request=None,
                                          budget_s: float = 6.0,
                                          max_paid_builds: int = 4) -> dict:
    """Score native item-options proposals as actual whole-build requests.

    The level-20 request supplies the unchanged actor, talent, APL and world.
    MythicSim's item-options supplies each item ID, and the native prepare
    endpoint alone determines which equipment slot / eligibility applies.
    No Python item model, gear stats, or legality filter is involved.
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
            # Item specs are a native request transport only. The selected
            # engine resolves the item's real slot and accepts/refuses it.
            candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"] = [
                {"id": item_id}]
            (folder / f"{index:03d}-native-item-{item_id}.json").write_text(
                json.dumps(candidate), encoding="utf-8")
        receipt = score_source_priest_l20_candidates(
            binary, folder, score_request=score_request, budget_s=budget_s,
            max_paid_builds=max_paid_builds)
    return {
        **receipt,
        "native_item_options_proposed": len(proposals),
        "native_item_option_source_slots_proposed": [slot for _, slot in proposals],
        "native_candidate_provenance": "MYTHICSIM_ITEM_OPTIONS_AND_SOURCE_L20_REQUEST",
    }
