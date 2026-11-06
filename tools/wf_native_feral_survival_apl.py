"""Native-scored Feral APL order candidates for real 100-mob survival.

Only reorder existing source APL actions. MythicSim prepares and executes every
candidate; Forever never interprets ability IDs, legality, damage or healing.
Two-target and 50-target native screens rank changed policies for bounded
100-target attempts. A real 100-target native death can trigger the next
independently screened policy; no failed run is scored. This is not the cold
300s P4-P6 acceptance search.
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
from tools.wf_native_feral_l60_world import FERAL_SOURCE, run_feral_l60_world


def _source_apl_candidates(source: dict) -> list[tuple[str, dict]]:
    try:
        actions = source["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("FERAL_NATIVE_APL_SOURCE_INCOMPLETE") from exc
    if not isinstance(actions, list) or len(actions) < 4 or any(
        not isinstance(action, dict) or "action" not in action for action in actions
    ):
        raise ValueError("FERAL_NATIVE_APL_SOURCE_INCOMPLETE")

    # Move existing late priority actions into the earlier half. These are
    # mechanical priority permutations, not spell-name or game-rule claims.
    # Native preparation and paid combat decide whether a policy is useful.
    candidates = [("source", copy.deepcopy(source))]
    for label, from_index in (("advance_last", -1), ("advance_penultimate", -2)):
        request = copy.deepcopy(source)
        priority = request["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
        selected_action = priority.pop(from_index)
        priority.insert(len(priority) // 2, selected_action)
        if priority != actions:
            candidates.append((label, request))
    return candidates


def search_feral_native_apl_survival(
    binary: str | Path, source_request: str | Path = FERAL_SOURCE,
    *, recovery_seconds: int = 24, prepare_run=None, world_run=None,
) -> dict:
    if type(recovery_seconds) is not int or not 1 <= recovery_seconds <= 120:
        raise ValueError("FERAL_L60_WORLD_RECOVERY_SECONDS_INVALID")
    path = Path(source_request).resolve()
    source = json.loads(path.read_bytes())
    candidates = _source_apl_candidates(source)
    attempts: list[dict] = []
    viable: list[tuple[str, dict, dict]] = []
    with TemporaryDirectory(prefix="feral-native-apl-") as folder:
        temporary = Path(folder) / "candidate.json"
        for label, request in candidates:
            temporary.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
            attempt: dict = {"policy": label, "screen_targets": 2}
            try:
                result = run_feral_l60_world(
                    binary, temporary, target_count=2,
                    recovery_seconds=recovery_seconds,
                    prepare_run=prepare_run, world_run=world_run,
                )
            except (AssertionError, RuntimeError) as exc:
                # Native refusal/death is a rejected candidate, not a score.
                detail = str(exc)
                if not (
                    detail.startswith("FERAL_L60_NATIVE_PREPARE_REFUSED:")
                    or detail.startswith("RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:")
                ):
                    raise
                attempt.update(status="native_refused_or_dead", native_failure=detail)
            else:
                proof = result["native_world"]
                elapsed = proof.get("world_elapsed_seconds")
                health = proof.get("minimum_native_actor_health")
                if (
                    type(elapsed) not in (float, int) or not math.isfinite(elapsed)
                    or elapsed <= 0 or type(health) not in (float, int)
                    or not math.isfinite(health) or health <= 0
                ):
                    raise RuntimeError("FERAL_NATIVE_APL_TWO_TARGET_SCORE_MISSING")
                attempt.update(
                    status="native_screen_survived",
                    two_target_elapsed_seconds=float(elapsed),
                    minimum_native_actor_health=float(health),
                    native_prepared_request_sha256=result["native_prepared_request_sha256"],
                )
                viable.append((label, request, attempt))
            attempts.append(attempt)
        # The two-target result is a real native paid observation, not a
        # survival gate: a policy with lower early HP can still sustain 50/100
        # consecutive kills, and a dead source policy cannot veto a surviving
        # native-accepted replacement. Rank alternatives to spend less compute,
        # but decide feasibility only from actual retained-actor world runs.
        changed = [(label, request, attempt) for label, request, attempt in viable
                   if label != "source"]
        if not changed:
            raise RuntimeError(
                "FERAL_NATIVE_APL_NO_EXECUTABLE_TWO_TARGET_ALTERNATIVE:"
                + json.dumps(attempts, sort_keys=True)
            )
        # A two-target winner need not survive the persistent world. Screen
        # genuinely changed, native-scored APLs in descending two-target order,
        # falling back after real 50-target deaths. No Warcraft-rule pre-veto.
        ranked_changed = sorted(
            changed,
            key=lambda triple: (
                triple[2]["minimum_native_actor_health"],
                -triple[2]["two_target_elapsed_seconds"],
            ),
            reverse=True,
        )
        recovery_screens: list[dict] = []
        hundred_failures: list[dict] = []
        for label, selected, selected_screen in ranked_changed:
            temporary.write_text(json.dumps(selected, sort_keys=True), encoding="utf-8")
            surviving_recovery: list[dict] = []
            for seconds in dict.fromkeys((recovery_seconds, 120)):
                attempt = {"policy": label, "recovery_seconds": seconds, "screen_targets": 50}
                try:
                    screen = run_feral_l60_world(
                        binary, temporary, target_count=50,
                        recovery_seconds=seconds,
                        prepare_run=prepare_run, world_run=world_run,
                    )
                except AssertionError as exc:
                    detail = str(exc)
                    if not detail.startswith("RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:"):
                        raise
                    attempt.update(status="native_actor_died", native_failure=detail)
                else:
                    proof = screen["native_world"]
                    elapsed = proof.get("world_elapsed_seconds")
                    health = proof.get("minimum_native_actor_health")
                    if (
                        type(elapsed) not in (float, int) or not math.isfinite(elapsed)
                        or elapsed <= 0 or type(health) not in (float, int)
                        or not math.isfinite(health) or health <= 0
                    ):
                        raise RuntimeError("FERAL_NATIVE_APL_RECOVERY_SCREEN_SCORE_MISSING")
                    attempt.update(
                        status="native_screen_survived",
                        fifty_target_elapsed_seconds=float(elapsed),
                        minimum_native_actor_health=float(health),
                        native_prepared_request_sha256=screen["native_prepared_request_sha256"],
                    )
                    surviving_recovery.append(attempt)
                recovery_screens.append(attempt)
            if not surviving_recovery:
                continue
            # Fifty kills are necessary screening evidence, not a promise
            # that the same actor survives the remaining fifty. If the first
            # source-native policy dies at 100, try the next *independently*
            # screened changed APL rather than discarding its genuine chance.
            best_recovery = max(surviving_recovery, key=lambda attempt: (
                attempt["minimum_native_actor_health"],
                -attempt["fifty_target_elapsed_seconds"],
            ))
            chosen_recovery_seconds = best_recovery["recovery_seconds"]
            temporary.write_text(json.dumps(selected, sort_keys=True), encoding="utf-8")
            try:
                paid = run_feral_l60_world(
                    binary, temporary, target_count=100,
                    recovery_seconds=chosen_recovery_seconds,
                    prepare_run=prepare_run, world_run=world_run,
                )
            except AssertionError as exc:
                if not str(exc).startswith("RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:"):
                    raise
                hundred_failures.append({
                    "selected_policy": label,
                    "selected_recovery_seconds": chosen_recovery_seconds,
                    "native_failure": str(exc),
                    "native_prepared_request_sha256":
                        best_recovery["native_prepared_request_sha256"],
                })
                continue
            objective = paid["objective_100_mobs"]
            if objective is None:
                raise RuntimeError("FERAL_NATIVE_APL_100_TARGET_OBJECTIVE_UNPAID")
            return {
                "selected_policy": label,
                "selected_native_two_target_screen": selected_screen,
                "two_target_screens": attempts,
                "recovery_screens": recovery_screens,
                "failed_native_100_target_attempts": hundred_failures,
                "selected_recovery_seconds": chosen_recovery_seconds,
                "native_paid_100_target_objective": objective,
                "native_prepared_request_sha256": paid["native_prepared_request_sha256"],
                "source_request_raw_sha256": paid["source_request_raw_sha256"],
                "p4_p5_p6_certified": False,
            }
        if hundred_failures:
            raise RuntimeError(
                "FERAL_NATIVE_APL_100_TARGET_NATIVE_DEATH:"
                + json.dumps({
                    "two_target_screens": attempts,
                    "recovery_screens": recovery_screens,
                    "failed_native_100_target_attempts": hundred_failures,
                }, sort_keys=True)
            )
        raise RuntimeError(
            "FERAL_NATIVE_APL_NO_SURVIVING_RECOVERY_SCREEN:"
            + json.dumps(recovery_screens, sort_keys=True)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source-request", type=Path, default=FERAL_SOURCE)
    parser.add_argument("--recovery-seconds", type=int, default=24)
    args = parser.parse_args()
    result = search_feral_native_apl_survival(
        args.binary, args.source_request, recovery_seconds=args.recovery_seconds,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
