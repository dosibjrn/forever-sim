#!/usr/bin/env python3
"""Cheap *predictive* screening of native three-world-mob Rust receipts.

This module is not a simulator: no HP, mana, pet, spell, regeneration or
cooldown state is modified. Training labels come ONLY from real subsequent
100-mob Rust runs with the same source engine/scenario; a censored/dead run
is never a 100-mob duration label.
"""
from __future__ import annotations

import math
from statistics import fmean
from typing import Any

THREE = 3
FEATURES = (
    "mean_kill_s", "late_kill_s", "kill_time_slope",
    "mana_end_fraction", "mana_net_drain_per_mob_fraction",
    "health_end_fraction", "health_net_drain_per_mob_fraction",
    "native_mana_regen_per_mob_fraction",
    "native_health_damage_per_mob_fraction",
    "long_cooldowns_ready_per_100_s",
    "long_cooldown_casts_first3",
    "long_cooldown_remaining_s",
    "mana_spent_per_mob_fraction",
    "mana_gained_per_mob_fraction",
    "health_actual_gain_per_mob_fraction",
)


def finite(value: Any, label: str) -> float:
    if type(value) not in (float, int) or not math.isfinite(float(value)):
        raise ValueError("Rust native probe missing finite " + label)
    return float(value)


def cooldown_receipt(prepared: dict, windows: list[dict]) -> dict:
    """Source-native long-CD ability, actual casts and remaining cooldown.

    A 180s cooldown cast in the first three mobs is *not* available
    for the next 180s; report remaining time rather than allowing the
    predictor to multiply the initial burst by 100.
    """
    if not windows:
        raise ValueError("No native cooldown windows")
    last = windows[-1]
    if not all("native_spell_cast_receipts" in w and
               "native_long_cooldown_states" in w for w in windows):
        return {
            "long_cooldowns_available": [],
            "long_cooldown_casts_total": None,
            "long_cooldown_remaining_s": None,
            "long_cooldown_usage_observed": False,
            "long_cooldown_usage_source": "Missing source-Rust native spell cast receipts",
        }
    states = last["native_long_cooldown_states"]
    casts = [cast for w in windows for cast in w["native_spell_cast_receipts"]
             if cast.get("is_long_cooldown") is True]
    for state in states:
        if not (type(state.get("duration_ns")) is int
                and type(state.get("ready_in_ns")) is int
                and state["ready_in_ns"] >= 0):
            raise ValueError("Invalid native cooldown timer receipt")
    total = sum(int(row["casts"]) for row in casts)
    return {
        "long_cooldowns_available": states,
        "long_cooldown_casts_total": total,
        "long_cooldown_remaining_s": sum(
            state["ready_in_ns"]/1e9 for state in states),
        "long_cooldown_usage_observed": True,
        "long_cooldown_usage_source": "Rust retained actor spell.cast counts and timer state",
        "long_cooldown_casts_by_mob": [
            [cast for cast in w["native_spell_cast_receipts"]
             if cast.get("is_long_cooldown") is True] for w in windows],
    }


