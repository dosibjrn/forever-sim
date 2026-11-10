#!/usr/bin/env python3
"""Start an authentic native-paid Warlock L10 root, then resume L11+ in one call.

The L20 request is only a shape/template; it is NEVER an L10 predecessor,
leveling receipt or talent/gear source. Rust supplies L10 alternatives and
alone prepares the proposed L10 actor. The existing native paid-range engine
owns all subsequent adjacent levels and exact paid-receipt reuse.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

# Workflow invokes this as "python tools/wf_warlock_l10_root.py". Ensure
# package imports work without PYTHONPATH, as in the adjacent-range driver.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import wf_warlock_native_start_source as same_level
from tools import wf_warlock_next_level_source as next_level
from tools import wf_warlock_paid_range as paid_range
from tools import wf_warlock_route_guide as guide


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _refusal_report(out: Path, *, status: str, reason: str, binary_sha: str,
                    template_sha: str) -> None:
    report = guide.build_route_report({
        "schema_version": 1, "class": "warlock", "start_level": 10,
        "end_level": 60, "observations": [], "native_refusals": [{
            "variant": "native_actor_L10", "level": 10, "status": status,
            "error": reason, "native_binary_sha256": binary_sha,
            "original_source_sha256": template_sha, "killed": None,
        }],
    })
    _write(out / "route.json", report)
    (out / "GUIDE.md").write_text(guide.render_guide(report))


def propose_root(*, binary: Path, template: Path, out: Path,
                 max_proposals: int = 30) -> dict:
    """Offer native-discovered talent/spell proposals; accept only Rust prepare."""
    if not binary.is_file() or not template.is_file() or max_proposals < 1:
        raise ValueError("L10 requires existing binary/template and positive proposal budget")
    original = json.loads(template.read_text())
    player = original["raid"]["parties"][0]["players"][0]
    if player.get("class") != "ClassWarlock" or player.get("race") != "RaceTroll":
        raise ValueError("L10 template must contain a Troll Warlock actor")
    if (player.get("level") is not None and
            (type(player["level"]) is not int or
             original["encounter"]["targets"][0].get("level") != player["level"])):
        raise ValueError("template actor and encounter must agree on their source level")
    if not isinstance(player.get("equipment", {}).get("items"), list):
        raise ValueError("native template needs an equipment proposal list")
    out.mkdir(parents=True, exist_ok=True)
    selected = out / "source_request.json"
    selected.unlink(missing_ok=True)
    template_sha = next_level.sha256(template)
    binary_sha = next_level.sha256(binary)
    call = subprocess.run(
        [str(binary.resolve()), "options", "--class", "warlock", "--level", "10"],
        capture_output=True, text=True, timeout=60, check=False)
    refusals = []
    options = None
    if call.returncode:
        refusals.append({"stage": "options",
                         "reason": (call.stderr or call.stdout or "native options refused")[-2000:]})
    else:
        try:
            options = json.loads(call.stdout)
            if options.get("class") != "warlock" or options.get("level") != 10:
                raise ValueError("native options returned a different actor")
        except (ValueError, AttributeError) as exc:
            refusals.append({"stage": "options", "reason": str(exc)})
            options = None
    if options is not None:
        # Names and numeric identities come from this exact Rust options reply.
        # The order below is a search heuristic, not a spell-legality rule.
        spells = options.get("spells", [])
        choices = [s for s in spells if isinstance(s, dict)
                   and type(s.get("spell_id")) is int and s["spell_id"] > 0]
        keywords = ("shadow bolt", "corruption", "immolate", "agony")
        choices.sort(key=lambda s: next(
            (i for i, word in enumerate(keywords)
             if word in str(s.get("name", "")).casefold()), len(keywords)))
        talent_strings = ["0-0-0"]  # banked-point candidate; Rust can refuse
        for tree_number, tree in enumerate(options.get("talents", {}).get("trees", [])):
            for entry in tree.get("talents", []):
                index = entry.get("index")
                if type(index) is not int or index < 0 or entry.get("max_rank", 0) < 1:
                    continue
                allocation = [["0"] * (index + 1) if t == tree_number else ["0"]
                              for t in range(3)]
                allocation[tree_number][index] = "1"
                talent_strings.append("-".join("".join(t) for t in allocation))
        tried = 0
        for talents in dict.fromkeys(talent_strings):
            for spell in choices:
                if tried >= max_proposals:
                    break
                tried += 1
                request = copy.deepcopy(original)
                actor = request["raid"]["parties"][0]["players"][0]
                actor["level"] = 10
                actor["talentsString"] = talents
                request["encounter"]["targets"][0]["level"] = 10
                # A minimal candidate APL uses a native-offered spell ID.
                # Rust prepare, not Forever, judges whether it is usable.
                actor.setdefault("rotation", {})["priorityList"] = [{
                    "action": {"castSpell": {"spellId": {"spellId": spell["spell_id"]}}}
                }]
                candidate = out / "attempts" / f"root_{tried:02d}"
                request_path = candidate / "template_request.json"
                _write(request_path, request)
                result = same_level.select_prepared_source(
                    binary=binary, source=request_path, out=candidate / "native",
                    actor_level=10)
                if result["status"] == "NATIVE_PREPARED_NOT_YET_PAID":
                    selected.write_bytes((candidate / "native" / "source_request.json").read_bytes())
                    receipt = {
                        "kind": "warlock_native_l10_root",
                        "status": "NATIVE_PREPARED_NOT_YET_PAID",
                        "level": 10, "paid_predecessor": None,
                        "original_template_sha256": template_sha,
                        "native_binary_sha256": binary_sha,
                        "native_options_source_revision": options.get("source_revision"),
                        "selected_source_sha256": next_level.sha256(selected),
                        "selected_talents": talents, "selected_spell_id": spell["spell_id"],
                        "attempted": tried, "native_refusals_before_selection": refusals,
                    }
                    _write(out / "proposal.json", receipt)
                    return receipt
                refusals.append({"stage": "prepare", "talents": talents,
                                 "spell_id": spell["spell_id"],
                                 "native_refusals": result["native_refusals"]})
            if tried >= max_proposals:
                break
    receipt = {
        "kind": "warlock_native_l10_root",
        "status": ("NATIVE_OPTIONS_REFUSED" if options is None
                   else "NATIVE_PREPARE_REFUSED_ALL_SOURCES"),
        "level": 10, "paid_predecessor": None,
        "original_template_sha256": template_sha,
        "native_binary_sha256": binary_sha,
        "attempted": len([r for r in refusals if r["stage"] == "prepare"]),
        "native_refusals": refusals,
    }
    _write(out / "proposal.json", receipt)
    return receipt


def run(*, binary: Path, template: Path, out: Path, end_level: int = 19,
        max_new_levels: int = 10, max_proposals: int = 30,
        health_threshold: float = 0.7, mana_threshold: float = 0.25,
        run_url: str | None = None) -> dict:
    if not 10 <= end_level <= 19 or max_new_levels < 1:
        raise ValueError("L10 root range requires end 10..19 and positive budget")
    if not 0 < health_threshold <= 1 or not 0 < mana_threshold <= 1:
        raise ValueError("Decisions thresholds must be in (0,1]")
    if not binary.is_file() or not template.is_file():
        raise ValueError("root range needs native executable and source template")
    if run_url is not None and (
        not run_url.startswith("https://github.com/")
        or "/actions/runs/" not in run_url
    ):
        raise ValueError("run_url must identify an actual GitHub Actions run")
    engine_sha, template_sha = next_level.sha256(binary), next_level.sha256(template)
    key = paid_range._digest({
        "level": 10, "native_binary": engine_sha, "template": template_sha,
        "max_proposals": max_proposals, "health_threshold": health_threshold,
        "mana_threshold": mana_threshold, "recovery": "decisions",
        "target_count": 100, "hostile": True,
    })
    folder = out / "L10" / key
    proposal_dir, paid_dir = folder / "proposal", folder / "paid"
    source, route = proposal_dir / "source_request.json", paid_dir / "route.json"
    completed, reused = [], []
    stopped = None
    latest_route, latest_source = route, source

    def save(next_level_number: int) -> dict:
        native_guide = latest_route.with_name("GUIDE.md")
        latest_guide = out / "GUIDE.md"
        if stopped and stopped.get("status") == "PAID_ACK_UNVERIFIED":
            # Keep the producer's original guide in the paid artifact, but do
            # not publish it as verified when its source-linked ACK failed.
            latest_guide.parent.mkdir(parents=True, exist_ok=True)
            latest_guide.write_text(
                "# Warlock L10 — paid ACK not verified\n\n"
                "No source-linked native 100/100 L10 completion was verified. "
                "Inspect the preserved native route and "
                "ack_verification_error.json before any continuation.\n")
        elif native_guide.is_file():
            latest_guide.parent.mkdir(parents=True, exist_ok=True)
            latest_guide.write_bytes(native_guide.read_bytes())
        else:
            latest_guide.unlink(missing_ok=True)
        result = {
            "kind": "warlock_native_l10_root_range_v1", "from_level": 10,
            "end_level": end_level, "selected_engine_binary_sha256": engine_sha,
            "completed_new_levels": completed, "reused_levels": reused,
            "stopped": stopped, "next_level": next_level_number,
            "last_paid_route": str(latest_route), "last_paid_source": str(latest_source),
            "latest_guide": str(latest_guide) if latest_guide.is_file() else None,
            "full_10_60_native_replay_executed": False,
            "elapsed_10_60_seconds": None,
        }
        _write(out / "range_progress.json", result)
        return result

    def unverified_ack(exc: Exception) -> dict:
        nonlocal stopped
        # A producer can publish a route/guide without the complete original
        # native 100/100 source-linked ACK. Preserve those bytes and record the
        # exact forwarding/receipt-verification failure; never pay/advance it.
        reason = f"{type(exc).__name__}: {exc}"
        _write(paid_dir / "ack_verification_error.json", {
            "status": "PAID_ACK_UNVERIFIED", "level": 10, "error": reason,
            "native_binary_sha256": engine_sha,
            "selected_source_sha256": (
                next_level.sha256(source) if source.is_file() else None),
            "route": str(route),
        })
        stopped = {"level": 10, "status": "PAID_ACK_UNVERIFIED",
                   "route": str(route), "error": reason}
        return save(10)

    if route.is_file():
        try:
            paid_refusal = paid_range._cached_paid_refusal(route, 10)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return unverified_ack(exc)
        if paid_refusal:
            # Keep the original class of refusal on resumed runs rather than
            # converting a paid-driver exception into a Warcraft failure.
            refusal = next(row for row in json.loads(route.read_text())["native_refusals"]
                           if isinstance(row, dict) and row.get("level") == 10
                           and row.get("status"))
            stopped = {"level": 10, "status": refusal["status"], "route": str(route)}
            return save(10)
        try:
            next_level.verified_paid_predecessor(
                route=route, source=source, binary=binary, from_level=10)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return unverified_ack(exc)
        reused.append(10)
    else:
        proposal_file = proposal_dir / "proposal.json"
        if proposal_file.is_file():
            # A previous process may have written the native options/prepare
            # refusal before its guide. Resume that exact refused attempt
            # instead of asking Rust to repeat unchanged native work.
            proposal = json.loads(proposal_file.read_text())
            if (proposal.get("native_binary_sha256") != engine_sha
                    or proposal.get("original_template_sha256") != template_sha):
                raise ValueError("cached L10 proposal has mismatched native identity")
            if source.is_file():
                if (proposal.get("status") != "NATIVE_PREPARED_NOT_YET_PAID"
                        or proposal.get("selected_source_sha256") != next_level.sha256(source)):
                    raise ValueError("cached L10 prepared source has mismatched native identity")
            elif proposal.get("status") not in (
                    "NATIVE_OPTIONS_REFUSED", "NATIVE_PREPARE_REFUSED_ALL_SOURCES"):
                raise ValueError("cached L10 prepared proposal has no selected source")
        elif source.is_file():
            raise ValueError("cached L10 source has no native proposal receipt")
        else:
            proposal = propose_root(binary=binary, template=template,
                                    out=proposal_dir, max_proposals=max_proposals)
        if proposal["status"] != "NATIVE_PREPARED_NOT_YET_PAID":
            reason = json.dumps(proposal.get("native_refusals", []))[-3000:]
            _refusal_report(paid_dir, status=proposal["status"], reason=reason,
                            binary_sha=engine_sha, template_sha=template_sha)
            stopped = {"level": 10, "status": proposal["status"],
                       "proposal": str(proposal_dir / "proposal.json"),
                       "route": str(route)}
            return save(10)
        try:
            code = guide.main([
                "--execute-native", "--actor-level", "10",
                "--binary", str(binary), "--source", str(source),
                "--health-threshold", str(health_threshold),
                "--mana-threshold", str(mana_threshold),
                "--trial", f"native-l10-root-{key}",
                *(['--run-url', run_url] if run_url else []),
                "--out", str(paid_dir),
            ])
        except Exception as exc:
            # A transport/driver exception is not a native Warcraft refusal.
            # Keep it inspectable without granting paid credit or hiding CI failure.
            reason = f"{type(exc).__name__}: {exc}"
            _write(paid_dir / "driver_error.json", {
                "status": "PAID_DRIVER_ERROR", "error": reason, "actor_level": 10,
                "native_binary_sha256": engine_sha,
                "selected_source_sha256": next_level.sha256(source),
            })
            if not route.is_file():
                _refusal_report(paid_dir, status="PAID_DRIVER_ERROR", reason=reason,
                                binary_sha=engine_sha, template_sha=template_sha)
            stopped = {"level": 10, "status": "PAID_DRIVER_ERROR",
                       "route": str(route), "error": reason}
            return save(10)
        if code:
            if not route.is_file():
                # The producer must not silently drop the original failed attempt.
                # An absent receipt is a driver failure, not evidence of native refusal.
                reason = f"paid guide returned exit code {code} without route.json"
                _refusal_report(paid_dir, status="PAID_RECEIPT_MISSING", reason=reason,
                                binary_sha=engine_sha, template_sha=template_sha)
                stopped = {"level": 10, "status": "PAID_RECEIPT_MISSING",
                           "route": str(route), "error": reason}
            else:
                stopped = {"level": 10, "status": "NATIVE_PAID_REFUSAL",
                           "route": str(route)}
            return save(10)
        # A return code alone cannot establish a paid 100/100 root. Publish
        # a resumable machine/human refusal without overwriting native bytes.
        try:
            next_level.verified_paid_predecessor(
                route=route, source=source, binary=binary, from_level=10)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return unverified_ack(exc)
        completed.append(10)
    if end_level == 10:
        return save(11)
    remaining = max_new_levels - len(completed)
    if remaining == 0:
        stopped = {"level": 11, "status": "BOUNDED_NEW_LEVEL_BUDGET"}
        return save(11)
    child = paid_range.run(
        binary=binary, source=source, predecessor_route=route,
        out=out / "continuation", from_level=10, end_level=end_level,
        max_new_levels=remaining, max_proposals=max_proposals,
        health_threshold=health_threshold, mana_threshold=mana_threshold,
        run_url=run_url)
    completed.extend(child["completed_new_levels"])
    reused.extend(child["reused_levels"])
    stopped = child["stopped"]
    latest_route = Path(child["last_paid_route"])
    latest_source = Path(child["last_paid_source"])
    return save(child["next_level"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True,
                        help="Warlock source request shape only; NOT a paid predecessor")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--end-level", type=int, default=19)
    parser.add_argument("--max-new-levels", type=int, default=10)
    parser.add_argument("--max-proposals", type=int, default=30)
    parser.add_argument("--health-threshold", type=float, default=0.7)
    parser.add_argument("--mana-threshold", type=float, default=0.25)
    parser.add_argument("--run-url")
    result = run(**vars(parser.parse_args(argv)))
    print(json.dumps(result, indent=2))
    return 2 if result["stopped"] and result["stopped"]["status"] != "BOUNDED_NEW_LEVEL_BUDGET" else 0


if __name__ == "__main__":
    raise SystemExit(main())
