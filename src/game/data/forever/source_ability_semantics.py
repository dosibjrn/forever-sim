"""Generic source-indexed ability grammar -> executable Game IR actions.

Only fully parsed source shapes with independently sourced execution metadata
are included. Every other indexed action remains an explicit coverage gap;
no ability or class is selected by name/ID in production logic.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import sqlite3
from src.game.model.ir import (ActionDefinition, DamageEffect, PeriodicEffect,
    ResourceChangeEffect, ResourceCost, WeaponDamageEffect, ControlEffect, HealEffect,
    PeriodicHealEffect, ResourceScaledPeriodicEffect)
from src.game.data.forever.sqlite_talents import DEFAULT_DB, _slug
from .source_db_scope import active_ability_db

_RESOURCE_SCALED_PERIODIC_HEADER = re.compile(
    r'Finishing move that causes damage over time\. Damage increases per combo point and by your Attack Power:',re.I)
_RESOURCE_SCALED_PERIODIC_LINE = re.compile(
    r'([1-5]) points?: (\d+) damage over (\d+) sec\.',re.I)


def parse_resource_scaled_periodic_ladder(text: str) -> tuple[dict[int,float],float]:
    """Fail closed on every unparsed character; never infer missing CP totals."""
    lines = [x.strip() for x in text.strip().splitlines() if x.strip()]
    if len(lines)!=6 or not _RESOURCE_SCALED_PERIODIC_HEADER.fullmatch(lines[0]):
        raise ValueError('unparsed resource-scaled periodic tooltip')
    ladder={};duration=None
    for line in lines[1:]:
        match=_RESOURCE_SCALED_PERIODIC_LINE.fullmatch(line)
        if match is None:raise ValueError('unparsed resource-scaled periodic rank ladder')
        cp,damage,seconds=map(int,match.groups())
        if cp in ladder or damage<0 or seconds<=0 or (duration is not None and duration!=seconds):
            raise ValueError('invalid resource-scaled periodic rank ladder')
        ladder[cp]=float(damage);duration=seconds
    if set(ladder)!=set(range(1,6)):
        raise ValueError('incomplete resource-scaled periodic rank ladder')
    return ladder,float(duration)

_DIRECT = re.compile(r'Causes (\d+) to (\d+) (\w+) damage to the target\.',re.I)
_PERIODIC_COMBO = re.compile(
    r'.+? the target for (\d+) damage and an additional (\d+) damage over (\d+) sec\. Awards (\d+) combo point\.',re.I)
_WEAPON_COMBO = re.compile(r'.+? the enemy for (\d+(?:\.\d+)?)% normal damage plus (\d+)\. Awards (\d+) combo point\.', re.I)
_WEAPON_COMBO_POSITION = re.compile(r'Shred the target, causing (\d+(?:\.\d+)?)% damage plus (\d+) to the target\. Must be behind the target\. Awards (\d+) combo point\.', re.I)
_ROOT = re.compile(r'Roots the target in place and causes (\d+) (\w+) damage over (\d+) sec\. Damage caused may interrupt the effect\. .+',re.I)
_DIRECT_HOT = re.compile(r'Heals a friendly target for (\d+) to (\d+) and another (\d+) over (\d+) sec\.',re.I)
_DIRECT_HEAL = re.compile(r'Heals a friendly target for (\d+) to (\d+)\.',re.I)
_DIRECT_STUN = re.compile(r'Stuns the target for (\d+(?:\.\d+)?) sec\.',re.I)
# Strict, source-indexed grammar: channelled area heal is executed as the
# player's own heal until party actor targeting has been independently proven.
_CHANNELLED_GROUP_HEAL = re.compile(
    r'Regenerates all nearby (?:party|group) members (?:within (\d+) yards )?'
    r'for (\d+) every (\d+) sec(?:onds)? for (\d+) sec(?:onds)?\. '
    r'[^.]+ must channel to maintain the spell\.',re.I)
_COOLDOWN_MINS = re.compile(r'(\d+) min cooldown',re.I)

_COST = re.compile(r'(\d+(?:\.\d+)?)\s+(Mana|Energy|Rage|Focus)',re.I)
_CAST = re.compile(r'(\d+(?:\.\d+)?)\s+sec cast',re.I)
_RANGE = re.compile(r'(\d+(?:\.\d+)?)\s+yd range',re.I)



def _source_cost_match(cost_text:str, *,db_path:Path,class_key:str,spell_id:int):
    """Prefer canonical listview cost; recover only ABSENT costs from verified HTML.

    Never silently override a malformed or conflicting index field. The header
    accessor rechecks the original HTML and every derived typed field against
    its source on a content-addressed cache. Not proof of acquisition.
    """
    if cost_text:
        return _COST.fullmatch(cost_text),None
    from .source_verified_detail_headers import verified_headers_for_class
    header=verified_headers_for_class(db_path,class_key).get(int(spell_id))
    if not header or header['cost_resource'] is None:
        return None,None
    cost=_COST.fullmatch(f"{header['cost_amount']} {header['cost_resource']}")
    return cost,header['detail_html_sha256'] if cost else None


def _action_id(family: str, spell_id: int, level: int, semantic_type: str) -> str:
    # Stable legacy references are a property of the semantic shape, not a
    # class/spell-specific optimizer switch.
    if semantic_type == 'melee_direct_periodic_combo':
        return f'{family}:{spell_id}'
    if semantic_type in ('weapon_combo','resource_scaled_periodic'):
        return f'{family}:{level}'
    return f'source_spell:{spell_id}'


@dataclass(frozen=True)
class SourceActionRef:
    id: str
    spell_id: int
    level: int
    source_url: str
    cost_resource: str
    cost_amount: float

    @property
    def costs(self):
        return (ResourceCost(resource_id=self.cost_resource, amount=self.cost_amount),)


def latest_source_action_ref(class_key: str, family: str, level: int, *, db_path: Path | None = None):
    '''Small policy-seed reference from canonical SQL, never a second executor.'''
    db=Path(db_path or active_ability_db(DEFAULT_DB))
    with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        row=conn.execute('''SELECT i.spell_id,i.name,i.level_hint,i.source_url,
            i.raw_listview_json,s.semantic_type
            FROM spell_index i LEFT JOIN ability_semantic_source_facts s
              ON s.class_key=i.class_key AND s.spell_id=i.spell_id
            WHERE lower(i.class_key)=? AND lower(i.name)=? AND i.kind='abilities'
              AND i.level_hint<=? ORDER BY i.level_hint DESC,i.spell_id DESC LIMIT 1''',
              (class_key.lower(),family.lower(),int(level))).fetchone()
    if row is None:
        return None
    if not row['semantic_type']:
        raise ValueError(f'source action lacks typed semantics: {class_key}/{family}/{row["spell_id"]}')
    raw=json.loads(row['raw_listview_json'])
    cost,_cost_detail_sha=_source_cost_match(
        str(((raw.get('envChange') or {}).get('after') or {}).get('cost') or '').strip(),
        db_path=db,class_key=class_key.lower(),spell_id=int(row['spell_id']))
    if cost is None:
        raise ValueError(f'source action cost unparsed: {row["spell_id"]}')
    return SourceActionRef(id=_action_id(_slug(str(row['name'])),int(row['spell_id']),
            int(row['level_hint']),str(row['semantic_type'])),spell_id=int(row['spell_id']),
            level=int(row['level_hint']),source_url=str(row['source_url']),
            cost_resource=cost.group(2).lower(),cost_amount=float(cost.group(1)))

def _source_periodic_spell_flags(conn):
    """Load optional sourced flags; unknown mechanics remain explicit blockers."""
    flag_table=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='sourced_periodic_spell_flags'").fetchone()
    sourced_periodic_flags={}
    if flag_table:
        for flag in conn.execute("""SELECT spell_id,source_patch,build_attested,periodic_can_crit,
                heartbeat_resist,damage_break_probability,source_url,source_scope
                FROM sourced_periodic_spell_flags"""):
            fact=dict(flag)
            if (not isinstance(fact['source_patch'],str)
                    or not fact['source_patch'].startswith('1.')
                    or fact['build_attested'] not in (0,1)
                    or fact['periodic_can_crit'] not in (0,1)
                    or fact['heartbeat_resist'] not in (0,1)
                    or fact['damage_break_probability'] is not None
                    or not str(fact['source_url']).startswith('https://')
                    or not isinstance(fact['source_scope'],str)
                    or not fact['source_scope']):
                raise ValueError('INVALID_SOURCED_PERIODIC_SPELL_FLAG')
            sourced_periodic_flags[int(fact['spell_id'])]=fact
    return sourced_periodic_flags


def source_ability_actions(ir, *,class_key:str,level:int,db_path:Path|None=None):
    """Return IR with new source actions/mode permissions and coverage ledger."""
    db=Path(db_path or active_ability_db(DEFAULT_DB))
    conn=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    try:
        try:
            rows=conn.execute('''SELECT i.spell_id,i.name,i.level_hint,i.rank_hint,
               i.raw_listview_json,i.source_url,s.*,
               m.tick_interval_s AS melee_tick_interval_s,
               m.direct_can_crit AS melee_direct_can_crit,
               m.periodic_can_crit AS melee_periodic_can_crit,
               m.attack_resource_id AS melee_attack_resource_id,
               m.target_resource_id AS melee_target_resource_id,
               m.source_url AS melee_semantics_url,
               m.source_build AS melee_source_build,
               m.captured_at AS melee_captured_at,
               m.evidence AS melee_evidence,
               m.crit_multiplier AS melee_crit_multiplier,
               m.crit_chance_stat_id AS melee_crit_chance_stat_id
               FROM spell_index i JOIN ability_semantic_source_facts s
               ON s.class_key=i.class_key AND s.spell_id=i.spell_id
               LEFT JOIN sourced_direct_periodic_melee_semantics m ON m.spell_id=i.spell_id
               WHERE i.class_key=? AND i.kind='abilities' AND i.level_hint<=?
               ORDER BY i.name,i.level_hint DESC''',(class_key.lower(),int(level))).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError('canonical SQLite source ability semantics schema unavailable') from exc
        sourced_periodic_flags=_source_periodic_spell_flags(conn)
    finally:conn.close()
    # Every independently verified rank is a distinct legal action candidate.
    # The bounded controller (not the IR compiler) decides how much compute
    # each family/rank receives. In particular, lower ranks of damage,
    # control, and combo generators must not disappear at higher levels.
    # This is source-driven and independent of class, spell or effect names.
    selected = {f'{_slug(str(row["name"]))}#{int(row["spell_id"])}': row
                for row in rows}
    from .source_indexed_action_coverage import _source_spell_ids
    existing_source_ids={sid for action in ir.actions for sid in _source_spell_ids(action)}
    existing_action_ids={action.id for action in ir.actions}
    modes={m.id:m for m in ir.modes}
    resources={r.id for r in ir.resources}
    added=[]; source_facts=[]; skipped=[]
    # Stable newest-first order within a family preserves default highest-rank
    # behavior for existing consumers, while retaining all legal downranks.
    for selection_key,row in sorted(selected.items(), key=lambda kv: (
            _slug(str(kv[1]['name'])), -int(kv[1]['level_hint']), int(kv[1]['spell_id']))):
        family=_slug(str(row["name"]))
        sid=int(row['spell_id'])
        if sid in existing_source_ids:
            skipped.append({'spell_id':sid,'reason':'exact_source_spell_already_compiled'})
            continue
        proposed_id=_action_id(family,sid,int(row['level_hint']),str(row['semantic_type']))
        if proposed_id in existing_action_ids:
            skipped.append({'spell_id':sid,'reason':'action_id_collision_with_different_source_rank'})
            continue
        raw=json.loads(row['raw_listview_json'])
        tooltip=(raw.get('envChange') or {}).get('after') or {}
        # An index without tooltip body may have a separately pinned, typed
        # source observation. Recheck that its origin still matches the raw
        # index and preserve the unverified newer-build boundary.
        control_fact=None
        if row['semantic_type']=='direct_control':
            from hashlib import sha256
            clauses=json.loads(row['caveats_json'])
            matching=[c.get('observation') for c in clauses if isinstance(c,dict)
                      and c.get('semantic')=='direct_control_source_observation']
            if len(matching)!=1 or not isinstance(matching[0],dict):
                raise ValueError('DIRECT_CONTROL_SOURCE_FACT_MISSING')
            control_fact=matching[0]
            if (control_fact.get('indexed_payload_sha256')!=sha256(row['raw_listview_json'].encode()).hexdigest()
                    or control_fact.get('source_url')!=row['source_url']
                    or control_fact.get('spell_id')!=sid or
                    control_fact.get('build_bridge_verified') is not False):
                raise ValueError('DIRECT_CONTROL_INDEX_MISMATCH')
            tooltip={'cost':control_fact['cost'],'cast':control_fact['cast'],
                     'range':control_fact['range'],'text':control_fact['tooltip_text']}
        external_fact=None
        if row['semantic_type']=='direct_damage':
            # A generic direct-damage source rank can have a newer client
            # observation in an explicitly selected stage. Do not rewrite the
            # canonical index or quietly keep its older damage numbers.
            from .source_index_rank_parity import indexed_rank_fact
            external_fact=indexed_rank_fact(class_key=class_key,name=str(row['name']),
                required_level=int(row['level_hint']),effect_kind='direct_damage',db_path=db)
            if external_fact is not None and external_fact['source_authority']=='external_beta_client_web_text_observation':
                tooltip=external_fact['raw_observed_after']
        source={'authority':row['source_authority'],'url':row['source_url'],
                'mechanics_url':row['mechanics_source_url'],'capture_id':row['capture_id'],
                'source_spell_id':sid,'source_rank':row['rank_hint']}
        if external_fact is not None and external_fact['source_authority']=='external_beta_client_web_text_observation':
            source={**source,'numeric_authority':external_fact['source_authority'],
                    'external_source_urls':external_fact['external_source_urls'],
                    'observation_sha256':external_fact['observation_sha256'],
                    'source_build':external_fact['source_build'],
                    'checkpoint_eligibility':external_fact['checkpoint_eligibility']}
        cost,cost_detail_sha=_source_cost_match(
            str(tooltip.get('cost') or '').strip(),db_path=db,
            class_key=class_key.lower(),spell_id=sid)
        cast=str(tooltip.get('cast') or '').strip()
        cast_s=0.0 if cast.lower()=='instant' else (float(_CAST.fullmatch(cast).group(1)) if _CAST.fullmatch(cast) else None)
        source_range=str(tooltip.get('range') or '').strip()
        range_match=_RANGE.fullmatch(source_range)
        range_yards=(float(range_match.group(1)) if range_match else None)
        # Only independently sourced distance enters 2D reach calculations.
        # An unknown range remains missing rather than guessing a spell range.
        mode=str(row['required_mode_id'])
        if cost_detail_sha:
            source['cost_verified_detail_html_sha256']=cost_detail_sha
        if cost is None or cast_s is None or mode not in modes or cost.group(2).lower() not in resources:
            skipped.append({'spell_id':sid,'reason':'cost_cast_mode_or_resource_not_executable'});continue
        text=str(tooltip.get('text') or '').strip()
        effects=[]; extra_requirements=[]
        if row['semantic_type']=='direct_control':
            match=_DIRECT_STUN.fullmatch(text)
            if (match and control_fact and
                    float(match.group(1))==float(control_fact['duration_s']) and
                    control_fact['control_id']=='stun' and
                    control_fact['prevents_enemy_actions'] is True and
                    control_fact['breaks_on_damage'] is False):
                effects.append(ControlEffect(effect_type='control',
                    control_id=str(control_fact['control_id']),target='enemy',
                    duration_s=float(control_fact['duration_s']),
                    prevents_enemy_actions=True,breaks_on_damage=False,
                    proc_chance=1.0))
        elif row['semantic_type']=='direct_damage':
            match=_DIRECT.fullmatch(text)
            if match:
                low,high,school=match.groups()
                effects.append(DamageEffect(effect_type='damage',school=school.lower(),target='enemy',
                    base_min=float(low),base_max=float(high),spell_power_coefficient=float(row['spell_power_coefficient']),
                    field_provenance={'source':(source,)}))
        elif row['semantic_type']=='direct_periodic_combo':
            match=_PERIODIC_COMBO.fullmatch(text)
            if match:
                immediate,total,duration,combo=map(int,match.groups())
                tick=float(row['tick_interval_s'])
                if duration%tick==0 and 'combo_points' in resources:
                    effects.extend((
                        DamageEffect(effect_type='damage',school='physical',target='enemy',
                            base_min=float(immediate),base_max=float(immediate),
                            spell_power_coefficient=float(row['spell_power_coefficient']),
                            field_provenance={'source':(source,)}),
                        PeriodicEffect(effect_type='periodic_damage',school='physical',target='enemy',
                            aura_id=f'source_periodic:{sid}',total_base_damage=float(total),
                            duration_s=float(duration),tick_interval_s=tick,
                            field_provenance={'source':(source,)}),
                        ResourceChangeEffect(effect_type='resource_change',resource_id='combo_points',
                            target='enemy',operation='add',amount=float(combo))))
        elif row['semantic_type']=='melee_direct_periodic_combo':
            # Same typed grammar for any sourced melee direct+periodic builder;
            # neither class nor spell name is inspected by this executor adapter.
            match=_PERIODIC_COMBO.fullmatch(text)
            melee_fields=(row['melee_tick_interval_s'],row['melee_direct_can_crit'],
                row['melee_periodic_can_crit'],row['melee_attack_resource_id'],
                row['melee_target_resource_id'],row['melee_semantics_url'],
                row['melee_source_build'],row['melee_captured_at'],
                row['melee_evidence'],row['melee_crit_multiplier'],
                row['melee_crit_chance_stat_id'])
            if match and all(x is not None for x in melee_fields):
                immediate,total,duration,combo=map(int,match.groups())
                tick=float(row['melee_tick_interval_s'])
                crit_mult=float(row['melee_crit_multiplier'])
                stat=str(row['melee_crit_chance_stat_id'])
                attack_resource=str(row['melee_attack_resource_id'])
                target_resource=str(row['melee_target_resource_id'])
                if (row['melee_semantics_url'] != row['source_url'] or
                    attack_resource != cost.group(2).lower() or
                    attack_resource not in resources or target_resource not in resources or
                    int(row['melee_direct_can_crit']) not in (0,1) or
                    int(row['melee_periodic_can_crit']) not in (0,1) or
                    not (tick > 0 and duration > 0 and duration/tick == int(duration/tick)) or
                    not (crit_mult >= 1 and crit_mult < 10) or not stat or
                    not row['melee_source_build'] or not row['melee_evidence']):
                    raise ValueError(f'invalid sourced melee direct/periodic semantics for {sid}')
                # The crit stat and multiplier are sourced data, not a fixed
                # game-specific value in the optimizer or runtime.
                source={**source,'source_build':row['melee_source_build'],
                        'mechanics_capture':row['melee_captured_at'],
                        'mechanics_evidence':row['melee_evidence']}
                effects.extend((
                    DamageEffect(effect_type='damage',school='physical',target='enemy',
                        base_min=float(immediate),base_max=float(immediate),
                        crit_chance_stat_id=(stat if row['melee_direct_can_crit'] else None),
                        crit_multiplier=crit_mult,field_provenance={'source':(source,)}),
                    PeriodicEffect(effect_type='periodic_damage',school='physical',target='enemy',
                        aura_id=f'{family}:{sid}:bleed',total_base_damage=float(total),
                        duration_s=float(duration),tick_interval_s=tick,refresh_rule='replace',
                        crit_chance_stat_id=(stat if row['melee_periodic_can_crit'] else None),
                        crit_multiplier=crit_mult,field_provenance={'source':(source,)}),
                    ResourceChangeEffect(effect_type='resource_change',resource_id=target_resource,
                        target='enemy',operation='add',amount=float(combo)),
                ))
        elif row['semantic_type']=='weapon_combo':
            match=_WEAPON_COMBO.fullmatch(text)
            source_auto=next((a for a in ir.auto_attacks if a.required_mode_id==mode
                              and a.owner_actor_id==ir.actor.id),None)
            if match and source_auto and 'combo_points' in resources:
                mult,flat,combo=match.groups()
                effects.extend((WeaponDamageEffect(effect_type='weapon_damage',
                    school='physical',target='enemy',damage_source=source_auto.damage_source,
                    weapon_damage_time_s=source_auto.swing_time_s,
                    weapon_damage_multiplier=float(mult)*0.01,flat_damage=float(flat),
                    hit_chance=source_auto.hit_chance,
                    crit_chance_on_landed_hit=source_auto.crit_chance_on_landed_hit,
                    crit_multiplier=source_auto.crit_multiplier,provenance=(source,),
                    metadata={'source_weapon_basis':source_auto.id,
                              'combo_point_award':int(combo),
                              'combo_point_award_semantics':'generic_target_bound_resource_change'}),
                    ResourceChangeEffect(effect_type='resource_change',resource_id='combo_points',
                        target='enemy',operation='add',amount=float(combo))))
        elif row['semantic_type']=='weapon_combo_position':
            match=_WEAPON_COMBO_POSITION.fullmatch(text)
            source_auto=next((a for a in ir.auto_attacks if a.required_mode_id==mode
                              and a.owner_actor_id==ir.actor.id),None)
            if match and source_auto and row['positional_requirement']=='behind' and 'combo_points' in resources:
                mult,flat,combo=match.groups()
                effects.extend((WeaponDamageEffect(effect_type='weapon_damage',school='physical',target='enemy',
                    damage_source=source_auto.damage_source,weapon_damage_time_s=source_auto.swing_time_s,
                    weapon_damage_multiplier=float(mult)*0.01,flat_damage=float(flat),
                    hit_chance=source_auto.hit_chance,crit_chance_on_landed_hit=source_auto.crit_chance_on_landed_hit,
                    crit_multiplier=source_auto.crit_multiplier,provenance=(source,),
                    metadata={'source_weapon_basis':source_auto.id}),
                    ResourceChangeEffect(effect_type='resource_change',resource_id='combo_points',
                        target='enemy',operation='add',amount=float(combo))))
                extra_requirements.append({'kind':'relative_position_is','value':row['positional_requirement']})
        elif row['semantic_type']=='periodic_control':
            match=_ROOT.fullmatch(text)
            tick=row['tick_interval_s']
            if match and tick and row['periodic_power_coefficient_per_tick'] is not None:
                total,school,duration=match.groups()
                if int(duration)%float(tick)==0:
                    crit_fact=sourced_periodic_flags.get(sid)
                    crit_flag=bool(crit_fact and crit_fact['periodic_can_crit'])
                    crit_source=({'authority':'forever_wowhead_periodic_flag',
                        'source_url':crit_fact['source_url'],
                        'source_patch':crit_fact['source_patch'],
                        'build_attested':bool(crit_fact['build_attested']),
                        'source_scope':crit_fact['source_scope']},) if crit_flag else ()
                    effects.extend((ControlEffect(effect_type='control',control_id='root',target='enemy',
                        duration_s=float(duration)),
                        PeriodicEffect(effect_type='periodic_damage',school=school.lower(),target='enemy',
                            aura_id=f'source_periodic:{sid}',total_base_damage=float(total),
                            duration_s=float(duration),tick_interval_s=float(tick),
                            spell_power_coefficient_per_tick=float(row['periodic_power_coefficient_per_tick']),
                            crit_chance_stat_id=('spell_crit_chance' if crit_flag else None),
                            field_provenance={'source':(source,),
                                **({'periodic_can_crit':crit_source} if crit_flag else {})},
                            unsupported_semantics=(
                                {'semantic':'root_break_on_damage_or_heartbeat','status':'not_yet_modeled'},
                                *(({'semantic':'periodic_can_crit','status':'not_yet_modeled'},)
                                  if not crit_flag else ())))))
        elif row['semantic_type']=='resource_scaled_periodic':
            # The full CP ladder is parsed from the canonical rank's own
            # tooltip, not from a class-specific constant or previous rank.
            # AP and crit remain explicitly unsupported, not assumed zero.
            try:
                ladder,duration=parse_resource_scaled_periodic_ladder(text)
            except ValueError as exc:
                raise ValueError(f'invalid sourced resource-scaled periodic rank {sid}: {exc}') from exc
            tick=row['tick_interval_s']
            if tick is None or tick<=0 or duration/float(tick)!=int(duration/float(tick)):
                raise ValueError(f'invalid sourced resource-scaled periodic timing {sid}')
            caveats=json.loads(row['caveats_json'])
            binding=next((c for c in caveats if isinstance(c,dict)
                          and c.get('semantic')=='resource_binding'),None)
            if not binding or binding.get('resource_id') not in resources or binding.get('scope')!='target':
                raise ValueError(f'missing sourced resource binding {sid}')
            if not any(c.get('semantic')=='attack_power_scaling' and c.get('status')=='explicit_gap'
                       for c in caveats if isinstance(c,dict)):
                raise ValueError(f'unknown attack power scaling semantics {sid}')
            resource_id=str(binding['resource_id'])
            effects.extend((ResourceScaledPeriodicEffect(
                effect_type='resource_scaled_periodic_damage',school='physical',target='enemy',
                aura_id=f'{family}:{int(row["level_hint"])}:bleed',resource_id=resource_id,
                resource_scope='target',total_base_damage_by_resource_amount=ladder,
                duration_s=duration,tick_interval_s=float(tick),refresh_rule='replace',
                field_provenance={'damage_by_combo_points':(source,),
                                  'tick_interval_s':(source,)},
                unsupported_semantics=tuple(c for c in caveats if isinstance(c,dict)
                                            and c.get('status') in ('explicit_gap','legacy_transcription_pending_independent_verification'))),
                ResourceChangeEffect(effect_type='resource_change',resource_id=resource_id,
                    target='enemy',operation='set',amount=0.0)))
            extra_requirements.append({'kind':'resource_min','resource_id':resource_id,'value':1.0})
        elif row['semantic_type']=='channeled_group_heal':
            match=_CHANNELLED_GROUP_HEAL.fullmatch(text)
            cd=_COOLDOWN_MINS.fullmatch(str(tooltip.get('cooldown') or '').strip())
            if (match and cd and 'health' in resources and
                    row['periodic_power_coefficient_per_tick'] is not None and
                    row['gcd_s'] is not None):
                radius,per_tick,tick_sec,duration=match.groups()
                per_tick,tick_sec,duration=map(int,(per_tick,tick_sec,duration))
                if (tick_sec>0 and 0<duration<=120 and duration%tick_sec==0 and
                        float(row['tick_interval_s'])==tick_sec and
                        float(row['gcd_s'])>0 and int(cd.group(1))>0 and
                        str(row['source_authority'])=='forever_wowhead_source_index_build_unverified'):
                    source={**source,'source_build_verified':False,
                        'unsupported_party_healing':True}
                    effects.append(PeriodicHealEffect(effect_type='periodic_heal',
                        target='self',resource_id='health',aura_id=f'source_channel_heal:{sid}',
                        total_base_heal=float(per_tick)*(duration/tick_sec),
                        duration_s=float(duration),tick_interval_s=float(tick_sec),
                        spell_power_coefficient_per_tick=float(row['periodic_power_coefficient_per_tick']),
                        field_provenance={'source':(source,)},unsupported_semantics=(
                            {'code':'PARTY_HEALING_NOT_SUPPORTED_PLAYER_ONLY','source':source},
                            {'code':'SOURCE_BUILD_BRIDGE_UNVERIFIED','source':source})))
                    channel_duration_s=float(duration)
                    channel_cd_s=float(cd.group(1))*60.
        elif row['semantic_type']=='direct_heal':
            match=_DIRECT_HEAL.fullmatch(text)
            if match and 'health' in resources:
                low,high=map(int,match.groups())
                if 0 <= low <= high:
                    effects.append(HealEffect(effect_type='heal',target='self',resource_id='health',
                        base_min=float(low),base_max=float(high),
                        spell_power_coefficient=float(row['spell_power_coefficient']),
                        field_provenance={'source':(source,)}))
        elif row['semantic_type']=='direct_periodic_heal':
            match=_DIRECT_HOT.fullmatch(text)
            tick=row['tick_interval_s']
            if match and tick and row['periodic_power_coefficient_per_tick'] is not None and 'health' in resources:
                low,high,total,duration=map(int,match.groups())
                if duration%float(tick)==0:
                    effects.extend((HealEffect(effect_type='heal',target='self',resource_id='health',
                        base_min=float(low),base_max=float(high),spell_power_coefficient=float(row['spell_power_coefficient']),
                        field_provenance={'source':(source,)}),
                        PeriodicHealEffect(effect_type='periodic_heal',target='self',resource_id='health',
                            aura_id=f'source_periodic_heal:{family}',total_base_heal=float(total),
                            duration_s=float(duration),tick_interval_s=float(tick),
                            spell_power_coefficient_per_tick=float(row['periodic_power_coefficient_per_tick']),
                            field_provenance={'source':(source,)},unsupported_semantics=(
                                {'semantic':'periodic_can_crit','status':'not_yet_modeled'},
                                {'semantic':'cross_rank_aura_replacement',
                                 'status':'conservative_same_index_family_not_server_verified'}))))
        if not effects:
            skipped.append({'spell_id':sid,'reason':'source_tooltip_grammar_not_fully_executable'});continue
        channelled=(row['semantic_type']=='channeled_group_heal')
        action=ActionDefinition(id=_action_id(family,sid,int(row['level_hint']),str(row['semantic_type'])),family_key=family,name=str(row['name']),
            owner_actor_id=ir.actor.id,requirements=(
                {'kind':'minimum_level','value':int(row['level_hint'])},
                {'kind':'mode_is','value':mode},*extra_requirements),
            costs=(ResourceCost(resource_id=cost.group(2).lower(),amount=float(cost.group(1))),),
            cast_time_s=(channel_duration_s if channelled else cast_s),
            gcd_s=float(row['gcd_s']),cooldown_s=(channel_cd_s if channelled else
                float(control_fact['cooldown_s']) if control_fact is not None else 0.0),
            effects=tuple(effects),provenance=(source,),
            metadata={'source_spell_rank':row['rank_hint'],'source_semantic_type':row['semantic_type'],
                      **({'source_build_bridge_verified':False,
                          'source_control_duration_observation':dict(control_fact)}
                         if control_fact is not None else {}),
                      **({'channel':True,'unsupported_party_scope':True,
                          'source_build_bridge_verified':False} if channelled else {}),
                      **({'range_yards':range_yards} if range_yards is not None else {}),
                      'source_caveats':json.loads(row['caveats_json']),
                      'ability_source_coverage':'partial_until_all_source_ability_effects_verified'})
        added.append(action)
        existing_source_ids.add(sid)
        existing_action_ids.add(action.id)
        source_facts.append({'fact_kind':'source_indexed_executable_ability',
            'family_key':family,'spell_id':sid,'level':int(row['level_hint']),
            'source':source,'caveats':json.loads(row['caveats_json'])})
    # A provider may declare a policy dependency before generic ingestion.
    # Never publish a policy pointing to a non-executable indexed action.
    compiled_ids={a.id for a in (*ir.actions,*added)}
    for fact in ir.source_facts:
        if isinstance(fact,dict) and fact.get('fact_kind')=='required_source_action':
            if fact.get('action_id') not in compiled_ids:
                raise ValueError(f"required source action not executable: {fact.get('action_id')}")
    permissions={}
    for action in added:
        mode=next(req['value'] for req in action.requirements if req['kind']=='mode_is')
        permissions.setdefault(mode,[]).append(action.id)
    new_modes=tuple(replace(m, enabled_action_ids=(None if m.enabled_action_ids is None
                      else m.enabled_action_ids + tuple(permissions.get(m.id,()))))
                    for m in ir.modes)
    return replace(ir,actions=ir.actions+tuple(added),modes=new_modes,
        source_facts=ir.source_facts+tuple(source_facts),
        provenance={**dict(ir.provenance),'source_ability_ingest':{
            'new_action_families':sorted(a.family_key for a in added),
            'unparsed_semantic_rows':skipped,'canonical_source':'ability_semantic_source_facts'}})
