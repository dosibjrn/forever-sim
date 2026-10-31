"""Source-hash-bound spell-detail effect slots, not a spell/action allowlist.

Wowhead's structured #spelldetails table contains independent effect slots and
exact periodic tick intervals which are *not* present in many listview texts.
Parse ALL slots, including unknown ones, and fail closed on structural drift.
No row in this ledger is proof of acquisition, target legality or a complete
L2 action.  Never replace an unsupported slot with a silent no-op.
"""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path
from bs4 import BeautifulSoup
from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot
from .source_ingest_blockers import SCHEMA as BLOCKER_SCHEMA, reason as blocker_reason, read_blocker

SCHEMA = '''CREATE TABLE IF NOT EXISTS verified_spell_detail_effect_slots (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, slot INTEGER NOT NULL,
 index_batch_id TEXT NOT NULL, index_payload_sha256 TEXT NOT NULL,
 detail_html_sha256 TEXT NOT NULL, source_url TEXT NOT NULL,
 effect_label TEXT NOT NULL, effect_text TEXT NOT NULL,
 typed_kind TEXT NOT NULL, values_json TEXT NOT NULL,
 execution_status TEXT NOT NULL,
 PRIMARY KEY(class_key,spell_id,slot))'''
META = '''CREATE TABLE IF NOT EXISTS verified_spell_detail_effect_headers (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
 index_batch_id TEXT NOT NULL, index_payload_sha256 TEXT NOT NULL,
 detail_html_sha256 TEXT NOT NULL, source_url TEXT NOT NULL,
 headers_json TEXT NOT NULL, flags_json TEXT NOT NULL,
 effect_slots INTEGER NOT NULL, supported_slots INTEGER NOT NULL,
 execution_status TEXT NOT NULL,
 PRIMARY KEY(class_key,spell_id))'''
_STATUS='BLOCKED_PARTIAL_VERIFIED_EFFECT_NOT_COMPLETE_L2'
_NUMBER=r'([+-]?\d+(?:\.\d+)?)'
_VALUE=re.compile(r'\bValue:\s*'+_NUMBER+r'\b',re.I)
_PERIODIC=re.compile(r'\bValue:\s*'+_NUMBER+r'\s+every\s+(\d+(?:\.\d+)?)\s+seconds?\b',re.I)
_COEF=re.compile(r'\bSP mod:\s*'+_NUMBER+r'\b',re.I)
_DURATION=re.compile(r'^(\d+(?:\.\d+)?)\s+(seconds?|minutes?|hours?)$',re.I)
_SCHOOL_DAMAGE=re.compile(r'^School Damage\s*\(([^()]+)\)$',re.I)
_POWER_GAIN=re.compile(r'^Give Power\s*\(([^()]+)\)$',re.I)
_ABSORB_DAMAGE=re.compile(r'^Apply Aura: Absorb Damage\s*\(([^()]*)\)$',re.I)
_MOVEMENT_SLOW='Apply Aura: Decrease Run Speed %'
_ALL_SCHOOLS=frozenset({'arcane','fire','frost','holy','nature','physical','shadow'})



def _time(value: str) -> float | None:
    m=_DURATION.fullmatch(value)
    if not m:return None
    scale={'second':1,'minute':60,'hour':3600}[m[2].lower().rstrip('s')]
    result=float(m[1])*scale
    return result if result>0 else None


