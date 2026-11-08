#!/usr/bin/env python3
"""Out-of-sample ranking diagnostics for native 3-to-100 mob surrogate.

Train only on the other completed native 100-kill observations in every fold.
Report leave-one-candidate-out AND stricter leave-one-build-family-out:
same (gear, talents, pet) never appears in both training and validation.
No fake labels from deaths, native timeouts or the first three kills.
"""
from __future__ import annotations

import math
from statistics import fmean

from wf_warlock_chain_surrogate import train_supervised, predict


def _score_rows(rows):
    if len(rows) < 2:
        return {
            "predictions": len(rows),
            "pairwise_accuracy": None,
            "pairwise_correct": 0,
            "pairwise_total": 0,
            "spearman_rho": None,
            "top1_actual_rank": None,
            "top3_contains_actual_winner": None,
            "selection_regret_s": None,
            "mae_seconds": None,
            "mape": None,
            "large_gap_120s_accuracy": None,
        }
    by_pred = sorted(rows, key=lambda row: (row["predicted_s"], row["candidate"]))
    by_truth = sorted(rows, key=lambda row: (row["actual_s"], row["candidate"]))
    rank_pred = {r["candidate"]: i for i, r in enumerate(by_pred)}
    rank_true = {r["candidate"]: i for i, r in enumerate(by_truth)}
    n = len(rows)
    pairs = correct = large = large_correct = 0
    for i in range(n):
        for j in range(i + 1, n):
            one, two = rows[i], rows[j]
            true_delta = one["actual_s"] - two["actual_s"]
            pred_delta = one["predicted_s"] - two["predicted_s"]
            if abs(true_delta) < 1e-9 or abs(pred_delta) < 1e-9:
                continue
            pairs += 1
            right = true_delta * pred_delta > 0
            correct += right
            if abs(true_delta) >= 120:
                large += 1
                large_correct += right
    order_penalty = sum((rank_pred[row["candidate"]]-rank_true[row["candidate"]]) ** 2
                        for row in rows)
    return {
        "predictions": n,
        "pairwise_accuracy": correct / pairs if pairs else None,
        "pairwise_correct": correct,
        "pairwise_total": pairs,
        "spearman_rho": 1. - 6. * order_penalty / (n * (n*n - 1)),
        "top1_actual_rank": rank_true[by_pred[0]["candidate"]] + 1,
        "top3_contains_actual_winner": any(
            r["candidate"] == by_truth[0]["candidate"] for r in by_pred[:3]),
        "selection_regret_s": by_pred[0]["actual_s"] - by_truth[0]["actual_s"],
        "mae_seconds": fmean(abs(row["predicted_s"] - row["actual_s"]) for row in rows),
        "mape": fmean(abs(row["predicted_s"] - row["actual_s"]) / row["actual_s"]
                      for row in rows),
        "large_gap_120s_accuracy": large_correct / large if large else None,
        "large_gap_120s_correct": large_correct,
        "large_gap_120s_total": large,
    }


def report_rank_validation(sessions, cases, *, engine_sha, scenario_id):
    """Strict held-out forecasts. Return None for insufficient training.

    A group is a native gear+talent+pet combination; nearby APL variants
    cannot leak into one another's group holdout training.
    """
    lookup = {case["result"]["candidate"]: case["result"] for case in cases}
    valid = []
    for row in sessions:
        if row.get("engine_sha") != engine_sha or row.get("scenario_id") != scenario_id:
            continue
        native = row.get("result") or {}
        if native.get("status") != "COMPLETED" or native.get("confirmed_kills") != 100:
            continue
        if not isinstance(row.get("probe"), dict):
            continue
        value = native.get("elapsed_s")
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            continue
        candidate_id = row.get("candidate")
        if candidate_id not in lookup:
            continue
        item = lookup[candidate_id]
        key = (item["gear"], item["talents"], item["pet"])
        valid.append({"session": row, "candidate": candidate_id,
                      "family": key, "actual_s": float(value)})
    # Remove duplicates of a candidate, keep latest real native receipt.
    records = {row["candidate"]: row for row in valid}
    valid = list(records.values())

    metrics = {}
    for mode in ("leave_one_candidate_out", "leave_one_build_family_out"):
        scored = []
        missing = []
        for row in valid:
            others = [
                r["session"] for r in valid if (
                    r["candidate"] != row["candidate"] if mode ==
                    "leave_one_candidate_out" else r["family"] != row["family"])
            ]
            model = train_supervised(
                others, engine_sha=engine_sha, scenario_id=scenario_id)
            if model["time_model"] is None:
                missing.append(row["candidate"])
                continue
            forecast = predict(model, row["session"]["probe"],
                               engine_sha=engine_sha, scenario_id=scenario_id)
            predicted = forecast["estimated_100_mob_elapsed_s"]
            if (type(predicted) not in (int, float)
                    or not math.isfinite(predicted) or predicted <= 0):
                missing.append(row["candidate"])
                continue
            scored.append({
                "candidate": row["candidate"], "actual_s": row["actual_s"],
                "predicted_s": float(predicted),
                "build_family": list(row["family"]),
                "train_size": model["completed_100_runs"],
            })
        metrics[mode] = {
            **_score_rows(scored),
            "excluded_no_train": missing,
            "all_completed_100": len(valid),
            "rows": sorted(scored, key=lambda r: r["actual_s"]),
        }
    return {
        "engine_sha": engine_sha,
        "scenario_id": scenario_id,
        "validation": metrics,
        "note": "Cross-fitted predictions only. Group holdout excludes all "
                "100-mob labels with the same (gear, talents, pet). No training "
                "score is reported as held-out ranking performance.",
    }
