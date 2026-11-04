"""Minimal M1 scoreboard: historical LIVE gate PASS stamps, never gate evidence.

Only wf_gate.py calls record_pass after the real production provider returns PASS.
This tool displays stored acceptance history; it never awards a new PASS.
"""
from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Also support the documented direct invocation: python tools/m1_progress.py
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.wf_gate_coverage import (measured_live_coverage,
                                    measured_p7_dps_proximity, pareto_effort_fraction)
LEDGER = ROOT / "docs/planning/M1_PASSES.tsv"
GATES = tuple(f"P{n}" for n in range(3, 7)) + tuple(f"P7.{n}" for n in range(1, 6))
RETIRED_GATES = frozenset(("P1", "P2"))
CLASSES = frozenset(("druid", "hunter", "mage", "paladin", "priest",
                     "rogue", "shaman", "warlock", "warrior"))
LEVELS = frozenset((20, 30, 40, 60))
PASS_FIELDS = ("class", "level", "spec", "gate", "passed_at_utc", "commit",
               "run_url", "compatibility_id")
FIELDS = PASS_FIELDS + ("status", "verified", "applicable", "scope_provisional",
                        "measured_at_utc")
TOTAL = 148 * len(GATES)  # 1332 active checkpoint-gate pairs; P1/P2 rows are historical only


def _key(row):
    return tuple(row[k] for k in ("class", "level", "spec", "gate"))


def _rows(path=LEDGER):
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        columns = tuple(reader.fieldnames or ())
        if columns not in (PASS_FIELDS, FIELDS):
            raise ValueError("M1 ledger schema mismatch")
        rows = {}
        for row in reader:
            if columns == PASS_FIELDS:  # historical PASS-only register
                row.update(status="PASS", verified="", applicable="",
                           scope_provisional="", measured_at_utc=row["passed_at_utc"])
            if (row["class"] not in CLASSES or int(row["level"]) not in LEVELS
                    or not re.fullmatch(r"[a-z][a-z0-9_-]*", row["spec"])
                    or (row["gate"] not in GATES and row["gate"] not in RETIRED_GATES)
                    or not re.fullmatch(r"[0-9a-f]{40}", row["commit"])
                    or row["status"] not in ("PASS", "PARTIAL")
                    or not row["measured_at_utc"]):
                raise ValueError("Invalid M1 measurement row: " + str(_key(row)))
            if row["status"] == "PASS" and not row["passed_at_utc"]:
                raise ValueError("PASS requires a real acceptance timestamp")
            if row["status"] == "PARTIAL":
                # Retired P1/P2 rows remain parseable history. Active P3-P6
                # record executed behavior; P7 records coupled live DPS / required DPS.
                if row["gate"].startswith("P7."):
                    n, d = float(row["verified"]), float(row["applicable"])
                    numeric_ok = math.isfinite(n) and math.isfinite(d)
                else:
                    n, d = int(row["verified"]), int(row["applicable"])
                    numeric_ok = True
                # 100% of a measured subcomponent can remain a gate FAIL.
                if not (numeric_ok and 0 < n <= d and d > 0
                        and not row["passed_at_utc"]
                        and row["scope_provisional"] in ("0", "1")):
                    raise ValueError("PARTIAL must have genuine bounded coverage")
            rows[_key(row)] = row  # latest verified measurement per gate
    return rows


def _write(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, delimiter="\t", fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows[k] for k in sorted(rows))
    temp.replace(path)


def record_pass(*, class_key, level, spec, gate, report, root=ROOT, path=LEDGER):
    """Called only after wf_gate._run_live_gate validates a real PASS."""
    if report.get("status") != "PASS" or report.get("reasons"):
        raise ValueError("Only an executed live PASS can be recorded")
    if class_key not in CLASSES or level not in LEVELS or gate not in GATES:
        raise ValueError("Not an M1 checkpoint/gate")
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", spec):
        raise ValueError("Invalid spec")
    row = _provenance(class_key, level, spec, gate, report, root)
    row.update(status="PASS", passed_at_utc=row["measured_at_utc"],
               verified="", applicable="", scope_provisional="")
    rows = _rows(path)
    if rows.get(_key(row), {}).get("status") == "PASS":
        return False  # An existing PASS is not retimestamped every run.
    rows[_key(row)] = row
    _write(rows, path)
    return True


