"""Offline, source-honest build guides with MythicSim-inspired information architecture.

Accepts ONLY already verified/paid native result rows from the shared optimizer.
No Warcraft stats, drops, raid DPS, icons or equipment legality are inferred.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from html import escape
from typing import Any, Mapping, Sequence
import json


def h(x: Any) -> str:
    return escape('' if x is None else str(x), quote=True)


def rjson(x: Any) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def names(row: Mapping[str, Any]) -> Mapping[str, Any]:
    labels = row.get('receipt', {}).get('native_named_build')
    return labels if isinstance(labels, Mapping) else {}


def trees(row: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    obj: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for t in names(row).get('talent_names') or []:
        if isinstance(t, Mapping):
            obj[str(t.get('tree') or 'Unknown tree')].append(t)
    return obj


def points(talents: Sequence[Mapping[str, Any]]) -> int:
    return sum(int(x.get('rank') or 0) for x in talents)


def spec(row: Mapping[str, Any]) -> str:
    by = trees(row)
    return max(by, key=lambda k: points(by[k])) if by else 'Specialization unreported'


def gear_rows(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [x for x in names(row).get('equipped_item_names_ids') or []
            if isinstance(x, Mapping) and type(x.get('item_id')) is int and x['item_id'] > 0]


def slot_label(raw: Any) -> str:
    named = {'back':'Back', 'feet':'Feet', 'wrist':'Wrists', 'hands':'Hands',
             'finger':'Ring', 'trinket':'Trinket', 'neck':'Neck', 'shoulder':'Shoulders',
             'waist':'Waist', 'two_hand':'Two-hand', 'main_hand':'Main hand',
             'off_hand':'Off hand', 'one_hand':'One hand', 'ranged':'Ranged',
             'head':'Head', 'chest':'Chest', 'legs':'Legs', 'shirt':'Shirt'}
    val = str(raw or '').lower()
    return named.get(val, val.replace('_', ' ').title()) if val else 'Unspecified'


def item_meta(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        val = item.get(key)
        if val is not None and val != '':
            return val
    return None


def equipment_warnings(gear: Sequence[Mapping[str, Any]]) -> list[str]:
    counts = Counter(str(i.get('native_slot') or '') for i in gear if i.get('native_slot'))
    clashes = [slot_label(key) for key, n in counts.items()
               if n > 1 and key not in ('finger','trinket')]
    combos = {str(i.get('native_slot')) for i in gear}
    if 'two_hand' in combos and ('off_hand' in combos or 'main_hand' in combos or 'one_hand' in combos):
        clashes.append('Two-hand and other weapon slot labels coexist')
    return (['Native item-slot metadata contains overlaps: ' + ', '.join(clashes)
             + '. These are input positions, not a certified equip-legal one-per-slot BiS set.']
            if clashes else [])


def gear_table(row: Mapping[str, Any]) -> str:
    gear = gear_rows(row)
    if not gear:
        return '<p class="empty">No source-labeled items in this native receipt.</p>'
    lines = []
    for item in gear:
        iid = item['item_id']
        slot = slot_label(item.get('native_slot'))
        name = item.get('name') or f'Native item {iid}'
        # A linked source lookup is optional; the report itself has zero network dependencies.
        url = f'https://www.wowhead.com/forever/item={iid}'
        lvl = item_meta(item,'item_level','ilvl')
        ench = item_meta(item,'enchant','enchant_name')
        src = item_meta(item,'source','drop_source','acquisition')
        note = ('Item level ' + h(lvl) if lvl is not None else 'Item level unavailable')
        if ench is not None:
            note += ' · ' + h(ench)
        lines.append(
            '<tr><td><div class="slothead"><span class="slotglyph" aria-hidden="true">'
            + h(slot[:1].upper()) + '</span><span>' + h(slot) + '<small>Input #'
            + h(item.get('position')) + '</small></span></div></td>'
            '<td><a class="item" href="' + h(url) + '" target="_blank" rel="noopener noreferrer">'
            + h(name) + '</a><small>' + note + ' · Item ID ' + h(iid) + '</small></td>'
            '<td class="source">' + (h(src) if src is not None else '<span class="unknown">Source not in receipt</span>')
            + '</td></tr>')
    return ('<div class="table-scroll"><table class="gear"><thead><tr>'
            '<th>Slot / native input</th><th>Item & details</th><th>Where to get it</th>'
            '</tr></thead><tbody>' + ''.join(lines) + '</tbody></table></div>')


def talent_section(row: Mapping[str, Any]) -> str:
    by = trees(row)
    if not by:
        return '<p class="empty">Talent names were not supplied by this native receipt.</p>'
    total = sum(points(v) for v in by.values())
    groups = []
    for tree, ts in by.items():
        n = points(ts)
        entries = ''.join('<li><span class="talent-symbol" aria-hidden="true">✧</span>'
                          '<span class="talent-name">' + h(t.get('name') or 'Unknown talent')
                          + '</span><b>' + h(t.get('rank')) + '/' + h(t.get('max_rank'))
                          + '</b></li>' for t in ts)
        groups.append('<section class="talent-tree"><div class="tree-title"><h3>'
                      + h(tree) + '</h3><span>' + str(n) + ' points</span></div>'
                      '<div class="meter"><span style="width:'
                      + str(round(n/max(total,1)*100,1)) + '%"></span></div><ul>'
                      + entries + '</ul></section>')
    return ('<div class="talent-summary"><span class="chip">Talent points: '
            + ' / '.join(str(points(x)) for x in by.values())
            + '</span><span class="raw-talents">' + h(row.get('talents'))
            + '</span></div><div class="tree-grid">' + ''.join(groups) + '</div>')


def cond_label(condition: Any) -> str:
    if condition is None:
        return 'Always / native default'
    if isinstance(condition, dict):
        neg = condition.get('not')
        if isinstance(neg, dict):
            spell = ((neg.get('val') or {}).get('dotIsActive') or {}).get('spellId')
            if isinstance(spell, dict) and 'spellId' in spell:
                return 'If DoT ' + str(spell['spellId']) + ' is not active'
    return rjson(condition)


def apl_section(row: Mapping[str, Any]) -> str:
    spells = names(row).get('ordered_apl_spells', [])
    if not spells:
        return '<p class="empty">Ordered native APL labels unavailable.</p>'
    items=[]
    for idx,s in enumerate(spells,1):
        if not isinstance(s,Mapping):continue
        rank = s.get('rank')
        items.append('<li class="rotation-row"><span class="priority">'
                     + h(s.get('priority') or idx) + '</span><span class="spell-icon" aria-hidden="true">✦</span>'
                     '<span class="spell-text"><strong>' + h(s.get('name') or 'Unknown native spell')
                     + '</strong><small>Spell ID ' + h(s.get('spell_id'))
                     + (' · ' + h(rank) if rank else ' · rank unavailable')
                     + '</small></span><span class="condition">'
                     + h(cond_label(s.get('condition'))) + '</span></li>')
    return '<ol class="rotation">' + ''.join(items) + '</ol>'


def hashes(row: Mapping[str, Any]) -> str:
    r=row.get('receipt') or {}
    values = [('Prepared source SHA256',row.get('source_request_sha256')),
              ('Exact binary SHA256',row.get('engine_binary_sha256')),
              ('Original paid receipt digest',r.get('native_raw_receipt_sha256')),
              ('Original receipt file',r.get('native_raw_receipt_file')),
              ('Native scorer status',r.get('status'))]
    return ('<dl class="hashes">' + ''.join('<dt>' + h(name) + '</dt><dd>'
            + h(val if val is not None else 'Unavailable') + '</dd>'
            for name,val in values) + '</dl>')


def top_comparison(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ''
    fastest=float(rows[0]['native_elapsed_seconds'])
    body=[]
    for i,row in enumerate(rows[:3],1):
        elapsed=float(row['native_elapsed_seconds'])
        delta=elapsed-fastest
        recovery=float(row['terminal_recovery_seconds'])
        body.append('<tr><td class="rank-num">#'+str(i)+'</td><td><b>'+h(spec(row))+'</b>'
                    '<small>'+h(row.get('talents'))+'</small></td><td>'+h(row.get('pet') or 'No pet')
                    +'</td><td><strong>'+f'{elapsed:.3f}'+' s</strong><small>'
                    +(f'+{delta:.3f} s vs #1' if delta else 'Fastest observed')
                    +'</small></td><td>'+f'{recovery:.3f}'+' s</td><td><a href="#alternative-'
                    +str(i)+'">View</a></td></tr>')
    return ('<div class="table-scroll"><table class="comparison"><thead><tr><th>Rank</th><th>Spec & talents</th>'
            '<th>Pet</th><th>Time incl. recovery</th><th>End recovery</th><th>Build</th>'
            '</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>')


def footer_faq(level:int,cls:str) -> str:
    questions = [
        ('Is this a true best-in-slot list?',
         'No. It is the fastest among the actually measured candidates for this one level and encounter. '
         'Native input slot labels are not proof of a complete equip-legal BiS set, nor are all gear drops verified.'),
        ('Why are item icons, item levels and sources missing?',
         'The stored paid optimization receipts include item IDs, names and native slot labels, '
         'but do not consistently include icon IDs, ilvl, enchants, faction, acquisition source or attributes. '
         'We do not silently copy Classic data into Forever or invent missing values.'),
        ('Why is there no raid DPS or 10,000-iteration number?',
         'This is a leveling comparison of two real hostile targets with balanced RNG and final HP/mana recovery. '
         'It is not the MythicSim level-60 raid-boss benchmark, and elapsed seconds are not raid DPS.'),
        ('Is the best build part of a proven leveling route?',
         'No. The character is prepared independently at this level. XP, travel, trainer visits, item acquisition, '
         'and a continuous no-respec path are not established by these paid candidate receipts.')]
    return ''.join('<details class="faq"><summary>'+h(k)+'</summary><p>'+h(v)+'</p></details>' for k,v in questions)


_CSS = '''
:root{color-scheme:dark;--bg:#0b0f17;--panel:#111827;--panel2:#162235;--line:#2b364a;--text:#f2f5ff;--muted:#acbad0;--purple:#b9adff;--gold:#f0c478;--green:#92dec5}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(ellipse at 20% -15%,#26234a 0,transparent 43%),var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}a{color:var(--purple)}
.site-head{border-bottom:1px solid var(--line);background:rgba(11,15,23,.95)}.nav-wrap,.wrap{max-width:1160px;margin:auto;padding:0 22px}.nav-wrap{min-height:64px;display:flex;align-items:center;justify-content:space-between;gap:14px}.logo{font-weight:850;letter-spacing:.13em;font-size:17px;color:#fff}.logo span{color:var(--gold)}.nav-mini{color:var(--muted);font-size:13px}
.wrap{padding-top:30px;padding-bottom:56px}.breadcrumb{color:var(--muted);font-size:13px;margin:3px 0 25px}.breadcrumb b{color:var(--purple)}.hero{display:flex;gap:20px;align-items:center;padding:5px 0 22px}.crest{width:74px;height:74px;border:1px solid #7062c2;border-radius:17px;background:linear-gradient(140deg,#453a7c,#1c273c);font-size:42px;display:grid;place-items:center;color:var(--gold);flex-shrink:0}
h1{font-size:clamp(29px,4.1vw,45px);line-height:1.15;margin:0 0 7px;font-weight:830;letter-spacing:-.025em}.subtitle{color:var(--muted);margin:0 0 12px}.engine{font-size:12px;color:var(--muted)}.eyebrow{color:var(--gold);text-transform:uppercase;font-size:11px;font-weight:800;letter-spacing:.15em}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin:13px 0 18px}.pill{background:#252442;border:1px solid #514989;border-radius:99px;padding:5px 11px;font-size:12px;color:#d8d1ff}.pill.warn{background:#3b2d1b;border-color:#72522a;color:#ffe0a2}
.metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:15px 0 24px}.metric{border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:15px;min-width:0}.metric b{display:block;font-size:25px;white-space:nowrap;font-variant-numeric:tabular-nums;line-height:1.25;color:var(--text)}.metric small{display:block;color:var(--muted);font-size:12px;margin-top:5px}
.callout{border-left:3px solid var(--gold);background:#27251f;color:#e6d8bd;border-radius:0 7px 7px 0;padding:14px 17px;margin:20px 0}.callout.danger{border-color:#e89977;background:#32231f}.section-nav{display:flex;flex-wrap:wrap;gap:16px;border-bottom:1px solid var(--line);margin:29px 0}.section-nav a{color:var(--muted);padding:0 0 12px;text-decoration:none;font-size:13px;font-weight:680}.section-nav a:hover{color:white}
section.content{margin:38px 0}.section-top{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap}.section-top h2,h2{font-size:25px;letter-spacing:-.02em;margin:0 0 11px}.muted{color:var(--muted)}.section-desc{font-size:13px;color:var(--muted);margin:0 0 15px}.table-scroll{overflow-x:auto}.gear,.comparison{width:100%;border-collapse:collapse;font-size:14px}.gear th,.comparison th{text-align:left;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em;background:#152034}.gear td,.gear th,.comparison td,.comparison th{padding:13px 12px;border-bottom:1px solid var(--line);vertical-align:middle}.gear tbody tr:nth-child(odd),.comparison tbody tr:nth-child(odd){background:rgba(19,28,43,.7)}.gear small,.comparison small{display:block;color:var(--muted);font-size:11px;margin-top:3px}.slothead{display:flex;align-items:center;gap:9px;min-width:120px}.slotglyph,.spell-icon,.talent-symbol{display:inline-grid;place-items:center;background:linear-gradient(145deg,#343064,#233346);border:1px solid #4a4b78;border-radius:7px;color:#cbbcff;flex:none}.slotglyph{width:36px;height:36px;font-size:14px;font-weight:800}.slothead small{font-size:10px}.item{font-weight:700;color:#c3b5ff;text-decoration:none}.item:hover{text-decoration:underline}.source{color:var(--muted)}.unknown{font-size:12px;color:#aeb7c8;font-style:italic}
.talent-summary{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:10px 0 17px}.chip{color:var(--gold);background:#2c2936;border:1px solid #514760;border-radius:99px;padding:5px 12px;font-size:12px}.raw-talents{font:12px ui-monospace,Consolas,monospace;color:var(--muted)}.tree-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.talent-tree{border:1px solid var(--line);background:var(--panel);padding:15px;border-radius:11px;min-width:0}.tree-title{display:flex;justify-content:space-between;gap:5px;align-items:center}.tree-title h3{font-size:17px;margin:0}.tree-title span{font-size:11px;color:var(--gold);white-space:nowrap}.meter{height:4px;background:#242d42;margin:11px 0 13px;border-radius:4px}.meter span{display:block;height:100%;background:var(--purple);border-radius:4px}.talent-tree ul{margin:0;padding:0;list-style:none}.talent-tree li{display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--line);padding:7px 0;font-size:12px}.talent-tree li:last-child{border:0}.talent-symbol{width:24px;height:24px;font-size:13px}.talent-name{flex:1;min-width:0}.talent-tree li b{font-variant-numeric:tabular-nums;color:#e6ddff;white-space:nowrap}
.duo{display:grid;grid-template-columns:1.25fr .75fr;gap:14px}.panel{border:1px solid var(--line);background:var(--panel);border-radius:11px;padding:17px;min-width:0}.panel h3{font-size:16px;color:var(--gold);margin:0 0 13px}.rotation{padding:0;margin:0;list-style:none}.rotation-row{display:flex;align-items:center;gap:9px;padding:10px 0;border-bottom:1px solid var(--line)}.rotation-row:last-child{border:0}.priority{color:#9caaca;font-size:12px;min-width:20px}.spell-icon{width:31px;height:31px}.spell-text{flex:1;min-width:0}.spell-text strong{font-size:13px}.spell-text small{display:block;font-size:11px;color:var(--muted)}.condition{font-size:11px;color:#c3d0e2;max-width:33%;overflow-wrap:anywhere}.panel p{font-size:13px}.pair-hero{font-size:23px;color:var(--green);font-weight:800}.policy pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;color:#c8d1df}
.comparison .rank-num{color:var(--gold);font-weight:800}.comparison strong{color:var(--green)}details{background:#151d2b;border:1px solid var(--line);border-radius:9px;margin:9px 0}summary{padding:12px 15px;cursor:pointer;font-weight:680;color:#d9d3ff}details .inside,details p{padding:2px 16px 15px;margin:0;font-size:13px;color:var(--muted)}.hashes{display:grid;grid-template-columns:minmax(120px,230px) minmax(0,1fr);gap:9px;font:11px ui-monospace,Consolas,monospace}.hashes dt{color:var(--muted)}.hashes dd{margin:0;overflow-wrap:anywhere}.empty{color:var(--muted);font-size:13px}footer{border-top:1px solid var(--line);padding:23px 0;color:var(--muted);font-size:12px}
@media(max-width:930px){.metrics{grid-template-columns:repeat(3,1fr)}.tree-grid{grid-template-columns:1fr}.duo{grid-template-columns:1fr}}@media(max-width:620px){.nav-wrap,.wrap{padding-left:13px;padding-right:13px}.hero{align-items:flex-start}.crest{width:55px;height:55px;font-size:30px}.metrics{grid-template-columns:repeat(2,1fr)}.section-nav{gap:12px}.gear,.comparison{min-width:610px}.condition{max-width:44%}.metric b{font-size:19px}.hashes{grid-template-columns:1fr}}
@media print{:root{color-scheme:light;--bg:#fff;--panel:#fff;--panel2:#fff;--line:#bbb;--text:#111;--muted:#444;--purple:#463586;--gold:#795100;--green:#165e40}body{background:#fff}.section-nav{display:none}details{break-inside:avoid}.site-head{display:none}}
'''


def render_reference_page(result: Mapping[str, Any], level: int, paid_rows: Sequence[Mapping[str, Any]], character_class: str,
                          *, native_raw: Mapping[str, Any] | None = None) -> str:
    """Render source-verified rows; validation belongs to existing _valid_rows()."""
    if not paid_rows:
        raise ValueError('NO_VERIFIED_NATIVE_PAID_WINNER_FOR_HTML_LEVEL_' + str(level))
    from tools.wf_native_paid_sim_report import SIM_REPORT_CSS, render_paid_simulation
    rows=sorted(paid_rows,key=lambda x:(x['native_elapsed_seconds'],x['source_request_sha256']))
    best=rows[0]
    cls=character_class.title()
    specialization=spec(best)
    enemy_count=result.get('mob_count')
    counted={axis:len({rjson(x.get(axis)) for x in rows}) for axis in ('talents','gear','apl','pet')}
    warnings=equipment_warnings(gear_rows(best))
    need_items=gear_rows(best)
    unlabeled=sum(1 for x in need_items if not item_meta(x,'source','drop_source','acquisition'))
    raw=best['receipt']
    showstat=lambda label,value: '<div class="metric"><b>'+h(value)+'</b><small>'+h(label)+'</small></div>'
    stats=''.join([showstat('Best measured time',f"{best['native_elapsed_seconds']:.3f} s"),
                   showstat('Real enemies',enemy_count),
                   showstat('Verified paid builds',len(rows)),
                   showstat('Measured gear sets',counted['gear']),
                   showstat('Measured pet choices',counted['pet'])])
    clsmark=h(cls[:1].upper())
    warning_markup=''.join('<aside class="callout danger"><strong>Gear verification needed.</strong> '+h(w)+'</aside>' for w in warnings)
    summary=(f'Best measured {cls} level {level} leveling build: {specialization}, '
             f'{best.get("pet") or "no summoned pet"}, {best["native_elapsed_seconds"]:.3f} seconds '
             f'for {enemy_count} native hostile kills with final HP/mana recovery included.')
    nav=''.join('<a href="#'+k+'">'+v+'</a>' for k,v in [
        ('simulation','Results & timeline'),('resources','Resources'),('damage','Damage & uptime'),
        ('gear','Gear'),('talents','Talents'),('play','Rotation & pet'),('compare','Top 3'),
        ('settings','Settings'),
        ('method','Methodology'),('faq','FAQ')])
    policy=raw.get('native_world_policy') or best.get('native_world_policy')
    recovery=best['terminal_recovery_seconds']
    mobs=raw.get('targets_killed')
    coverage = raw.get('native_options_coverage') or {}
    devnotes = '; '.join(str(v) for v in (coverage.get('notes') or [])) if isinstance(coverage, Mapping) else ''
    alternatives=''.join('<details id="alternative-'+str(i)+'"><summary>#'+str(i)
        +' '+h(spec(row))+' · '+h(row.get('pet') or 'No pet')+' · '
        +f'{row["native_elapsed_seconds"]:.3f}'+' s — expand exact build</summary><div class="inside">'
        +'<h3>Equipment</h3>'+gear_table(row)+'<h3>Talents</h3>'+talent_section(row)
        +'<h3>APL</h3>'+apl_section(row)+'<h3>Evidence</h3>'+hashes(row)
        +'</div></details>' for i,row in enumerate(rows[:3],1))
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>'+h(specialization)+' '+h(cls)+' L'+str(level)+' | Best tested native build</title>'
        '<style>'+_CSS+SIM_REPORT_CSS+'</style></head><body>'
        '<header class="site-head"><div class="nav-wrap"><div class="logo">FOREVER <span>SIM LAB</span></div>'
        '<div class="nav-mini">Native build research · Standalone report</div></div></header><main class="wrap">'
        '<div class="breadcrumb">WoW Forever &nbsp;›&nbsp; Builds &nbsp;›&nbsp; <b>'+h(cls)+'</b> &nbsp;›&nbsp; L'+str(level)+'</div>'
        '<section class="hero"><div class="crest" aria-label="Class initial">'+clsmark+'</div><div><p class="eyebrow">Native paid · Leveling results · Best tested</p>'
        '<h1>'+h(specialization)+' '+h(cls)+' · Level '+str(level)+'</h1>'
        '<p class="subtitle">'+h(summary)+'</p>'
        '<div class="engine">Balanced RNG · '+h(result.get('iterations'))+' iteration(s) per source candidate · Two-dimensional movement and paid recovery</div></div></section>'
        '<div class="pills"><span class="pill warn">Provisional · Not proven BiS</span><span class="pill">'+h(best.get('pet') or 'No pet')+'</span>'
        '<span class="pill">'+h(specialization)+'</span><span class="pill">'+h(result.get('backend') or 'Rust native')+'</span></div>'
        '<div class="metrics">'+stats+'</div>'
        '<aside class="callout"><strong>Best tested, not guaranteed BiS.</strong> This compares '+str(len(rows))
        +' actually paid builds for one independently prepared level. Unlike MythicSim’s reference page, this is <b>not</b> '
        'a level-60 raid DPS / pre-raid acquisition list. Source receipts do not include all item stat, source, icon or enchant metadata.</aside>'
        '<nav class="section-nav" aria-label="Report sections">'+nav+'</nav>'
        +render_paid_simulation(result, best, native_raw=native_raw)
        +'<section class="content" id="gear"><div class="section-top"><h2>Best tested gear</h2><span class="chip">'
        +str(len(need_items))+' source item positions</span></div>'
        '<p class="section-desc">Slot-labelled items from the winning native request. Item IDs link to a separate Wowhead Forever lookup; this HTML renders fully offline.</p>'
        +warning_markup+gear_table(best)
        +('<p class="section-desc">Acquisition source not supplied for '+str(unlabeled)+' / '+str(len(need_items))+' items. Item level, enchants and item artwork are likewise omitted unless explicitly sourced.</p>' if need_items else '')
        +'</section><section class="content" id="talents"><h2>Talents</h2><p class="section-desc">Points and ranks from the native prepared actor; this is not a visual recreation of the in-game grid.</p>'
        +talent_section(best)+'</section>'
        '<section class="content" id="play"><h2>Rotation and world policy</h2><div class="duo"><div class="panel"><h3>Native APL · ordered priorities</h3>'
        +apl_section(best)+'</div><div class="panel policy"><h3>Summon & recovery</h3><div class="pair-hero">'+h(best.get('pet') or 'No pet')+'</div>'
        '<p>Measured '+h(mobs)+' of '+h(enemy_count)+' hostile kills; final HP <strong>'+h(raw.get('terminal_hp'))+'/'+h(raw.get('terminal_max_hp'))
        +'</strong>, mana <strong>'+h(raw.get('terminal_mana'))+'/'+h(raw.get('terminal_max_mana'))+'</strong>.</p>'
        '<p>End recovery: <b>'+f'{recovery:.3f}'+' seconds</b> (already included in time).</p>'
        '<p class="muted">'+('Native World-APL policy:' if policy is not None else 'World policy not separately encoded in the receipt.')+'</p>'
        +('<pre>'+h(rjson(policy))+'</pre>' if policy is not None else '')+'</div></div></section>'
        '<section class="content" id="compare"><h2>Top three measured candidates</h2><p class="section-desc">Each entry below has its own exactly matched native source and binary identity, not a fabricated higher-level route.</p>'
        +top_comparison(rows)+alternatives+'</section>'
        '<section class="content" id="method"><h2>How this list is made</h2><p>Every ranked candidate was prepared by the selected native Rust source and evaluated against '
        +h(enemy_count)+' real hostile targets. The score is elapsed time including movement and the terminal full-health/full-mana restoration (not raid DPS). '
        'This report ranks only accepted source-native ACK, complete-resource receipts and checks that ranked build/source fields equal the original receipts.</p>'
        '<p>Measured proposal breadth: <b>'+str(counted['talents'])+'</b> talent allocations, <b>'+str(counted['apl'])
        +'</b> APLs, <b>'+str(counted['gear'])+'</b> gear sets, <b>'+str(counted['pet'])+'</b> pet choices. '
        'The finite candidate set does not certify optimality, learned level legality for every item, a compatible no-respec route, or item acquisition order.</p>'
        '<p class="section-desc">Unreported in stored receipts: item icon file names, many item levels, enchants, item sources and detailed stats; player race, client patch, raid DPS and stat weights. '
        +('Native source coverage notes: '+h(devnotes)+'.' if devnotes else '')+'</p>'
        '<details><summary>Native verification and traceability</summary><div class="inside">'+hashes(best)+'</div></details></section>'
        '<section class="content" id="faq"><h2>Frequently asked questions</h2>'+footer_faq(level,cls)+'</section>'
        '<footer>Standalone offline build report · Content from exact source-prepared and paid native World receipts · '
        'External item links are optional · Not affiliated with MythicSim or Blizzard. Reference layout inspired by MythicSim BiS information structure, not its source code.</footer>'
        '</main></body></html>\n')