def parse_detail_effects(html: str) -> dict:
    """Typed observations only; preserve exact ordered unsupported effects."""
    soup=BeautifulSoup(html,'html.parser')
    tables=soup.select('table#spelldetails')
    if len(tables)!=1:
        raise ValueError('MISSING_OR_AMBIGUOUS_STRUCTURED_SPELL_DETAILS')
    rows=tables[0].find('tbody',recursive=False)
    if rows is None:raise ValueError('MISSING_SPELL_DETAILS_TBODY')
    headers={};flags=[];effects=[]
    for tr in rows.find_all('tr',recursive=False):
        th=tr.find('th',recursive=False)
        td=tr.find('td',recursive=False)
        if th is None or td is None:continue
        label=th.get_text(' ',strip=True)
        if label=='Flags':
            flags=[li.get_text(' ',strip=True) for li in td.select('li')]
            continue
        if re.fullmatch(r'Effect(?:\s+#\d+)?',label):
            expected=int(label.split('#')[1]) if '#' in label else 1
            if expected!=len(effects)+1:
                raise ValueError('NONCONTIGUOUS_SOURCE_EFFECT_SLOTS')
            small=td.find('small',recursive=False)
            # Triggered-spell links can use a nested icon table instead of <small>.
            # Preserve these as unsupported; never silently discard the slot.
            effect_type=' '.join(str(c).strip() for c in td.contents
                                 if isinstance(c,str) and str(c).strip())
            effect_type=' '.join(effect_type.split())
            body=' '.join((small.get_text(' ',strip=True) if small is not None else td.get_text(' ',strip=True)).split())
            values={};kind='unsupported'
            periodic=_PERIODIC.search(body)
            value=_VALUE.search(body)
            coef=_COEF.search(body)
            if coef:values['spell_power_coefficient_per_tick_or_effect']=float(coef[1])
            school_match=_SCHOOL_DAMAGE.fullmatch(effect_type)
            if school_match and value and not periodic:
                kind='direct_damage';values.update(amount=float(value[1]),school=school_match[1].lower())
            elif effect_type in ('Apply Aura: Periodic Damage','Apply Aura: Periodic Heal') and periodic:
                kind=('periodic_damage' if effect_type.endswith('Damage') else 'periodic_heal')
                values.update(amount_per_tick=float(periodic[1]),tick_interval_s=float(periodic[2]))
            elif (absorb_match:=_ABSORB_DAMAGE.fullmatch(effect_type)) and value:
                schools=frozenset(x.strip().lower() for x in absorb_match[1].split(','))
                # Do not turn a restricted-school shield into a universal one.
                # Its amount/duration are typed even when its scope is blocked.
                values.update(amount=float(value[1]),absorbed_schools=sorted(schools))
                if schools==_ALL_SCHOOLS and float(value[1])>=0:
                    kind='absorb_all_schools'
                else:
                    kind='unsupported_absorb_school_scope'
            elif effect_type=='Apply Aura: Root' and value:
                # Only an actual timed root is a runnable ControlEffect.
                if float(value[1])==1:
                    kind='root_control'
                    values.update(control_id='root')
                else:
                    values['source_value']=float(value[1])
            elif effect_type == _MOVEMENT_SLOW and value:
                # Signed source percentage; target movement and pathing are
                # NOT source-attested L2 mechanics.  A synthetic movement
                # baseline is used only in the isolated L1 executor probe.
                delta=float(value[1])
                if -100 < delta < 0:
                    kind='movement_slow'
                    values['fractional_delta']=delta/100.0
                else:
                    values['source_value']=delta
            elif effect_type == 'Deal Weapon Damage' and value:
                # The source opcode's Value: 1 is a marker, not one damage.
                # Weapon choice/hit/normalization are L1 scenario proxies.
                if float(value[1]) == 1:
                    kind='weapon_base';values['opcode_marker']=1
            elif effect_type == 'Normalized Weapon Damage' and value:
                kind='normalized_weapon_bonus';values['flat_bonus']=float(value[1])
            elif effect_type == 'Weapon Damage - %' and value:
                kind='weapon_multiplier';values['percent']=float(value[1])
            elif effect_type == 'Weapon Damage - No School' and value:
                kind='weapon_bonus';values['flat_bonus']=float(value[1])
            elif (power_match:=_POWER_GAIN.fullmatch(effect_type)) and value:
                resource=re.sub(r'[^a-z0-9]+','_',power_match[1].strip().lower()).strip('_')
                if resource and float(value[1])>=0:
                    kind='resource_gain'
                    values.update(resource=resource,amount=float(value[1]))
                else:
                    values['source_value']=float(value[1])
            elif value:
                values['source_value']=float(value[1])
            if kind in ('weapon_multiplier','weapon_bonus','normalized_weapon_bonus') and (
                    not all(float(v) >= 0 for v in values.values())):
                kind='unsupported_invalid_weapon_value'
            if kind.startswith('periodic') and (values['tick_interval_s']<=0 or values['amount_per_tick']<0):
                raise ValueError('INVALID_SOURCE_PERIODIC_VALUE')
            effects.append({'slot':expected,'label':label,'effect_type':effect_type,
                            'effect_text':body,'kind':kind,'values':values})
        elif label in ('Cost','Range','Cast time','Cooldown','GCD','Forms','Aura proc chance'):
            if label in headers:raise ValueError('DUPLICATE_SPELL_DETAIL_FIELD')
            headers[label]=td.get_text(' ',strip=True)
    # The nested grid is source-structured but not a sibling of the main rows.
    for grid in tables[0].select('td.grid-nesting-wrapper > table.grid'):
        for tr in grid.select('tr'):
            th=tr.find('th',recursive=False);td=tr.find('td',recursive=False)
            if th and td:
                key=th.get_text(' ',strip=True)
                if key in headers:raise ValueError('DUPLICATE_SPELL_DETAIL_FIELD')
                headers[key]=td.get_text(' ',strip=True)
    if not effects or 'Cost' not in headers or 'Cast time' not in headers:
        raise ValueError('INCOMPLETE_STRUCTURED_SPELL_DETAILS')
    duration=_time(headers.get('Duration',''))
    for effect in effects:
        if effect['kind'] in ('absorb_all_schools','root_control','movement_slow'):
            if duration is None:
                effect['kind']='unsupported_missing_control_or_absorb_duration'
            else:
                effect['values']['duration_s']=duration
        if effect['kind'].startswith('periodic'):
            tick=effect['values']['tick_interval_s']
            if duration is None or abs(duration/tick-round(duration/tick))>1e-8:
                # Exact tick value but unknown schedule is NOT executable.
                effect['kind']='unsupported_periodic_schedule'
            else:
                effect['values'].update(duration_s=duration,
                                        tick_count=int(round(duration/tick)),
                                        total_base=effect['values']['amount_per_tick']*round(duration/tick),
                                        school=headers.get('School','unknown').lower())
    return {'headers':headers,'flags':flags,'effects':effects,
            'source_complete_effect_count':len(effects),
            'typed_supported_slots':sum(not e['kind'].startswith('unsupported') for e in effects),
            'execution_status':_STATUS}


