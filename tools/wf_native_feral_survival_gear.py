"""One genuine native-supplied Feral L60 gear-slot survival probe over 100 kills.

Do not infer equipment legality in Forever: Rust item-options proposes items,
Rust prepare accepts/refuses a complete build, and the native/world actor is
the only source of the paid 100-mob score and survival outcome. This is an
increment toward P4-P6, not a 30/300-second gate acceptance run.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.game.native_p3_item_options import query_native_p3_item_options
from tools.wf_native_feral_l60_world import FERAL_SOURCE, run_feral_l60_world


# Positions in the RaidSimRequest equipment wire array, not item eligibility.
# The pinned MythicSim item-options endpoint owns which items fit each slot.
_SURVIVAL_SLOT_INDEX = {"chest": 4, "legs": 8, "head": 0}


def _native_survival_profile(item: dict) -> tuple[float, float]:
    """Only native-returned stat observations used to diversify paid probes."""
    stats = item["stats"]
    return (float(stats.get("Stamina", 0.0)),
            float(stats.get("Armor", 0.0)))


def _native_stamina(item: dict) -> float:
    """Search preference from native-supplied stats, NOT an eligibility check."""
    stats = item["stats"]
    return float(stats.get("Stamina", 0.0))


def search_feral_native_gear_survival(
    binary: str | Path,
    source_request: str | Path = FERAL_SOURCE,
    *, recovery_seconds: int = 24,
    max_candidates: int = 2,
    slot: str = "chest",
    native_options=None,
    world_run=None,
    prepare_run=None,
) -> dict:
    if slot not in _SURVIVAL_SLOT_INDEX:
        raise ValueError("FERAL_L60_NATIVE_GEAR_SLOT_UNSUPPORTED")
    if type(max_candidates) is not int or not 1 <= max_candidates <= 4:
        raise ValueError("FERAL_L60_NATIVE_GEAR_CANDIDATE_BUDGET_INVALID")
    if type(recovery_seconds) is not int or not 1 <= recovery_seconds <= 120:
        raise ValueError("FERAL_L60_WORLD_RECOVERY_SECONDS_INVALID")
    binary = Path(binary).resolve()
    source_request = Path(source_request).resolve()
    source = json.loads(source_request.read_bytes())
    try:
        equipped = source["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        original = equipped[_SURVIVAL_SLOT_INDEX[slot]]["id"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("FERAL_L60_SOURCE_EQUIPMENT_INCOMPLETE") from exc
    if type(original) is not int or len(equipped) != 16 and len(equipped) != 17:
        raise ValueError("FERAL_L60_SOURCE_EQUIPMENT_INCOMPLETE")

    # Query the selected pinned engine rather than a Forever/SQLite catalogue.
    # The same native engine must subsequently prepare and execute the build.
    native_options = native_options or query_native_p3_item_options
    options = native_options(binary, "druid", 60, spec="unrestricted", slot=slot)
    # The native transport already checks each returned item shape and source
    # eligibility. Rank native choices for survival; Rust still judges full
    # build validity (enchants, talents, combined equipment and APL).
    ranked = sorted(
        (item for item in options["items"] if item["item_id"] != original),
        key=lambda item: (*_native_survival_profile(item), -item["item_id"]),
        reverse=True,
    )
    # The previous two chest IDs exposed identical native Stamina and the
    # same lethal window. This bounded *stat-axis probe* spends no second
    # 100-mob run on an identical native Stamina/Armor profile. Other effects
    # remain candidates for the eventual full optimizer, not ruled illegal.
    candidates = []
    seen_profiles = set()
    for item in ranked:
        profile = _native_survival_profile(item)
        if profile in seen_profiles:
            continue
        seen_profiles.add(profile)
        candidates.append(item)
        if len(candidates) >= max_candidates:
            break
    if not candidates:
        raise RuntimeError(f"FERAL_L60_NATIVE_{slot.upper()}_OPTIONS_NO_ALTERNATIVE")

    attempts = []
    best = None
    with TemporaryDirectory(prefix=f"native-feral-{slot}-") as tmp:
        path = Path(tmp) / "candidate.json"
        for item in candidates:
            candidate = copy.deepcopy(source)
            candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][_SURVIVAL_SLOT_INDEX[slot]] = {
                "id": item["item_id"],
            }
            path.write_text(json.dumps(candidate, sort_keys=True), encoding="utf-8")
            attempt = {
                f"{slot}_item_id": item["item_id"],
                "gear_slot": slot,
                "native_stamina": _native_stamina(item),
                "native_armor": _native_survival_profile(item)[1],
                f"source_{slot}_item_id": original,
                "recovery_seconds": recovery_seconds,
            }
            try:
                result = run_feral_l60_world(
                    binary, path, target_count=100,
                    recovery_seconds=recovery_seconds,
                    world_run=world_run, prepare_run=prepare_run,
                )
            except AssertionError as exc:
                detail = str(exc)
                prefix = "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index="
                if not detail.startswith(prefix):
                    raise
                first = detail[len(prefix):].split(":", 1)[0]
                if not first.isdecimal() or not 0 <= int(first) < 100:
                    raise
                attempt.update(
                    status="native_death", first_native_death_index=int(first),
                    native_failure=detail,
                )
            except RuntimeError as exc:
                if not str(exc).startswith("FERAL_L60_NATIVE_PREPARE_REFUSED:"):
                    raise
                attempt.update(status="native_refused", native_failure=str(exc))
            else:
                paid = result["objective_100_mobs"]
                if paid is None:
                    raise AssertionError("FERAL_L60_NATIVE_GEAR_NO_PAID_OBJECTIVE")
                attempt.update(
                    status="survived",
                    mean_seconds_per_mob=paid["mean_seconds_per_mob"],
                    minimum_native_actor_health=paid["minimum_native_actor_health"],
                    native_prepared_request_sha256=result["native_prepared_request_sha256"],
                )
                if best is None or attempt["mean_seconds_per_mob"] < best["mean_seconds_per_mob"]:
                    best = attempt
            attempts.append(attempt)
    if best is None:
        raise RuntimeError(
            f"FERAL_L60_NO_SURVIVING_NATIVE_{slot.upper()}_CANDIDATE:"
            + json.dumps(attempts, sort_keys=True))
    return {
        "best_surviving_candidate": best,
        "native_paid_gear_attempts": attempts,
        "source": "selected_native_item_options_and_prepare",
        "searched_gear_slot": slot,
        "p4_p5_p6_certified": False,
    }


def search_feral_native_chest_survival(*args, **kwargs) -> dict:
    """Keep the existing chest caller while the independent legs lane runs."""
    return search_feral_native_gear_survival(*args, slot="chest", **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--source-request", type=Path, default=FERAL_SOURCE)
    parser.add_argument("--recovery-seconds", type=int, default=24)
    parser.add_argument("--max-candidates", type=int, default=2)
    parser.add_argument("--slot", choices=sorted(_SURVIVAL_SLOT_INDEX), default="legs")
    args = parser.parse_args()
    result = search_feral_native_gear_survival(
        args.binary, args.source_request,
        recovery_seconds=args.recovery_seconds,
        max_candidates=args.max_candidates, slot=args.slot,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
