"""Render an offline standalone BiS-style page from verified native-paid builds.

All displayed results originate from the optimizer JSON and its native receipt.
No game legality, item stats, provenance, or route continuity is inferred.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from html import escape
import json
import math
from pathlib import Path
from typing import Any


def _h(value: Any) -> str:
    return escape(str(value) if value is not None else "", quote=True)


def _valid_rows(result: Mapping[str, Any], level: int) -> list[Mapping[str, Any]]:
    from src.v2.native_range_optimizer import _receipt_error

    rankings = result.get("independent_level_rankings")
    rows = rankings.get(str(level), []) if isinstance(rankings, Mapping) else []
    if not isinstance(rows, list):
        return []
    accepted: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw = row.get("receipt")
        if not isinstance(raw, Mapping) or _receipt_error(
            raw, level=level, parent=None,
            mob_count=result.get("mob_count"), rng_mode=result.get("rng_mode"),
            iterations=result.get("iterations"),
        ) is not None:
            continue
        if any(row.get(field) != raw.get(field) for field in (
            "source_request_sha256", "engine_binary_sha256",
            "talents", "gear", "apl", "pet"
        )):
            continue
        if (not isinstance(row.get("native_elapsed_seconds"), (int, float))
                or not math.isclose(row["native_elapsed_seconds"],
                                    raw["elapsed_seconds"], abs_tol=1e-6)
                or not isinstance(row.get("terminal_recovery_seconds"), (int, float))
                or not math.isclose(row["terminal_recovery_seconds"],
                                    raw["terminal_recovery_seconds"], abs_tol=1e-6)):
            continue
        accepted.append(row)
    return sorted(accepted, key=lambda x: (
        x["native_elapsed_seconds"], x["source_request_sha256"]))


def _axis_counts(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    return {
        field: len({json.dumps(x.get(field), sort_keys=True) for x in rows})
        for field in ("gear", "pet", "apl", "talents")
    }


def _named_build(row: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = row.get("receipt") or {}
    label = raw.get("native_named_build")
    return label if isinstance(label, Mapping) else {}


def _spec(labels: Mapping[str, Any]) -> str:
    points: dict[str, int] = defaultdict(int)
    for talent in labels.get("talent_names") or []:
        if isinstance(talent, Mapping):
            points[str(talent.get("tree") or "Unspecified")] += int(
                talent.get("rank") or 0)
    return max(points, key=points.get) if points else "Unspecified"


def _equipment(labels: Mapping[str, Any]) -> str:
    rows = []
    for item in labels.get("equipped_item_names_ids") or []:
        if not isinstance(item, Mapping) or item.get("item_id") in (None, 0):
            continue
        # Prefer Rust's actual item slot over assuming a particular ordering.
        slot = item.get("native_slot") or ("position " + str(item.get("position")))
        rows.append(
            "<tr><td class='slot'>" + _h(str(slot).replace("_", " ").title())
            + "</td><td><strong>" + _h(item.get("name") or "Unknown name")
            + "</strong><span class='sub'>Item ID "
            + _h(item.get("item_id")) + "</span></td></tr>"
        )
    return ("<table><thead><tr><th>Slot (native)</th><th>Equipped item</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
            if rows else "<p class='muted'>Native item names unavailable.</p>")


def _talents(labels: Mapping[str, Any], allocation: Any) -> str:
    by_tree: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for t in labels.get("talent_names") or []:
        if isinstance(t, Mapping):
            by_tree[str(t.get("tree") or "Unknown")].append(t)
    output = ["<p class='mono'>Allocation: " + _h(allocation) + "</p>"]
    for tree, ts in by_tree.items():
        pts = sum(int(t.get("rank") or 0) for t in ts)
        output.append("<h4>" + _h(tree) + " <span class='muted'>"
                      + str(pts) + " points</span></h4><ul class='entries'>")
        for t in ts:
            output.append("<li><span>" + _h(t.get("name") or "Native talent")
                          + "</span><strong>" + _h(t.get("rank")) + "/"
                          + _h(t.get("max_rank")) + "</strong></li>")
        output.append("</ul>")
    if not by_tree:
        output.append("<p class='muted'>Native talent names unavailable.</p>")
    return "".join(output)


def _apl(labels: Mapping[str, Any]) -> str:
    spells = labels.get("ordered_apl_spells") or []
    lines = []
    for s in spells:
        if not isinstance(s, Mapping):
            continue
        label = _h(s.get("name") or "Native spell")
        rank = " · rank " + _h(s["rank"]) if s.get("rank") else ""
        condition = (json.dumps(s.get("condition"), sort_keys=True)
                     if s.get("condition") is not None else "always")
        lines.append("<li><span><strong>" + label + "</strong><span class='sub'>"
                     + "Spell " + _h(s.get("spell_id")) + rank
                     + "</span></span><code>" + _h(condition) + "</code></li>")
    return ("<ol class='apl'>" + "".join(lines) + "</ol>" if lines
            else "<p class='muted'>Native APL labels unavailable.</p>")


def _candidate_card(row: Mapping[str, Any], place: int) -> str:
    labels = _named_build(row)
    raw = row["receipt"]
    total = float(row["native_elapsed_seconds"])
    rest = float(row["terminal_recovery_seconds"])
    policy = raw.get("native_world_policy") or row.get("native_world_policy")
    policy_text = (json.dumps(policy, ensure_ascii=False, sort_keys=True)
                   if policy is not None else
                   "Not separately reported; see source-native receipt")
    return (
        "<article class='candidate' id='build-" + str(place) + "'>"
        "<div class='candidate-head'><div><span class='eyebrow'>Rank "
        + str(place) + " · native paid</span><h2>"
        + _h(_spec(labels)) + " · " + _h(row.get("pet") or "No summoned pet")
        + "</h2></div><div class='big-time'>" + f"{total:.3f}"
        + "<small>seconds / " + _h(raw.get("mob_count"))
        + " kills</small></div></div>"
        "<div class='metric-strip'><div>Terminal HP <strong>"
        + _h(raw.get("terminal_hp")) + " / " + _h(raw.get("terminal_max_hp"))
        + "</strong></div><div>Terminal mana <strong>"
        + _h(raw.get("terminal_mana")) + " / " + _h(raw.get("terminal_max_mana"))
        + "</strong></div><div>Paid final recovery <strong>"
        + f"{rest:.3f}" + " s</strong></div></div>"
        "<div class='detail-grid'><section><h3>Gear</h3>"
        + _equipment(labels) + "</section><section><h3>Talents</h3>"
        + _talents(labels, row.get("talents")) + "</section></div>"
        "<section><h3>Ordered APL</h3>" + _apl(labels) + "</section>"
        "<section><h3>World pull & recovery policy</h3><pre>"
        + _h(policy_text) + "</pre></section>"
        "<details><summary>Native verification and traceability</summary>"
        "<dl class='hashes'><dt>Prepared source SHA-256</dt><dd>"
        + _h(row.get("source_request_sha256"))
        + "</dd><dt>Engine binary SHA-256</dt><dd>"
        + _h(row.get("engine_binary_sha256"))
        + "</dd><dt>Original native receipt SHA-256</dt><dd>"
        + _h(raw.get("native_raw_receipt_sha256") or "Not supplied")
        + "</dd><dt>Original receipt location</dt><dd>"
        + _h(raw.get("native_raw_receipt_file") or "Not supplied")
        + "</dd><dt>Native receipt status</dt><dd>"
        + _h(raw.get("status")) + "</dd></dl></details></article>"
    )


_CSS = """
:root{color-scheme:dark;--bg:#0e121c;--panel:#181f2d;--soft:#222c3c;--line:#384455;
--txt:#f2f5fa;--muted:#aebbd0;--gold:#e8bf6c;--green:#86d9b6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1160px;margin:auto;padding:32px 22px 65px}
.eyebrow{font-size:.79rem;letter-spacing:.1em;text-transform:uppercase;color:var(--gold);
font-weight:750}h1{font-size:clamp(2rem,4vw,3.5rem);line-height:1.1;margin:.5rem 0 1rem}
h2{font-size:1.55rem;margin:.5rem 0}h3{font-size:1.12rem;margin:0 0 12px;color:var(--gold)}
h4{font-size:1rem;margin:20px 0 8px}.muted,.sub{color:var(--muted)}
.sub{display:block;font-size:.78rem}.hero{padding:25px 0 35px}
.hero p{max-width:760px;color:var(--muted);font-size:1.05rem}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;margin:18px 0 25px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}
.stat strong{display:block;font-size:1.55rem;font-variant-numeric:tabular-nums;color:var(--green)}
.stat span{font-size:.85rem;color:var(--muted)}
.note{border-left:4px solid var(--gold);background:var(--soft);padding:13px 18px;
border-radius:0 10px 10px 0;margin:16px 0 25px}
nav{display:flex;gap:12px;flex-wrap:wrap;margin:25px 0}
nav a{color:var(--txt);border:1px solid var(--line);border-radius:8px;
padding:8px 12px;text-decoration:none;background:var(--panel)}
.candidate{border:1px solid var(--line);border-radius:14px;background:var(--panel);
padding:25px;margin:23px 0}
.candidate-head{display:flex;align-items:center;justify-content:space-between;gap:20px}
.big-time{font-size:2rem;font-weight:800;font-variant-numeric:tabular-nums;color:var(--green)}
.big-time small{display:block;font-size:.77rem;text-align:right;color:var(--muted)}
.metric-strip{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 24px}
.metric-strip>div{border-radius:8px;background:var(--soft);padding:9px 13px;color:var(--muted)}
.metric-strip strong{color:var(--txt)}
.detail-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:24px;margin:18px 0}
section{min-width:0;margin:23px 0}table{width:100%;border-collapse:collapse}
th,td{padding:10px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:.85rem;color:var(--muted)}.slot{width:32%;color:var(--muted)}
.entries,.apl{margin:8px 0;padding:0;list-style:none}
.entries li,.apl li{display:flex;justify-content:space-between;gap:8px;
padding:7px 0;border-bottom:1px solid var(--line)}
.apl li{align-items:start}.apl code{max-width:52%;overflow-wrap:anywhere;
font-size:.76rem;color:var(--muted);text-align:right}
.mono,code,pre,.hashes{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--soft);
padding:12px;border-radius:9px}
details{border-top:1px solid var(--line);padding-top:16px;margin-top:25px}
summary{cursor:pointer;color:var(--gold)}
.hashes{display:grid;grid-template-columns:minmax(120px,220px) minmax(0,1fr);gap:10px}
.hashes dt{color:var(--muted)}.hashes dd{margin:0;overflow-wrap:anywhere}
footer{font-size:.82rem;color:var(--muted);padding-top:25px}
@media(max-width:780px){.stats{grid-template-columns:repeat(2,1fr)}
.detail-grid{grid-template-columns:1fr}.candidate-head{align-items:start;
flex-direction:column}.big-time small{text-align:left}.hashes{grid-template-columns:1fr}
.wrap{padding:24px 14px}.candidate{padding:16px}}
@media print{ :root{color-scheme:light;--bg:#fff;--panel:#fff;--soft:#f4f4f4;
--line:#bbb;--txt:#111;--muted:#555;--gold:#67511e;--green:#146a43}
nav{display:none}.candidate{break-inside:avoid}body{font-size:12px}}
"""


def render_native_paid_html(result: Mapping[str, Any], *, level: int) -> str:
    """HTML with all styles embedded, no external assets or JavaScript.

    Refuse to invent a winner when no original fully paid receipt qualifies.
    """
    if type(level) is not int:
        raise ValueError("level must be an integer")
    rows = _valid_rows(result, level)
    if not rows:
        raise ValueError("NO_VERIFIED_NATIVE_PAID_WINNER_FOR_HTML_LEVEL_" + str(level))
    breadth = _axis_counts(rows)
    top = rows[0]
    m = result.get("mob_count")
    cards = "".join(_candidate_card(row, i) for i, row in enumerate(rows[:3], 1))
    summary = "".join(
        "<div class='stat'><strong>" + str(breadth[axis]) +
        "</strong><span>Measured " + label + "</span></div>"
        for axis, label in (
            ("gear", "gear sets"), ("pet", "pet choices"),
            ("apl", "APL policies"), ("talents", "talent allocations")
        )
    )
    nav = "".join(
        "<a href='#build-" + str(i) + "'>#" + str(i) + " · "
        + f"{row['native_elapsed_seconds']:.3f}" + " s</a>"
        for i, row in enumerate(rows[:3], 1)
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>WoW Forever Warlock L" + str(level)
        + " — Best Tested Native Builds</title><style>" + _CSS + "</style>"
        "</head><body><main class='wrap'>"
        "<header class='hero'><div class='eyebrow'>WoW Forever / Native optimization / "
        "Best tested · Offline report</div><h1>Warlock · Level " + str(level)
        + "</h1><p>Best measured leveling builds from the actual Rust / 2D world "
        "simulator. Gear, talents, summoned pet and APL are shown exactly as "
        "prepared and measured, with fully clock-paid end recovery.</p></header>"
        "<div class='stats'>" + summary + "</div>"
        "<div class='note'><strong>Best tested, not guaranteed BiS.</strong> "
        + str(len(rows)) + " fully paid candidate(s); "
        + _h(m) + " native hostile kill(s) per candidate. "
        "These are independent level snapshots—not a continuous leveling route, "
        "a global item search, or proof of PvP performance. "
        "A fixed or absent axis is not an optimized axis.</div>"
        "<p class='muted'>Fastest measured build: <strong>"
        + f"{top['native_elapsed_seconds']:.3f} s" + "</strong>. "
        "Only original native-paid, two-target ACK and full-HP/mana receipt "
        "records are eligible for ranking.</p><nav aria-label='Top three builds'>"
        + nav + "</nav>" + cards
        + "<footer>Reproducibility: see each build's exact source SHA, engine "
        "SHA, raw receipt digest and policy. Generated from existing optimizer "
        "JSON without any new simulation, external dependencies, or browser "
        "network requests. Not affiliated with Blizzard Entertainment or MythicSim."
        "</footer></main></body></html>\n"
    )


def write_native_paid_html_reports(
    result: Mapping[str, Any], out_dir: Path, *, class_name: str = "warlock",
) -> list[Path]:
    out_dir = Path(out_dir)
    pages = []
    for level in result.get("sampled_levels_requested", []):
        if not _valid_rows(result, level):
            continue
        page = render_native_paid_html(result, level=level)
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / (class_name.lower() + "-l" + str(level) + "-best-tested.html")
        dest.write_text(page, encoding="utf-8")
        pages.append(dest)
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish independent offline HTML from saved native-paid JSON (no Rust run)")
    parser.add_argument("--in", dest="source", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = json.loads(args.source.read_text(encoding="utf-8"))
    pages = write_native_paid_html_reports(
        result, args.out_dir, class_name=result.get("class") or "warlock")
    for page in pages:
        print("WROTE_NATIVE_PAID_HTML", page)
    return 0 if pages else 2


if __name__ == "__main__":
    raise SystemExit(main())