def ingest(db_path:Path|str, *, quarantine_structural_errors:bool=False)->dict:
    """Atomic nine-class batch, only SHA-verified source HTML can enter ledger."""
    db=sqlite3.connect(str(db_path));db.row_factory=sqlite3.Row
    try:
        rows=db.execute('''SELECT i.class_key,i.spell_id,i.batch_id,i.source_url,i.raw_listview_json
            FROM spell_index i JOIN capture_lists l ON l.batch_id=i.batch_id
            AND l.class_key=i.class_key AND l.kind=i.kind
            JOIN capture_batches b ON b.batch_id=i.batch_id
            WHERE i.kind='abilities' AND l.complete=1 AND b.status='complete'
            ORDER BY i.class_key,i.spell_id''').fetchall()
        if len({r['class_key'] for r in rows})!=9:raise ValueError('INCOMPLETE_NINE_CLASS_SOURCE_INDEX')
        snapshot_keys={(str(r[0]),int(r[1])) for r in db.execute(
            'SELECT batch_id,spell_id FROM spell_detail_snapshots').fetchall()}
        prepared=[];meta=[];counts=Counter();classes=Counter();blocked=[]
        for row in rows:
            if (row['batch_id'],row['spell_id']) not in snapshot_keys:continue
            evidence=None
            try:
                evidence=read_verified_spell_detail_snapshot(db,batch_id=row['batch_id'],spell_id=row['spell_id'])
                parsed=parse_detail_effects(evidence['html'])
            except (ValueError,KeyError,TypeError) as exc:
                if not quarantine_structural_errors:raise
                blocked.append((row['class_key'],row['spell_id'],'effects',row['batch_id'],
                    sha256(row['raw_listview_json'].encode()).hexdigest(),
                    evidence['html_sha256'] if evidence is not None else None,blocker_reason(exc)))
                continue
            common=(row['class_key'],row['spell_id'],row['batch_id'],
                    sha256(row['raw_listview_json'].encode()).hexdigest(),
                    evidence['html_sha256'],row['source_url'])
            meta.append((*common,json.dumps(parsed['headers'],sort_keys=True),
                         json.dumps(parsed['flags']),len(parsed['effects']),
                         parsed['typed_supported_slots'],_STATUS))
            classes[row['class_key']]+=1
            for effect in parsed['effects']:
                counts[effect['kind']]+=1
                prepared.append((row['class_key'],row['spell_id'],effect['slot'],*common[2:],
                    effect['label'],effect['effect_type']+' | '+effect['effect_text'],
                    effect['kind'],json.dumps(effect['values'],sort_keys=True),_STATUS))
        db.execute('BEGIN IMMEDIATE')
        db.execute(SCHEMA);db.execute(META);db.execute(BLOCKER_SCHEMA)
        db.execute("DELETE FROM verified_source_ingest_blockers WHERE stage='effects'")
        db.executemany('INSERT INTO verified_source_ingest_blockers VALUES (?,?,?,?,?,?,?)',blocked)
        db.execute('DELETE FROM verified_spell_detail_effect_slots')
        db.execute('DELETE FROM verified_spell_detail_effect_headers')
        db.executemany('INSERT INTO verified_spell_detail_effect_slots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',prepared)
        db.executemany('INSERT INTO verified_spell_detail_effect_headers VALUES (?,?,?,?,?,?,?,?,?,?,?)',meta)
        db.commit()
        return {'verified_pages':len(meta),'source_classes':len(classes),'effect_slots':len(prepared),
                'by_kind':dict(counts),'by_class':dict(classes),
                'quarantined_source_pages':len(blocked),'quarantine_reasons':dict(Counter(x[-1] for x in blocked)),
                'executable_promotions':0,
                'accepted_checkpoints':0,'status':_STATUS}
    except Exception:
        db.rollback();raise
    finally:db.close()