def extract_three_mob_features(prepared: dict, world: dict) -> dict:
    """Consume ONLY real ACKed, retained-actor three-target Rust receipts."""
    if (world.get("world_targets_killed") != THREE or
            world.get("continuous_native_actor") is not True or
            world.get("actual_2d_ack") is not True):
        raise ValueError("Three-mob native receipts must be 3 lethal ACKs on one actor")
    windows = world.get("native_windows") or []
    if len(windows) != THREE:
        raise ValueError("Rust did not report all three windows")
    kills = [finite(v, "native_kill_ns") / 1e9 for v in
             (w.get("native_kill_ns") for w in windows)]
    if not (0 < kills[0] < kills[1] < kills[2]):
        raise ValueError("Nonmonotonic Rust kill clocks")
    times = [kills[0], kills[1] - kills[0], kills[2] - kills[1]]
    if abs(kills[-1] - finite(world["world_elapsed_seconds"], "world elapsed")) > 1e-5:
        raise ValueError("World and native kill clocks differ")
    health_max = finite(prepared["player"]["stats"]["Health"], "native max HP")
    mana_max = finite(prepared["player"]["mana"]["max"], "native max mana")
    if health_max <= 0 or mana_max <= 0:
        raise ValueError("Invalid source-native player resource maximum")
    health = [finite(w.get("actor_health"), "HP") for w in windows]
    mana = [finite(w.get("actor_mana"), "mana") for w in windows]
    if min(health) <= 0 or min(mana) < 0:
        raise ValueError("Rust actor died or resource receipt invalid")
    native_mana_regen = [w.get("native_combat_mana_regen_actual_gain")
                         for w in windows]
    native_health_damage = [w.get("native_health_damage_taken")
                            for w in windows]
    regen_observed = all(type(v) in (int,float) for v in native_mana_regen)
    damage_observed = all(type(v) in (int,float) for v in native_health_damage)
    regen = sum(finite(v,"mana regen") for v in native_mana_regen) if regen_observed else None
    damage = sum(finite(v,"HP damage") for v in native_health_damage) if damage_observed else None
    cd = cooldown_receipt(prepared, windows)
    cd_rate = sum(100.0 / (state["duration_ns"]/1e9)
                  for state in cd["long_cooldowns_available"])
    mana_spent_rows = [w.get("native_mana_spent") for w in windows]
    mana_gained_rows = [w.get("native_mana_gained") for w in windows]
    hp_gained_rows = [w.get("native_health_actual_gain") for w in windows]
    spent_observed = all(type(v) in (float,int) for v in mana_spent_rows)
    gained_observed = all(type(v) in (float,int) for v in mana_gained_rows)
    hp_gained_observed = all(type(v) in (float,int) for v in hp_gained_rows)
    mana_spent = sum(finite(v, "mana spent") for v in mana_spent_rows) if spent_observed else None
    mana_gained = sum(finite(v, "mana gained") for v in mana_gained_rows) if gained_observed else None
    health_gained = sum(finite(v, "health gain") for v in hp_gained_rows) if hp_gained_observed else None
    features = {
        "mean_kill_s": fmean(times),
        "late_kill_s": fmean(times[1:]),
        "kill_time_slope": (times[2] - times[0]) / 2.0,
        "mana_end_fraction": mana[-1] / mana_max,
        "mana_net_drain_per_mob_fraction": (mana_max - mana[-1]) / (THREE * mana_max),
        "health_end_fraction": health[-1] / health_max,
        "health_net_drain_per_mob_fraction": (health_max - health[-1]) / (THREE * health_max),
        "native_mana_regen_per_mob_fraction":
            regen / (THREE * mana_max) if regen is not None else 0.0,
        "native_health_damage_per_mob_fraction":
            damage / (THREE * health_max) if damage is not None else 0.0,
        "long_cooldowns_ready_per_100_s": cd_rate,
        "long_cooldown_casts_first3": cd["long_cooldown_casts_total"] or 0.,
        "long_cooldown_remaining_s": cd["long_cooldown_remaining_s"] or 0.,
        "mana_spent_per_mob_fraction": (
            mana_spent/(THREE*mana_max) if mana_spent is not None else 0.),
        "mana_gained_per_mob_fraction": (
            mana_gained/(THREE*mana_max) if mana_gained is not None else 0.),
        "health_actual_gain_per_mob_fraction": (
            health_gained/(THREE*health_max) if health_gained is not None else 0.),
    }
    if any(not math.isfinite(v) for v in features.values()):
        raise ValueError("Nonfinite Rust-derived feature")
    return {
        "features": features,
        "raw": {
            "kill_times_s": times, "kill_clocks_s": kills,
            "health_after_each_kill": health, "mana_after_each_kill": mana,
            "health_max": health_max, "mana_max": mana_max,
            "native_mana_regen_actual_gain": regen,
            "native_health_damage_taken": damage,
            "native_health_actual_gain": health_gained,
            "native_mana_spent": mana_spent,
            "native_mana_gained": mana_gained,
            "native_cast_receipts_observed": spent_observed and gained_observed,
            "native_spell_cast_receipts": [w.get("native_spell_cast_receipts") for w in windows],
            "native_mana_regen_observed": regen_observed,
            "native_health_damage_observed": damage_observed,
            "native_passive_recovery_ns": [w.get("native_passive_recovery_ns") for w in windows],
            "native_passive_recovery_ticks": [w.get("native_passive_recovery_ticks") for w in windows],
        },
        "cooldowns": cd,
        "source": "3 genuine Rust world kills, one actor; 100-mob result not inferred",
    }


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Tiny ridge normal-equation solver; no ML library or neural architecture."""
    n = len(vector)
    augmented = [matrix[i][:] + [vector[i]] for i in range(n)]
    for index in range(n):
        pivot = max(range(index,n), key=lambda j: abs(augmented[j][index]))
        augmented[index],augmented[pivot] = augmented[pivot],augmented[index]
        value = augmented[index][index]
        if abs(value) < 1e-12:
            raise ValueError("Ridge fit had singular design")
        for k in range(index,n+1):
            augmented[index][k] /= value
        for row in range(n):
            if row == index:
                continue
            scalar = augmented[row][index]
            for k in range(index,n+1):
                augmented[row][k] -= scalar * augmented[index][k]
    return [augmented[i][-1] for i in range(n)]


def _fit_ridge(rows: list[tuple[dict, float]], penalty: float = 12.) -> dict:
    if len(rows) < 6:
        raise ValueError("Six actual labeled Rust sessions required")
    means = [fmean(float(row["features"][k]) for row,_ in rows) for k in FEATURES]
    scales = [
        max(1e-8, math.sqrt(fmean((float(row["features"][k])-mean)**2
                               for row,_ in rows)))
        for k,mean in zip(FEATURES,means)
    ]
    x = [[1.] + [(float(row["features"][k])-mean)/scale
                  for k,mean,scale in zip(FEATURES,means,scales)]
         for row,_ in rows]
    y = [value for _,value in rows]
    m = len(FEATURES)+1
    mat = [[sum(a[i]*a[j] for a in x) + (penalty if i==j and i>0 else 0.)
            for j in range(m)] for i in range(m)]
    vec = [sum(a[i]*v for a,v in zip(x,y)) for i in range(m)]
    coefficients = _solve_linear(mat,vec)
    return {"means":means,"scales":scales,"coefficients":coefficients,
            "samples":len(rows),"lambda":penalty}


def _predict_regression(model: dict, probe: dict) -> float:
    f=probe["features"]
    x=[1.]+[(float(f[k])-mu)/scale
            for k,mu,scale in zip(FEATURES,model["means"],model["scales"])]
    return sum(a*b for a,b in zip(x,model["coefficients"]))


def train_supervised(sessions: list[dict], *, engine_sha: str,
                     scenario_id: str) -> dict:
    """Train only from 100-world-mob truth on the SAME engine/scenario.

    Failed/partial runs can train survival, but NEVER the finished time.
    Cross-validation is leave-one-out; report MAE, not an invented confidence.
    """
    labeled=[]
    for row in sessions:
        if (row.get("engine_sha") != engine_sha
                or row.get("scenario_id") != scenario_id):
            continue
        if not isinstance(row.get("probe"),dict):
            continue
        result=row.get("result") or {}
        complete = (result.get("status")=="COMPLETED"
                    and result.get("confirmed_kills")==100)
        if complete:
            elapsed=finite(result.get("elapsed_s"),"100-mob elapsed")
            if elapsed<=0:
                raise ValueError("Nonpositive 100-mob elapsed")
        else:
            elapsed=None
        # Never treat an untested case as an observed failure.
        if not complete and result.get("status") not in ("INCOMPLETE","FAILED"):
            continue
        labeled.append((row["probe"],complete,elapsed))
    survival_rows=[(p,float(ok)) for p,ok,_ in labeled]
    time_rows=[(p,math.log(sec)) for p,ok,sec in labeled if ok]
    model={"engine_sha":engine_sha,"scenario_id":scenario_id,
           "features":list(FEATURES),"labeled_100_runs":len(labeled),
           "completed_100_runs":len(time_rows),
           "survival_model":None,"time_model":None,
           "loo_mae_elapsed_s":None}
    if len(survival_rows)>=6 and len({y for _,y in survival_rows})>1:
        model["survival_model"]=_fit_ridge(survival_rows)
    if len(time_rows)>=6:
        model["time_model"]=_fit_ridge(time_rows)
        # LOO MAE in elapsed-time units, retraining on N-1 only.
        errors=[]
        for index,(probe,label) in enumerate(time_rows):
            train=[row for j,row in enumerate(time_rows) if j!=index]
            if len(train)<6:
                break
            value=math.exp(_predict_regression(_fit_ridge(train),probe))
            errors.append(abs(value-math.exp(label)))
        if errors:
            model["loo_mae_elapsed_s"]=fmean(errors)
    return model


def predict(model: dict, probe: dict, *, engine_sha: str,
            scenario_id: str) -> dict:
    if (model["engine_sha"] != engine_sha
            or model["scenario_id"] != scenario_id):
        raise ValueError("Never transfer 100-mob surrogate to different Rust engine/scenario")
    if not isinstance(probe.get("features"),dict):
        raise ValueError("No native three-mob features")
    reference = model.get("time_model") or model.get("survival_model")
    distance = None
    if reference is not None:
        # A bounded standardized distance is an extrapolation diagnostic,
        # NOT a calibrated probability interval or an engine mechanic.
        z = [(float(probe["features"][key])-mean)/scale
             for key,mean,scale in zip(FEATURES,reference["means"],
                                       reference["scales"])]
        distance = math.sqrt(fmean(min(5.,abs(value))**2 for value in z))
    result={
        "standardized_training_distance":distance,
        "estimated_100_mob_elapsed_s":None,
        "probability_100_mob_completed":None,
        "uncertainty_mae_s":model.get("loo_mae_elapsed_s"),
        "training_completed_100_runs":model["completed_100_runs"],
        "training_labeled_100_runs":model["labeled_100_runs"],
        "naive_3_mob_extrapolation_s":probe["features"]["late_kill_s"]*100,
        "prediction_trained":model["time_model"] is not None,
    }
    if model["time_model"] is not None:
        result["estimated_100_mob_elapsed_s"]=math.exp(
            _predict_regression(model["time_model"],probe))
    if model["survival_model"] is not None:
        result["probability_100_mob_completed"]=max(
            0.,min(1.,_predict_regression(model["survival_model"],probe)))
    return result


def select_native_100_validation(untested: list[dict], observed: list[dict],
                                 *, iteration: int) -> tuple[dict, str]:
    """Choose one MORE genuinely paid 100-mob Rust run.

    Exploitation uses completed-chain labels only. Every third adaptive
    choice targets out-of-distribution/category diversity; untrained models
    use native HP/mana/time receipts for bootstrap. This never predicts a
    kill, changes a game rule, or awards a completed chain.
    """
    if not untested:
        raise ValueError("No unvalidated native three-mob cases")

    def diversity(case: dict) -> float:
        chosen = case["result"]
        return sum(
            1.0 / (1.0 + sum(
                previous["result"].get(axis) == chosen.get(axis)
                for previous in observed))
            for axis in ("gear", "talents", "pet", "filler")
        )

    predicted = [case for case in untested
                 if isinstance(case["result"].get("surrogate"), dict)
                 and case["result"]["surrogate"].get(
                     "estimated_100_mob_elapsed_s") is not None]
    if not predicted:
        def native_priority(case: dict) -> tuple:
            f = case["probe"]["features"]
            return (f["health_end_fraction"], f["mana_end_fraction"],
                    -f["kill_time_slope"], -f["late_kill_s"], diversity(case))
        return max(untested, key=native_priority), "native_resource_bootstrap"

    if iteration % 3 == 2:
        def exploration(case: dict) -> tuple:
            p = case["result"]["surrogate"]
            distance = p.get("standardized_training_distance")
            return (float(distance) if distance is not None else 0.,
                    diversity(case), -case["probe"]["features"]["late_kill_s"])
        return max(predicted, key=exploration), "out_of_sample_exploration"

    def exploitation(case: dict) -> tuple:
        p = case["result"]["surrogate"]
        survival = p.get("probability_100_mob_completed")
        # With no failed chain labels, completion probability is UNKNOWN,
        # not 100%. Keep neutral until verified negative labels exist.
        survival = 0.5 if survival is None else float(survival)
        distance = p.get("standardized_training_distance")
        uncertainty_penalty = 1. + .05 * min(
            6., float(distance) if distance is not None else 0.)
        estimated = float(p["estimated_100_mob_elapsed_s"])
        if not math.isfinite(estimated) or estimated <= 0:
            return (float("inf"), 0.)
        return (estimated * uncertainty_penalty /
                max(.2, .25 + .75 * survival), -diversity(case))
    return min(predicted, key=exploitation), "predicted_100_mob_exploitation"