def _provenance(class_key, level, spec, gate, report, root):
    sha = subprocess.check_output(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=root, text=True
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("No auditable git revision")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    run_url = (f"{os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/"
               f"{os.getenv('GITHUB_REPOSITORY', 'dosibjrn/forever-sim')}"
               f"/actions/runs/{run_id}") if run_id else ""
    proof = report.get("runtime_proof") or {}
    # Legacy TSV metadata only, never a checkpoint gate.
    compatibility = report.get("compatibility_id") or proof.get("compatibility_id") or ""
    return {"class": class_key, "level": str(level), "spec": spec, "gate": gate,
            "passed_at_utc": "", "commit": sha, "run_url": run_url,
            "compatibility_id": compatibility, "status": "", "verified": "",
            "applicable": "", "scope_provisional": "",
            "measured_at_utc": datetime.now(timezone.utc).isoformat()}


def record_partial(*, class_key, level, spec, gate, report, root=ROOT, path=LEDGER):
    """Record the best genuinely measured fraction, never exploration or samples.

    The authoritative gate runner makes this decision without agent grading.
    An observed 100% subcomponent may remain FAIL due to other gate clauses.
    Preserve historical best PARTIAL on a weaker run (and log regression).
    Invalidation handles a materially changed source/measurement contract.
    """
    if (class_key not in CLASSES or level not in LEVELS or gate not in GATES
            or not re.fullmatch(r"[a-z][a-z0-9_-]*", spec)):
        return False

    if gate.startswith("P7."):
        # P7 is a numerical objective, not count-based sample coverage.
        # Include a genuine executed BLOCKED-with-UI-audit-missing result.
        score = measured_p7_dps_proximity(gate, report)
        if score is None or report.get("status") not in ("FAIL", "BLOCKED"):
            return False
        n = min(float(score["dps_objective_actual"]),
                float(score["dps_objective_required"]))
        d = float(score["dps_objective_required"])
        provisional = True  # Numerical DPS proximity never certifies the gate.
    else:
        measured = measured_live_coverage(report)
        if measured is None or report.get("status") != "FAIL":
            return False
        n, d = report.get("pass_count"), report.get("reachability_count")
        if not (type(n) is int and type(d) is int and 0 < n <= d):
            return False
        provisional = measured["scope_provisional"]

    rows = _rows(path)
    row = _provenance(class_key, level, spec, gate, report, root)
    old = rows.get(_key(row))
    if old and old["status"] == "PASS":
        return False
    if old and old["status"] == "PARTIAL":
        old_ratio = float(old["verified"]) / float(old["applicable"])
        new_ratio = n / d
        if new_ratio <= old_ratio + 1e-12:
            # A failed new probe is visible in its Actions log, but cannot
            # silently erase a previously proven M1 high-water mark.
            if new_ratio < old_ratio - 1e-12:
                print(f"M1_REGRESSION_OR_SCOPE_CHANGE: {_key(row)} "
                      f"observed={new_ratio:.4f} best={old_ratio:.4f}")
            return False
        # A changed denominator may be a new or narrower test universe.
        # Don't allow shrinking scope to inflate a partial score, even when
        # its ratio is larger. Require more actual passing behaviors too.
        if old["applicable"] != str(d):
            if n < float(old["verified"]):
                print(f"M1_SCOPE_CHANGE_NOT_COMPARABLE: {_key(row)} "
                      f"old={old['verified']}/{old['applicable']} new={n}/{d}")
                return False
            provisional = True

    row.update(status="PARTIAL", verified=str(n), applicable=str(d),
               scope_provisional=str(int(provisional)))
    rows[_key(row)] = row
    _write(rows, path)
    return True



def merge_concurrent_gate_results(base_path, measured_path, latest_path, output_path):
    """Merge only the actually changed production gate receipts into fresh main.

    GitHub Actions can have concurrent, unrelated source-backed gate jobs.
    A newer main must not erase a separate accepted gate, nor can a stale
    PARTIAL downgrade a newer result. This merges existing TSV receipts only:
    no new score/probe, new evidence schema or invented gate acceptance.
    """
    before = _rows(base_path)
    measured = _rows(measured_path)
    latest = _rows(latest_path)
    if set(before) - set(measured):
        raise ValueError("M1_ACTION_CANNOT_AUTOMATICALLY_INVALIDATE_RECEIPTS")
    for key, row in measured.items():
        if before.get(key) == row:
            continue
        prior = latest.get(key)
        if prior is None:
            latest[key] = row
        elif prior["status"] == "PASS":
            continue
        elif row["status"] == "PASS":
            latest[key] = row
        elif row["status"] == "PARTIAL" and prior["status"] == "PARTIAL":
            n, d = float(row["verified"]), float(row["applicable"])
            old_n, old_d = float(prior["verified"]), float(prior["applicable"])
            # Keep best previously proven comparable component or objective.
            # A shrunk denominator with fewer successful behaviors is not
            # additional progress, and a stale run never erases a newer PASS.
            if n / d > old_n / old_d + 1e-12 and (
                    d == old_d or n >= old_n):
                latest[key] = row
    _write(latest, output_path)
    return latest


def scoreboard(path=LEDGER):
    rows = _rows(path)
    by_checkpoint = {}
    partials = []
    for row in rows.values():
        if row["gate"] not in GATES:
            continue  # Preserve retired P1/P2 receipts without counting them.
        if row["status"] == "PARTIAL":
            n, d = ((float(row["verified"]), float(row["applicable"]))
                    if row["gate"].startswith("P7.")
                    else (int(row["verified"]), int(row["applicable"])))
            c = n / d
            effort = pareto_effort_fraction(c)
            partials.append({"class": row["class"], "level": row["level"],
                             "spec": row["spec"], "gate": row["gate"],
                             "verified": n, "applicable": d, "coverage": c,
                             "pareto_effort": effort,
                             "provisional": row["scope_provisional"] == "1"})
        elif row["status"] == "PASS":
            key = (row["class"], row["level"], row["spec"])
            by_checkpoint.setdefault(key, []).append(row)
    # OVERALL PLAN: one unrestricted plus four Druid profiles / three others
    # at each of the four levels. No new profile may inflate the 1,332 total.
    if len(by_checkpoint) > 148:
        raise ValueError("More than 148 distinct M1 checkpoint identities")
    for class_key in CLASSES:
        for level in LEVELS:
            specs = {spec for (c, lev, spec) in by_checkpoint
                     if c == class_key and int(lev) == level}
            if len(specs) > (5 if class_key == "druid" else 4):
                raise ValueError("Too many M1 profiles for a class/level")
    # The nine real active gate PASSes are the whole checkpoint contract.
    # Source/runtime correctness belongs inside each gate's production runner.
    # An optional cross-gate metadata ID is not a tenth acceptance gate.
    certified = sum({r["gate"] for r in group} == set(GATES)
                    for group in by_checkpoint.values())
    accepted = sum(r["status"] == "PASS" and r["gate"] in GATES for r in rows.values())
    fractional = sum(x["coverage"] for x in partials)
    measured_fraction = (accepted + fractional) / TOTAL
    return {"passed_gates": accepted, "total_gates": TOTAL,
            "gate_percent": 100 * accepted / TOTAL,
            "measured_gate_equivalents": accepted + fractional,
            "measured_fraction": measured_fraction,
            "measured_percent": 100 * measured_fraction,
            "partial_gates": sorted(partials, key=lambda x:
                                    (x["class"], x["level"], x["spec"], x["gate"])),
            "certified_checkpoints": certified,
            "total_checkpoints": 148}



def render_history_svg(output, ledger=LEDGER):
    """README graph from versioned M1 TSV snapshots; never run acceptance here.

    One chart artifact, no time-series ledger: the normal git history of
    M1_PASSES.tsv is the entire time axis. Current uncommitted gate results
    become the last point so the recorder can commit ledger+SVG together.
    """
    import tempfile
    from xml.sax.saxutils import escape

    rel = Path(ledger).resolve().relative_to(ROOT).as_posix()
    log = subprocess.check_output(
        ["git", "log", "--format=%H%x09%cI", "--", rel],
        cwd=ROOT, text=True).splitlines()
    samples = []
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "m1.tsv"
        for line in reversed(log):
            sha, stamp = line.split("\t", 1)
            snapshot.write_bytes(subprocess.check_output(
                ["git", "show", f"{sha}:{rel}"], cwd=ROOT))
            score = scoreboard(snapshot)  # one canonical scoring implementation
            samples.append((datetime.fromisoformat(stamp).timestamp(), score))
    current = scoreboard(ledger)
    if (not samples or
            abs(samples[-1][1]["measured_percent"] - current["measured_percent"]) > 1e-10 or
            samples[-1][1]["passed_gates"] != current["passed_gates"] or
            samples[-1][1]["certified_checkpoints"] != current["certified_checkpoints"]):
        rows = _rows(ledger)
        stamp = max((row["measured_at_utc"] for row in rows.values()),
                    default=datetime.now(timezone.utc).isoformat())
        measured_time = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        samples.append((max(measured_time, samples[-1][0] if samples else 0), current))

    max_value = max([s["measured_percent"] for _, s in samples] +
                    [s["gate_percent"] for _, s in samples] + [0.005])
    raw_step = max_value * 1.18 / 4
    power = 10 ** math.floor(math.log10(raw_step))
    tick_step = next(v * power for v in (1, 2, 5, 10) if v * power >= raw_step)
    ceiling = math.ceil(max_value * 1.18 / tick_step) * tick_step
    x0, x1, y0, y1 = 90, 1050, 160, 400
    first = samples[0][0]
    last = samples[-1][0]
    x_at = lambda ts: (x0 + (x1 - x0) * (ts - first) / (last - first)
                       if last > first else (x0 + x1) / 2)
    y_at = lambda pct: y1 - (y1 - y0) * pct / ceiling
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="485" '
        'viewBox="0 0 1120 485" role="img" '
        'aria-label="M1 gate acceptance and measured partial progress over time">',
        '<rect width="1120" height="485" rx="16" fill="#111827"/>',
        '<text x="38" y="42" fill="#f9fafb" font-family="Arial,sans-serif" '
        'font-size="25" font-weight="bold">Forever Sim — M1 progress</text>',
        '<text x="38" y="70" fill="#9ca3af" font-family="Arial,sans-serif" '
        f'font-size="15">Git-verified active gate results · {TOTAL:,} gate targets · 148 checkpoints</text>',
        f'<text x="38" y="103" fill="#34d399" font-family="Arial,sans-serif" '
        f'font-size="19" font-weight="bold">PASS {current["passed_gates"]}/{TOTAL} '
        f'({current["gate_percent"]:.4f}%)</text>',
        f'<text x="355" y="103" fill="#fbbf24" font-family="Arial,sans-serif" '
        f'font-size="19" font-weight="bold">Measured {current["measured_percent"]:.4f}%</text>',
        f'<text x="785" y="103" fill="#f9fafb" font-family="Arial,sans-serif" '
        f'font-size="19" font-weight="bold">Certified {current["certified_checkpoints"]}/148</text>',
        '<text x="785" y="124" fill="#9ca3af" font-family="Arial,sans-serif" '
        'font-size="12">9 actual gate PASSes = 1 checkpoint</text>',
        '<line x1="39" y1="130" x2="67" y2="130" stroke="#34d399" stroke-width="3"/>',
        '<text x="75" y="135" fill="#d1d5db" font-family="Arial,sans-serif" font-size="14">'
        f'Full gate PASS (% of {TOTAL})</text>',
        '<line x1="350" y1="130" x2="378" y2="130" stroke="#fbbf24" stroke-width="3"/>',
        '<text x="386" y="135" fill="#d1d5db" font-family="Arial,sans-serif" font-size="14">'
        'Partial-inclusive diagnostic index (NOT PASS)</text>',
    ]
    for i in range(5):
        val = ceiling * i / 4
        y = y_at(val)
        svg.extend((
            f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" '
            'stroke="#374151" stroke-width="1"/>',
            f'<text x="{x0-12}" y="{y+5:.1f}" text-anchor="end" fill="#9ca3af" '
            f'font-family="Arial,sans-serif" font-size="13">{val:.3f}%</text>',
        ))
    for ts in sorted(set((first, (first + last) / 2, last))):
        x = x_at(ts)
        label = datetime.fromtimestamp(ts, timezone.utc).strftime("%d %b %H:%M")
        svg.extend((
            f'<line x1="{x:.1f}" y1="{y1}" x2="{x:.1f}" y2="{y1+6}" stroke="#6b7280"/>',
            f'<text x="{x:.1f}" y="{y1+25}" text-anchor="middle" fill="#9ca3af" '
            f'font-family="Arial,sans-serif" font-size="13">{escape(label)}</text>',
        ))
    for field, color in (("gate_percent", "#34d399"),
                         ("measured_percent", "#fbbf24")):
        coords = [(x_at(ts), y_at(score[field])) for ts, score in samples]
        parts = [f"M {coords[0][0]:.1f} {coords[0][1]:.1f}"]
        for x, y in coords[1:]:
            parts.extend((f"H {x:.1f}", f"V {y:.1f}"))
        svg.append(f'<path d="{" ".join(parts)}" fill="none" '
                   f'stroke="{color}" stroke-width="3" stroke-linejoin="round"/>')
        x, y = coords[-1]
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
    svg.extend((
        '<text x="40" y="472" fill="#9ca3af" font-family="Arial,sans-serif" '
        'font-size="13">UTC timeline from TSV Git commits · Y-axis zoomed to observed progress '
        '(starts at zero) · Historical measured best, not current regression status</text>',
        '</svg>',
    ))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="M1 live-PASS scoreboard (no gate reruns)")
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--invalidate", nargs=4, metavar=("CLASS", "LEVEL", "SPEC", "GATE"),
                        help="Remove a materially invalidated active PASS or PARTIAL receipt")
    parser.add_argument("--merge-snapshots", nargs=4, type=Path,
                        metavar=("BASE", "MEASURED", "LATEST", "OUTPUT"),
                        help="Actions CAS retry: merge changed gate receipts onto newest TSV")
    parser.add_argument("--plot-svg", type=Path,
                        help="Render Git-history M1 chart for README; does not rerun gates")
    args = parser.parse_args(argv)
    if args.merge_snapshots:
        merge_concurrent_gate_results(*args.merge_snapshots)
        return 0
    if args.invalidate:
        rows = _rows(args.ledger)
        del_key = tuple(args.invalidate)
        if del_key[-1] in RETIRED_GATES:
            parser.error("Retired P1/P2 history is immutable")
        if del_key not in rows:
            parser.error("No such active receipt to invalidate")
        del rows[del_key]
        _write(rows, args.ledger)
    if args.plot_svg:
        render_history_svg(args.plot_svg, args.ledger)
    result = scoreboard(args.ledger)
    print(f"M1 measured progress: {result['measured_percent']:.4f}% "
          f"(float={result['measured_fraction']:.10f}; diagnostic, NOT PASS)")
    print(f"M1: {result['passed_gates']}/{TOTAL} accepted gate runs "
          f"({result['gate_percent']:.2f}%)")
    print(f"Best-observed fractional gate coverage (NOT PASS): "
          f"{result['measured_gate_equivalents']:.3f}/{TOTAL} "
          f"({result['measured_percent']:.4f}%, provisional where noted)")
    for p in result["partial_gates"]:
        tentative = " [provisional scope]" if p["provisional"] else ""
        unit = "DPS objective" if p["gate"].startswith("P7.") else "verified"
        print(f"  {p['class']} L{p['level']} {p['spec']} {p['gate']}: "
              f"{p['verified']:g}/{p['applicable']:g} "
              f"({100 * p['coverage']:.1f}% {unit}, "
              f"{100 * p['pareto_effort']:.1f}% Pareto-modeled work){tentative}")
    print(f"Whole checkpoints: {result['certified_checkpoints']}/148; "
          f"{len(GATES)} real active PASS gates per checkpoint; no extra gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