def read_current_effects(conn:sqlite3.Connection,*,class_key:str,spell_id:int)->dict|None:
    """Reverify source SHA, index SHA, parsed slots, and status on every use."""
    old_factory=conn.row_factory
    try:
        conn.row_factory=sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='verified_spell_detail_effect_headers'").fetchone():
            return None
        h=conn.execute('''SELECT h.*,i.batch_id AS live_batch,i.source_url AS live_url,
            i.raw_listview_json FROM verified_spell_detail_effect_headers h JOIN spell_index i
            ON i.class_key=h.class_key AND i.spell_id=h.spell_id AND i.kind='abilities'
            WHERE h.class_key=? AND h.spell_id=?''',(class_key,spell_id)).fetchone()
        if h is None:
            blocker=read_blocker(conn,class_key=class_key,spell_id=spell_id,stage='effects')
            if blocker:raise ValueError('SOURCE_VERIFIED_EFFECTS_QUARANTINED:'+blocker['reason_code'])
            return None
        if h['index_batch_id']!=h['live_batch'] or h['source_url']!=h['live_url'] or h['index_payload_sha256']!=sha256(h['raw_listview_json'].encode()).hexdigest():
            raise ValueError('STALE_VERIFIED_EFFECT_INDEX_REINGEST_REQUIRED')
        evidence=read_verified_spell_detail_snapshot(conn,batch_id=h['index_batch_id'],spell_id=spell_id)
        if evidence['html_sha256']!=h['detail_html_sha256']:
            raise ValueError('STALE_VERIFIED_EFFECT_HTML_REINGEST_REQUIRED')
        parsed=parse_detail_effects(evidence['html'])
        if (h['headers_json']!=json.dumps(parsed['headers'],sort_keys=True) or
            h['flags_json']!=json.dumps(parsed['flags']) or
            h['effect_slots']!=len(parsed['effects']) or
            h['supported_slots']!=parsed['typed_supported_slots'] or h['execution_status']!=_STATUS):
            raise ValueError('TAMPERED_VERIFIED_EFFECT_HEADER_REINGEST_REQUIRED')
        slots=conn.execute('''SELECT * FROM verified_spell_detail_effect_slots
            WHERE class_key=? AND spell_id=? ORDER BY slot''',(class_key,spell_id)).fetchall()
        if len(slots)!=len(parsed['effects']):raise ValueError('TAMPERED_VERIFIED_EFFECT_SLOTS_REINGEST_REQUIRED')
        for stored,source in zip(slots,parsed['effects']):
            expected=(source['slot'],h['index_batch_id'],h['index_payload_sha256'],
                h['detail_html_sha256'],h['source_url'],source['label'],
                source['effect_type']+' | '+source['effect_text'],source['kind'],
                json.dumps(source['values'],sort_keys=True),_STATUS)
            actual=tuple(stored[k] for k in ('slot','index_batch_id','index_payload_sha256',
                'detail_html_sha256','source_url','effect_label','effect_text',
                'typed_kind','values_json','execution_status'))
            if expected!=actual:raise ValueError('TAMPERED_VERIFIED_EFFECT_SLOTS_REINGEST_REQUIRED')
        return {**parsed,'source_url':h['source_url'],'detail_html_sha256':h['detail_html_sha256']}
    finally:
        conn.row_factory=old_factory
