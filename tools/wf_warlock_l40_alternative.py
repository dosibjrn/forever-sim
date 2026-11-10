#!/usr/bin/env python3
"""Source-native same-level L40 Warlock challenger and paid comparison.

gsim/Forever proposes *one* alternative talent allocation. MythicSim options
supplies available ranks and native prepare alone decides validity. The actual
hostile 100-kill Decisions replay is executed by wf_warlock_route_guide, not
by this proposer. This is an L40 counterfactual, NOT a dual-spec route.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path

from tools.wf_warlock_next_level_source import verified_paid_predecessor


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actor_of(request: dict) -> dict:
    return request["raid"]["parties"][0]["players"][0]


def _set_rank(tokens: list[str], tree: int, index: int, change: int) -> list[str]:
    result = list(tokens)
    digits = list(result[tree])
    digits.extend("0" for _ in range(max(0, index + 1 - len(digits))))
    digits[index] = str(int(digits[index]) + change)
    result[tree] = "".join(digits)
    return result


def propose(*, binary: Path, source: Path, baseline_route: Path,
            out: Path, max_proposals: int = 160) -> dict:
    """Try bounded one-rank reallocations, with NO Python talent legality rules."""
    if max_proposals < 1:
        raise ValueError("max_proposals must be positive")
    paid = verified_paid_predecessor(
        route=baseline_route, source=source, binary=binary, from_level=40)
    original = json.loads(source.read_text())
    actor = actor_of(original)
    if (actor.get("class") != "ClassWarlock" or actor.get("level") != 40
            or original["encounter"]["targets"][0].get("level") != 40):
        raise ValueError("original paid L40 source has mismatched actor/target identity")
    tokens = actor["talentsString"].split("-")
    if len(tokens) != 3 or any(not s.isascii() or not s.isdigit() for s in tokens):
        raise ValueError("cannot mutate the native talent serialization")
    options_result = subprocess.run(
        [str(binary.resolve()), "options", "--class", "warlock", "--level", "40"],
        capture_output=True, text=True, check=False, timeout=60)
    if options_result.returncode:
        raise RuntimeError("native L40 options refused: " +
                           (options_result.stderr or options_result.stdout)[-1600:])
    options = json.loads(options_result.stdout)
    trees = options.get("talents", {}).get("trees")
    if options.get("level") != 40 or not isinstance(trees, list) or len(trees) != 3:
        raise ValueError("native L40 talent options unavailable")
    # Only native options list potential targets. Do not infer prerequisites,
    # tier unlocks, points budget, or class mechanics in Forever.
    listed = []
    for tree_i, tree in enumerate(trees):
        for entry in tree["talents"]:
            index = entry["index"]
            cap = entry["max_rank"]
            if type(index) is not int or type(cap) is not int or index < 0 or cap < 1:
                raise ValueError("invalid native talent option transport")
            current = int(tokens[tree_i][index]) if index < len(tokens[tree_i]) else 0
            listed.append((tree_i, index, current, cap))
    sources = [(ti, ix) for ti, ix, current, _ in listed if current > 0]
    destinations = [(ti, ix) for ti, ix, current, cap in listed if current < cap]
    # Favor a distinct tree first, then stable native index order. It is just
    # a search heuristic, never an inferred legal alternate spec.
    pairs = [(src, dest) for src in sources for dest in destinations if src != dest]
    pairs.sort(key=lambda row: (row[0][0] == row[1][0], row[1], row[0]))
    out.mkdir(parents=True, exist_ok=True)
    attempts = out / "candidate_attempts"
    attempts.mkdir(exist_ok=True)
    refused = []
    for n, (src, dest) in enumerate(pairs[:max_proposals], 1):
        new_tokens = _set_rank(tokens, *src, -1)
        new_tokens = _set_rank(new_tokens, *dest, 1)
        changed = copy.deepcopy(original)
        actor_of(changed)["talentsString"] = "-".join(new_tokens)
        request_file = attempts / f"candidate_{n:03d}.json"
        prepared_file = attempts / f"candidate_{n:03d}.prepared.json"
        request_file.write_text(json.dumps(changed, indent=2) + "\n")
        result = subprocess.run(
            [str(binary.resolve()), "prepare", "--request", str(request_file.resolve()),
             "--actor-level", "40", "--outfile", str(prepared_file.resolve())],
            capture_output=True, text=True, check=False, timeout=60)
        if result.returncode or not prepared_file.is_file():
            refused.append({"from": list(src), "to": list(dest),
                            "native_response": (result.stderr or result.stdout)[-1000:],
                            "exit_code": result.returncode})
            continue
        selected = out / "source_request.json"
        selected.write_bytes(request_file.read_bytes())
        receipt = {
            "kind": "native_l40_same_level_talent_challenger",
            "status": "NATIVE_PREPARED_NOT_YET_PAID",
            "baseline_observation_id": paid["observation_id"],
            "baseline_source_sha256": digest(source),
            "native_binary_sha256": digest(binary),
            "selected_source_sha256": digest(selected),
            "source_talents": actor["talentsString"],
            "challenger_talents": actor_of(changed)["talentsString"],
            "from_rank": list(src), "to_rank": list(dest),
            "attempted": n, "native_refusals": refused,
            "claim": "Standalone L40 native-prepared challenge, no paid kill or dual-spec route yet",
        }
        (out / "proposal.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return receipt
    receipt = {
        "kind": "native_l40_same_level_talent_challenger",
        "status": "NATIVE_PREPARE_REFUSED_ALL_PROPOSALS",
        "baseline_observation_id": paid["observation_id"],
        "baseline_source_sha256": digest(source),
        "native_binary_sha256": digest(binary),
        "attempted": min(len(pairs), max_proposals),
        "native_refusals": refused,
    }
    (out / "proposal.json").write_text(json.dumps(receipt, indent=2) + "\n")
    raise RuntimeError("Native prepare refused all same-level L40 challenger proposals")


def _paid_row(report: dict, *, source_sha: str) -> dict:
    rows = [r for r in report.get("observations", []) if
            r.get("level") == 40 and r.get("status") == "measured_native_chain"
            and r.get("source_request_sha256") == source_sha
            and r.get("targets_requested") == r.get("targets_killed") == 100
            and r.get("paid_native_recovery") is True
            and r.get("native_world_ack") is True]
    if len(rows) != 1:
        raise ValueError("missing or ambiguous exact-source paid L40 100/100 receipt")
    return rows[0]


def compare(*, baseline_route: Path, baseline_source: Path,
            challenger_route: Path, challenger_source: Path,
            proposal: Path, out: Path) -> dict:
    """Compare comparable paid L40 observations, without inferring route gains."""
    receipt = json.loads(proposal.read_text())
    if receipt.get("status") != "NATIVE_PREPARED_NOT_YET_PAID":
        raise ValueError("cannot compare an unprepared/refused challenger")
    if (digest(baseline_source) != receipt.get("baseline_source_sha256")
            or digest(challenger_source) != receipt.get("selected_source_sha256")):
        raise ValueError("compared source bytes must match native proposal")
    baseline_request = json.loads(baseline_source.read_text())
    challenger_request = json.loads(challenger_source.read_text())
    # Exactly one dimension was intentionally changed: talents. No hidden
    # equipment, APL, pet, encounter or recovery change can earn this comparison.
    baseline_talents = actor_of(baseline_request).pop("talentsString")
    challenger_talents = actor_of(challenger_request).pop("talentsString")
    if baseline_request != challenger_request or baseline_talents == challenger_talents:
        raise ValueError("L40 challenger must change only the native talent string")
    base = _paid_row(json.loads(baseline_route.read_text()), source_sha=digest(baseline_source))
    challenge = _paid_row(json.loads(challenger_route.read_text()),
                          source_sha=digest(challenger_source))
    if any(base.get(key) != challenge.get(key) for key in
           ("scenario", "engine_binary_sha256", "recovery_policy")):
        raise ValueError("paid L40 native scenarios/recovery/engine are not comparable")
    if base.get("engine_binary_sha256") != receipt.get("native_binary_sha256"):
        raise ValueError("comparison engine differs from prepared challenger")
    baseline_seconds = float(base["elapsed_seconds_for_observed_chain"])
    challenger_seconds = float(challenge["elapsed_seconds_for_observed_chain"])
    if baseline_seconds <= 0 or challenger_seconds <= 0:
        raise ValueError("paid elapsed time must be positive")
    saved = baseline_seconds - challenger_seconds
    result = {
        "kind": "paid_l40_same_scenario_talent_comparison",
        "status": "PAID_COMPARABLE_100_100",
        "baseline_observation_id": base["id"],
        "challenger_observation_id": challenge["id"],
        "native_binary_sha256": base["engine_binary_sha256"],
        "baseline_source_sha256": digest(baseline_source),
        "challenger_source_sha256": digest(challenger_source),
        "baseline_elapsed_s": baseline_seconds,
        "challenger_elapsed_s": challenger_seconds,
        "standalone_l40_seconds_saved": round(saved, 4),
        "no_purchase_default": True,
        "dual_spec_10_60_gain_measured": False,
        "full_10_60_native_replay_executed": False,
        "interpretation": ("One standalone L40 talent counterfactual only. "
                           "A legal second evolving path, purchase/switch costs and "
                           "L40-L60 native results are not measured."),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--baseline-route", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-proposals", type=int, default=160)
    c = sub.add_parser("compare")
    c.add_argument("--baseline-route", type=Path, required=True)
    c.add_argument("--baseline-source", type=Path, required=True)
    c.add_argument("--challenger-route", type=Path, required=True)
    c.add_argument("--challenger-source", type=Path, required=True)
    c.add_argument("--proposal", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.command == "propose":
        result = propose(binary=args.binary, source=args.source,
                         baseline_route=args.baseline_route, out=args.out,
                         max_proposals=args.max_proposals)
    else:
        result = compare(baseline_route=args.baseline_route,
                         baseline_source=args.baseline_source,
                         challenger_route=args.challenger_route,
                         challenger_source=args.challenger_source,
                         proposal=args.proposal, out=args.out)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
