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
