"""Read-only, source-honest simulation-result panels for paid native builds.

This is a standalone HTML fragment; all charts use inline SVG/CSS. Nothing is
re-simulated and data not present in genuine native raw receipts is never filled
with inferred damage/cast/buff values.
"""
from __future__ import annotations

from collections.abc import Mapping
from html import escape
from math import isfinite
from typing import Any


def h(value: Any) -> str:
    return escape('' if value is None else str(value), quote=True)


def num(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    value = float(value)
    return value if isfinite(value) else None


def fmt(value: Any, suffix: str = '', ndigits: int = 2) -> str:
    n = num(value)
    return f'{n:,.{ndigits}f}{suffix}' if n is not None else 'Not recorded'


def _tile(label: str, value: Any, note: str = '') -> str:
    return ('<div class="sim-tile"><small>' + h(label) + '</small>'
            '<strong>' + h(value) + '</strong>'
            + ('<span>' + h(note) + '</span>' if note else '') + '</div>')


def _missing(title: str, description: str) -> str:
    return ('<div class="sim-missing"><b>' + h(title) + '</b><p>'
            + h(description) + '</p></div>')


def _kill_events(sidecar: Mapping[str, Any], elapsed: float) -> list[tuple[float, str]]:
    kills = sidecar.get('world_kills')
    if not isinstance(kills, list):
        return []
    result: list[tuple[float, str]] = []
    for index, row in enumerate(kills, 1):
        if not isinstance(row, Mapping):
            return []
        nanos = row.get('world_kill_clock_ns')
        if type(nanos) is not int or nanos < 0:
            return []
        second = nanos / 1e9
        if second > elapsed + .01:
            return []
        target = row.get('target_id')
        if not isinstance(target, str) or not target:
            return []
        result.append((second, target))
    return result if len({t for _, t in result}) == len(result) else []


def _timeline(sidecar: Mapping[str, Any], elapsed: float) -> str:
    kills = _kill_events(sidecar, elapsed)
    term = sidecar.get('native_terminal_recovery')
    if not kills:
        return _missing('No per-kill timeline in this receipt',
                        'The build has a verified total elapsed time, but native kill timestamps are not stored in this artifact.')
    w, x0, plot = 920, 48, 815
    def xp(t: float) -> float:
        return x0 + min(1., max(0., t / elapsed)) * plot if elapsed > 0 else x0
    spans = ['<svg class="sim-timeline" viewBox="0 0 920 172" role="img" '
             'aria-label="Source-native kill timestamps and terminal recovery; not a spell-cast timeline">',
             '<line x1="48" y1="92" x2="863" y2="92" stroke="#687c98" stroke-width="3"/>',
             '<text x="48" y="138" class="sim-svg-text">0s</text>',
             '<text x="862" y="138" text-anchor="end" class="sim-svg-text">' + h(fmt(elapsed, ' s')) + '</text>']
    for index, (t, target) in enumerate(kills, 1):
        x = xp(t)
        label_y = 38 if index % 2 else 64
        spans.extend([
            '<line x1="' + f'{x:.2f}' + '" y1="92" x2="' + f'{x:.2f}' + '" y2="' + str(label_y + 7) + '" stroke="#b1a1f5" stroke-width="2"/>',
            '<circle cx="' + f'{x:.2f}' + '" cy="92" r="7" fill="#b1a1f5"/>',
            '<text x="' + f'{x:.2f}' + '" y="' + str(label_y) + '" text-anchor="middle" class="sim-svg-text">' + h(target) + '</text>',
            '<text x="' + f'{x:.2f}' + '" y="118" text-anchor="middle" class="sim-svg-sub">' + h(fmt(t, ' s', 2)) + '</text>',
        ])
    if isinstance(term, Mapping):
        start, end = term.get('start_clock_ns'), term.get('end_clock_ns')
        if (type(start) is int and type(end) is int and
                0 <= start <= end and end / 1e9 <= elapsed + .01 and
                end / 1e9 > start / 1e9):
            a, b = xp(start / 1e9), xp(end / 1e9)
            spans.insert(2, '<rect x="' + f'{a:.2f}' + '" y="83" width="' +
                         f'{b-a:.2f}' + '" height="18" rx="4" fill="#358f7b" opacity=".65"/>')
            spans.append('<text x="' + f'{(a+b)/2:.2f}' + '" y="158" text-anchor="middle" class="sim-svg-sub">Final recovery</text>')
    spans.append('</svg>')
    return ''.join(spans) + '<p class="section-desc">Markers are genuine world-lethal ACK clock times. Green segment is paid terminal restoration when its source clocks are available. No cast or damage-over-time events are interpolated.</p>'


def _world_row(label: str, value: Any) -> str:
    return '<tr><td>' + h(label) + '</td><td>' + h(value) + '</td></tr>'


def _world_breakdown(sidecar: Mapping[str, Any]) -> str:
    windows = sidecar.get('native_windows')
    if not isinstance(windows, list) or not windows:
        return _missing('Per-target world details not recorded',
                        'The source did not preserve comparable per-enemy native windows.')
    pieces = ['<div class="table-scroll"><table class="comparison sim-table"><thead><tr><th>Target</th><th>Native kill clock</th><th>Native damage*</th><th>HP at window</th><th>Mana at window</th></tr></thead><tbody>']
    for i, row in enumerate(windows, 1):
        if not isinstance(row, Mapping):
            continue
        tick = row.get('native_kill_ns')
        time = tick / 1e9 if type(tick) is int and tick >= 0 else None
        pieces.append('<tr><td>World target ' + str(i) + '</td><td>' + h(fmt(time, ' s')) +
                      '</td><td>' + h(fmt(row.get('native_damage'))) + '</td><td>' +
                      h(fmt(row.get('actor_health'))) + '</td><td>' +
                      h(fmt(row.get('actor_mana'))) + '</td></tr>')
    pieces.append('</tbody></table></div><p class="section-desc">*Native damage is a source diagnostic per fight window; it is not a per-spell damage breakdown and must not be equated with final 2D applied damage or target HP.</p>')
    return ''.join(pieces)


def _resource_rows(sidecar: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    raw = row.get('receipt') or {}
    term = sidecar.get('native_terminal_recovery')
    tr = term if isinstance(term, Mapping) else {}
    hp_before = tr.get('health_before')
    hp_after = tr.get('health_after', raw.get('terminal_hp'))
    mp_before = tr.get('mana_before')
    mp_after = tr.get('mana_after', raw.get('terminal_mana'))
    hp_max = tr.get('max_health', raw.get('terminal_max_hp'))
    mp_max = tr.get('max_mana', raw.get('terminal_max_mana'))
    values = [
        ('HP before final recovery', fmt(hp_before)),
        ('HP after final recovery', fmt(hp_after) + ' / ' + fmt(hp_max)),
        ('Mana before final recovery', fmt(mp_before)),
        ('Mana after final recovery', fmt(mp_after) + ' / ' + fmt(mp_max)),
        ('Water time between targets', fmt(sidecar.get('native_water_seconds_total'), ' s')),
        ('Water time at terminal recovery', fmt(tr.get('water_seconds'), ' s')),
        ('Mana regained from terminal water', fmt(tr.get('water_mana_gain'))),
        ('Food time between targets', fmt(sidecar.get('native_food_seconds_total'), ' s')),
        ('Final recovery duration', fmt(row.get('terminal_recovery_seconds'), ' s', 3)),
        ('2D route movement (paid)', fmt(sidecar.get('gsim_route_paid_movement_s'), ' s')),
    ]
    gains = sidecar.get('native_combat_mana_regen_actual_gain_by_target')
    if isinstance(gains, list) and gains and all(num(v) is not None for v in gains):
        values.append(('Combat mana regeneration by target', ', '.join(fmt(x) for x in gains)))
    return ('<div class="table-scroll"><table class="comparison sim-table"><thead><tr><th>Measured resource field</th><th>Source value</th></tr></thead><tbody>'
            + ''.join(_world_row(*p) for p in values) + '</tbody></table></div>')


def _settings(result: Mapping[str, Any], row: Mapping[str, Any], sidecar: Mapping[str, Any]) -> str:
    raw = row.get('receipt') or {}
    candidates = [
        ('Selected backend', result.get('backend') or 'Not recorded'),
        ('RNG', result.get('rng_mode') or 'Not recorded'),
        ('Native iterations', result.get('iterations')),
        ('Hostile targets', result.get('mob_count')),
        ('Target HP', sidecar.get('world_target_hp')),
        ('Engine binary SHA256', row.get('engine_binary_sha256')),
        ('Prepared request SHA256', row.get('source_request_sha256')),
        ('Original raw native JSON SHA256', raw.get('native_raw_receipt_sha256')),
    ]
    return ('<dl class="sim-settings">' + ''.join('<dt>' + h(k) + '</dt><dd>' + h(v if v is not None else 'Not recorded') + '</dd>' for k,v in candidates) + '</dl>')


def render_paid_simulation(result: Mapping[str, Any], row: Mapping[str, Any],
                           *, native_raw: Mapping[str, Any] | None = None) -> str:
    """Render actual independent-world metrics without claiming unsupported DPS/casts.

    native_raw must be already verified against its exact original raw receipt
    digest and native prepared source SHA by the caller. No file IO happens here.
    """
    raw = native_raw if isinstance(native_raw, Mapping) else {}
    total = num(row.get('native_elapsed_seconds'))
    if total is None or total <= 0:
        raise ValueError('NO_VALID_NATIVE_ELAPSED_TIME')
    terminal = num(row.get('terminal_recovery_seconds'))
    prior = total - terminal if terminal is not None and 0 <= terminal <= total else None
    has_raw = bool(raw)
    summary = ''.join([
        _tile('Charged world elapsed', fmt(total, ' s', 3), 'Two-target objective, not raid DPS'),
        _tile('Before terminal recovery', fmt(prior, ' s', 3), 'Includes any paid movement and between-target recovery'),
        _tile('Terminal full HP / mana', fmt(terminal, ' s', 3), 'Included in total elapsed'),
        _tile('Lethal ACKs', fmt((len(raw.get('world_kills')) if isinstance(raw.get('world_kills'), list) else None), '', 0) if has_raw else h((row.get('receipt') or {}).get('targets_killed')), 'Distinct 2D deaths when raw receipt available'),
    ])
    raw_badge = ('<span class="chip">Exact original 2D raw receipt checked</span>' if has_raw else
                 '<span class="chip">Raw 2D sidecar not bundled / digest not verified</span>')
    simsettings = _settings(result, row, raw)
    resbody = _resource_rows(raw, row) if has_raw else _missing('Detailed resource ledger unavailable', 'Only final paid HP/mana and duration in the ranked receipt are available. Include the matching original .native.json to show drinking, regeneration and movement.')
    worldbody = _world_breakdown(raw) if has_raw else _missing('Per-target damage not recorded here', 'The exact native world sidecar is needed for per-target diagnostic damage.')
    timeline = _timeline(raw, total) if has_raw else _missing('Timeline not recorded in this report', 'Exact raw .native.json is absent or does not match the source receipt digest. No kill times are invented.')
    return (
        '<section class="content" id="simulation"><div class="section-top"><h2>Simulation results</h2>' + raw_badge + '</div>'
        '<p class="section-desc">Native two-dimensional world / leveling objective. Lower seconds wins; this is not MythicSim single-target raid DPS.</p>'
        '<div class="sim-metrics">' + summary + '</div>'
        '<div class="sim-panels"><div class="panel"><h3>Fight timeline</h3>' + timeline + '</div>'
        '<div class="panel"><h3>Per-target native world windows</h3>' + worldbody + '</div></div></section>'
        '<section class="content" id="resources"><h2>Resources and recovery</h2>'
        '<p class="section-desc">Actual measured resource fields. Values marked Not recorded are absent in the exact native receipt, not zero.</p>' + resbody + '</section>'
        '<section class="content" id="damage"><h2>Ability damage, casts, buffs and debuffs</h2>'
        '<div class="sim-panels"><div class="panel"><h3>Ability damage / pet damage</h3>'
        + _missing('Per-spell damage not recorded', 'These native-paid 2D receipts do not contain a per-spell damage distribution, pet DPS or crit/miss breakdown. APL priorities are build instructions, not measured casts.') + '</div>'
        '<div class="panel"><h3>Cast timeline and buff/debuff uptime</h3>'
        + _missing('Actual casts and aura uptimes not recorded', 'The result does not include per-cast timestamps, proc activations or aura uptime intervals. No artificial timeline is generated.') + '</div></div>'
        '<p class="section-desc">DPS distributions / confidence intervals are unavailable for the single balanced native candidate evaluation; do not compare this report with 10,000-iteration raid DPS.</p></section>'
        '<section class="content" id="settings"><h2>Sim settings and evidence</h2>' + simsettings + '</section>'
    )


SIM_REPORT_CSS = '''
.sim-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}
.sim-tile{background:#172237;border:1px solid #34405b;border-radius:12px;padding:16px;min-width:0}
.sim-tile small,.sim-tile span{display:block;font-size:11px;color:#afbdd2}
.sim-tile strong{display:block;font-variant-numeric:tabular-nums;font-size:22px;line-height:1.35;color:#e5dfff;overflow-wrap:anywhere;margin:5px 0}
.sim-panels{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin-top:14px}
.sim-missing{border:1px dashed #495368;background:#151c2a;border-radius:9px;padding:15px;color:#b7c7d9;font-size:13px}
.sim-missing b{color:#f0c478;font-size:13px}.sim-missing p{margin:8px 0 0}
.sim-timeline{display:block;width:100%;max-width:100%;height:auto;background:#111827;border-radius:8px;margin:10px 0}
.sim-svg-text{font-size:20px;fill:#e4dff6;font-family:system-ui,sans-serif;font-weight:600}
.sim-svg-sub{font-size:15px;fill:#afbdd2;font-family:system-ui,sans-serif}
.sim-table{font-size:12px}.sim-settings{display:grid;grid-template-columns:minmax(130px,230px) minmax(0,1fr);gap:9px;font-size:12px}
.sim-settings dt{color:#aebbd0}.sim-settings dd{margin:0;overflow-wrap:anywhere;font-family:ui-monospace,monospace}
@media(max-width:960px){.sim-panels{grid-template-columns:1fr}.sim-metrics{grid-template-columns:repeat(2,1fr)}}
@media(max-width:520px){.sim-metrics{grid-template-columns:1fr 1fr}.sim-tile strong{font-size:17px}.sim-settings{grid-template-columns:1fr}}
'''