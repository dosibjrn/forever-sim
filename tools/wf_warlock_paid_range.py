#!/usr/bin/env python3
"""Resume a bounded Warlock paid native level range without replaying completed kills.

Forever/gsim schedules source-native options, preparation and 100-target world
scenarios; MythicSim alone executes Warcraft mechanics. Every level remains an
independently paid measurement, NOT a continuous L10-60 journey or an M1 gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Direct CLI invocation (python tools/...) must resolve the project root, too.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import wf_warlock_next_level_source as next_level
from tools import wf_warlock_route_guide as guide


REFUSALS = {
    "NATIVE_OPTIONS_REFUSED", "NATIVE_ACTOR_LEVEL_UNSUPPORTED",
    "NATIVE_PREPARE_REFUSED_ALL_PROPOSALS",
}


def _digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:20]


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _cached_paid_refusal(route: Path, level: int) -> bool:
    """Recognize a persisted native refusal without mistaking it for paid work.

    A failed native 100-target attempt can still publish route.json with the
    previous measured levels plus a new-level refusal. The file's existence
    alone is not a paid ACK. Only the same-level native refusal is resumable;
    malformed or mismatched paid receipts still go through strict verification.
    """
    report = _read(route)
    if report.get("class") != "warlock" or level in report.get("measured_levels", []):
        return False
    refusals = report.get("native_refusals", [])
    return isinstance(refusals, list) and any(
        isinstance(row, dict)
        and row.get("level") == level
        and isinstance(row.get("status"), str)
        and bool(row["status"])
        and row["status"] != "COMPLETED_100_REAL_NATIVE_GSIM_KILLS"
        for row in refusals
    )


def run(*, binary: Path, source: Path, predecessor_route: Path, out: Path,
        from_level: int, end_level: int, max_new_levels: int = 2,
        predecessor_binary_sha256: str | None = None,
        max_proposals: int = 30, health_threshold: float = 0.7,
        mana_threshold: float = 0.25, run_url: str | None = None) -> dict:
    if not 10 <= from_level < end_level <= 60:
        raise ValueError("expected increasing adjacent range within L10..60")
    if max_new_levels < 1 or max_proposals < 1:
        raise ValueError("paid range budgets must be positive")
    if not 0 < health_threshold <= 1 or not 0 < mana_threshold <= 1:
        raise ValueError("native Decisions thresholds must be in (0,1]")
    if run_url is not None and (
            not run_url.startswith("https://github.com/")
            or "/actions/runs/" not in run_url):
        raise ValueError("run_url must identify an actual GitHub Actions run")
    if not binary.is_file() or not source.is_file() or not predecessor_route.is_file():
        raise ValueError("binary, source and paid predecessor route must exist")
    out.mkdir(parents=True, exist_ok=True)
    engine_sha = next_level.sha256(binary)
    current_source, current_route = source, predecessor_route
    current_engine_sha = predecessor_binary_sha256
    new_levels = 0
    completed = []
    reused = []
    stopped = None
    progress_path = out / "range_progress.json"

    def stop_unverified(*, level: int, paid_dir: Path, paid_route: Path,
                        selected_source: Path, status: str, error: str) -> dict:
        """Keep a failed producer/ACK attempt inspectable and never pay it twice.

        This receipt describes Forever transport or publication, not a native
        Warcraft refusal. Never overwrite the original route or native guide.
        """
        nonlocal stopped
        paid_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "kind": "warlock_paid_range_unverified_v1", "level": level,
            "status": status, "error": error,
            "native_binary_sha256": engine_sha,
            "selected_source_sha256": next_level.sha256(selected_source),
        }
        error_path = paid_dir / "driver_error.json"
        error_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        error_guide = paid_dir / "DRIVER_ERROR_GUIDE.md"
        error_guide.write_text(
            f"# Warlock L{level}: {status}\n\n"
            f"Native paid 100/100 completion is **not verified**.\n\n"
            f"Forever producer/receipt error: {error}\n\n"
            "Preserve the original paid attempt and source; do not advance "
            "or repeat it without an explicit corrected attempt.\n"
        )
        stopped = {
            "level": level, "status": status, "error": error,
            "driver_error": str(error_path), "guide": str(error_guide),
            "route": str(paid_route) if paid_route.is_file() else None,
        }
        return save()

    def save() -> dict:
        # Every genuine native guide run writes a route.json and a GUIDE.md
        # together. Publish the latest human-facing guide beside range_progress
        # so artifact consumers need not know the content-addressed cache key.
        # A terminal native refusal has its own guide with the actual refusal;
        # never replace it with a falsely successful predecessor guide.
        published_route = current_route
        if stopped and stopped.get("route"):
            refusal_route = Path(stopped["route"])
            if refusal_route.is_file():
                published_route = refusal_route
        # An unverified payment must never republish the last successful
        # predecessor guide as though the new level were measured.
        native_guide = (Path(stopped["guide"])
                        if stopped and stopped.get("guide")
                        else published_route.with_name("GUIDE.md"))
        latest_guide = out / "GUIDE.md"
        if native_guide.is_file():
            tmp_guide = latest_guide.with_suffix(".tmp")
            tmp_guide.write_bytes(native_guide.read_bytes())
            tmp_guide.replace(latest_guide)
        else:
            # If a new invocation has no native guide, do not leave a
            # previous invocation's guide masquerading as this range result.
            latest_guide.unlink(missing_ok=True)
        result = {
            "kind": "warlock_native_paid_range_v1",
            "from_level": from_level, "end_level": end_level,
            "selected_engine_binary_sha256": engine_sha,
            "completed_new_levels": completed, "reused_levels": reused,
            # Completed and reused levels are stored in separate lists, not
            # chronological order. The continuation frontier is the highest
            # verified paid level, even when paid/reused levels interleave.
            "next_level": max(completed + reused, default=from_level) + 1,
            "stopped": stopped,
            "full_10_60_native_replay_executed": False,
            "elapsed_10_60_seconds": None,
            "last_paid_route": str(current_route),
            "last_paid_source": str(current_source),
            "latest_guide": str(latest_guide) if native_guide.is_file() else None,
        }
        tmp = progress_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        tmp.replace(progress_path)
        return result

    for level in range(from_level + 1, end_level + 1):
        predecessor = next_level.verified_paid_predecessor(
            route=current_route, source=current_source, binary=binary,
            from_level=level - 1,
            predecessor_binary_sha256=current_engine_sha)
        key = _digest({
            "predecessor": predecessor,
            "native_source": next_level.sha256(current_source),
            "binary": engine_sha,
            "level": level, "max_proposals": max_proposals,
            "health_threshold": health_threshold, "mana_threshold": mana_threshold,
            "recovery": "decisions", "target_count": 100,
            "hostile": True,
        })
        folder = out / f"L{level}" / key
        proposal_dir, paid_dir = folder / "proposal", folder / "paid"
        proposal_file = proposal_dir / "proposal.json"
        selected_source = proposal_dir / "source_request.json"
        paid_route = paid_dir / "route.json"

        proposal = _read(proposal_file) if proposal_file.is_file() else None
        if proposal is not None and (
                proposal.get("paid_predecessor") != predecessor
                or proposal.get("original_source_sha256") != next_level.sha256(current_source)
                or proposal.get("native_binary_sha256") != engine_sha):
            raise ValueError(f"cached L{level} proposal lacks exact predecessor identity")
        if proposal is not None and proposal.get("status") in REFUSALS:
            if not paid_route.is_file():
                guide.main(["--native-proposal", str(proposal_file),
                            "--baseline-observations", str(current_route),
                            "--out", str(paid_dir)])
            stopped = {"level": level, "status": proposal["status"],
                       "proposal": str(proposal_file), "route": str(paid_route)}
            return save()

        if proposal is None:
            if new_levels >= max_new_levels:
                stopped = {"level": level, "status": "BOUNDED_NEW_LEVEL_BUDGET"}
                return save()
            try:
                proposal = next_level.propose(
                    binary=binary, source=current_source, out=proposal_dir,
                    from_level=level - 1, to_level=level,
                    max_proposals=max_proposals,
                    predecessor_route=current_route,
                    predecessor_binary_sha256=current_engine_sha)
            except RuntimeError:
                # Native options/prepare refusal was already written by the
                # source proposer; publish it instead of faking paid results.
                if not proposal_file.is_file():
                    raise
                proposal = _read(proposal_file)
                if proposal.get("status") not in REFUSALS:
                    raise
            if proposal["status"] in REFUSALS:
                guide.main(["--native-proposal", str(proposal_file),
                            "--baseline-observations", str(current_route),
                            "--out", str(paid_dir)])
                stopped = {"level": level, "status": proposal["status"],
                           "proposal": str(proposal_file), "route": str(paid_route)}
                return save()
        if proposal.get("status") != "NATIVE_PREPARED_NOT_YET_PAID":
            raise ValueError(f"unexpected L{level} native proposal status")
        if (not selected_source.is_file()
                or proposal.get("selected_source_sha256") != next_level.sha256(selected_source)):
            raise ValueError(f"prepared L{level} source bytes do not match native proposal")

        # Resume a previously attempted but unverified native world without
        # silently re-paying it. The marker is scoped to exact predecessor,
        # selected source, binary, scenario and recovery by the cache key.
        error_path = paid_dir / "driver_error.json"
        if error_path.is_file():
            error = _read(error_path)
            if (error.get("kind") != "warlock_paid_range_unverified_v1"
                    or error.get("level") != level
                    or error.get("status") not in (
                        "PAID_DRIVER_ERROR", "PAID_RECEIPT_MISSING",
                        "PAID_ACK_UNVERIFIED")
                    or not isinstance(error.get("error"), str)
                    or not error["error"]
                    or error.get("native_binary_sha256") != engine_sha
                    or error.get("selected_source_sha256")
                    != next_level.sha256(selected_source)):
                raise ValueError(f"cached L{level} unverified paid error has mismatched identity")
            stopped = {
                "level": level, "status": error["status"],
                "error": error["error"],
                "driver_error": str(error_path),
                "guide": str(paid_dir / "DRIVER_ERROR_GUIDE.md"),
                "route": str(paid_route) if paid_route.is_file() else None,
            }
            return save()

        if paid_route.is_file():
            # A failed paid attempt also publishes route.json. Preserve its
            # actual native refusal on resume: neither pretend it was paid
            # nor re-execute an unchanged failed 100-target scenario.
            if _cached_paid_refusal(paid_route, level):
                stopped = {"level": level, "status": "NATIVE_PAID_REFUSAL",
                           "proposal": str(proposal_file), "route": str(paid_route)}
                return save()
            # A completed equivalent native run is permanently reusable: no
            # 'staleness' veto and no repeated 100-mob payment. Any malformed
            # or nonmatching measured receipt still fails strict verification.
            next_level.verified_paid_predecessor(
                route=paid_route, source=selected_source, binary=binary,
                from_level=level)
            reused.append(level)
        else:
            if new_levels >= max_new_levels:
                stopped = {"level": level, "status": "BOUNDED_NEW_LEVEL_BUDGET"}
                return save()
            try:
                code = guide.main([
                    "--execute-native", "--actor-level", str(level),
                    "--binary", str(binary), "--source", str(selected_source),
                    "--health-threshold", str(health_threshold),
                    "--mana-threshold", str(mana_threshold),
                    "--baseline-observations", str(current_route),
                    "--trial", f"paid-source-native-L{level}-{key}",
                    "--out", str(paid_dir),
                    *(['--run-url', run_url] if run_url else []),
                ])
            except Exception as exc:
                return stop_unverified(
                    level=level, paid_dir=paid_dir, paid_route=paid_route,
                    selected_source=selected_source, status="PAID_DRIVER_ERROR",
                    error=f"{type(exc).__name__}: {exc}")
            if code != 0:
                if not paid_route.is_file():
                    return stop_unverified(
                        level=level, paid_dir=paid_dir, paid_route=paid_route,
                        selected_source=selected_source,
                        status="PAID_RECEIPT_MISSING",
                        error=f"native guide exited {code} without route.json")
                stopped = {"level": level, "status": "NATIVE_PAID_REFUSAL",
                           "proposal": str(proposal_file), "route": str(paid_route)}
                return save()
            # Publication status 0 alone cannot certify a new measured level;
            # validate the exact persisted paid 100/100 receipt before advancing.
            try:
                next_level.verified_paid_predecessor(
                    route=paid_route, source=selected_source, binary=binary,
                    from_level=level)
            except (ValueError, TypeError, KeyError, OSError) as exc:
                return stop_unverified(
                    level=level, paid_dir=paid_dir, paid_route=paid_route,
                    selected_source=selected_source, status="PAID_ACK_UNVERIFIED",
                    error=f"{type(exc).__name__}: {exc}")
            completed.append(level)
            new_levels += 1
        current_source, current_route = selected_source, paid_route
        current_engine_sha = None  # successor was executed with this exact binary
        save()
    return save()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--predecessor-route", type=Path, required=True)
    parser.add_argument("--predecessor-binary-sha256")
    parser.add_argument("--from-level", type=int, required=True)
    parser.add_argument("--end-level", type=int, required=True)
    parser.add_argument("--max-new-levels", type=int, default=2)
    parser.add_argument("--max-proposals", type=int, default=30)
    parser.add_argument("--health-threshold", type=float, default=0.7)
    parser.add_argument("--mana-threshold", type=float, default=0.25)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-url",
                        help="Exact Actions URL for newly executed native paid levels; never relabel cached receipts")
    result = run(**vars(parser.parse_args(argv)))
    print(json.dumps(result, indent=2))
    return 2 if result["stopped"] and result["stopped"]["status"] not in (
        "BOUNDED_NEW_LEVEL_BUDGET",) else 0


if __name__ == "__main__":
    raise SystemExit(main())
