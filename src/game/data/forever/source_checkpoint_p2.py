"""Generic checkpoint-scoped talent rank and allocation L0 acceptance audit.

Source GameIR supplies talent identities, ranks and provisional tree positions.
An exact-source supplemental capture can score missing executor modifiers WITHOUT
introducing a dummy TalentModifier, a free spell, or L2 execution permission.
All game-specific facts are data; unobserved tree positions fail closed.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import json
import re
from typing import Mapping

from src.game.talents import available_talent_points


@dataclass(frozen=True)
class P2Checkpoint:
    class_key: str
    level: int
    profile: str = 'unrestricted'
    use_runes: bool = False
    source_build: str = '1.60.1.70338'

    def __post_init__(self):
        if not self.class_key or not 1 <= self.level <= 60 or not self.profile:
            raise ValueError('INVALID_P2_CHECKPOINT')


def _captures(path: str | Path | None, checkpoint: P2Checkpoint):
    if path is None:
        return {}
    data=json.loads(Path(path).read_text())
    if (data.get('schema') not in ('forever_talent_l0_external_rank_observations_v1',
                                    'forever_checkpoint_talent_catalogue_source_v1')
            or data.get('class_key')!=checkpoint.class_key
            or data.get('source_build')!=checkpoint.source_build):
        raise ValueError('P2_SOURCE_BUILD_OR_CLASS_MISMATCH')
    observed={}
    for row in data['observations']:
        tid=row['talent_id']
        if tid in observed:
            raise ValueError('P2_DUPLICATE_SOURCE_TALENT')
        if not str(row.get('source_url','')).startswith('https://'):
            raise ValueError('P2_MISSING_SOURCE_URL')
        if not row.get('rank_values') or len(row['rank_values']) != int(row['max_rank']):
            raise ValueError('P2_INCOMPLETE_RANK_CURVE')
        prerequisite=row.get('prerequisite')
        if prerequisite is not None and (not isinstance(prerequisite,dict)
                or not str(prerequisite.get('talent_id') or '').strip()
                or not isinstance(prerequisite.get('required_rank'),int)
                or isinstance(prerequisite.get('required_rank'),bool)
                or prerequisite['required_rank']<1):
            raise ValueError('P2_INVALID_SOURCE_PREREQUISITE')
        if row.get('additional_effect_domain') and (not row.get('additional_target')
            or not row.get('additional_rank_values')
            or len(row['additional_rank_values']) != int(row['max_rank'])):
            raise ValueError('P2_INCOMPLETE_ADDITIONAL_EFFECT_CURVE')
        for values in [row['rank_values'],row.get('additional_rank_values',[])]:
            if any(not isinstance(v,(int,float)) or isinstance(v,bool) or v < 0 for v in values):
                raise ValueError('P2_INVALID_NUMERIC_SOURCE_VALUE')
        for extra in row.get('extra_effects',()):
            if (not extra.get('effect_domain') or not extra.get('target')
                    or len(extra.get('rank_values',()))!=int(row['max_rank'])
                    or any(not isinstance(v,(int,float)) or isinstance(v,bool) or v<0
                           for v in extra['rank_values'])):
                raise ValueError('P2_INVALID_SOURCE_EXTRA_EFFECT_CURVE')
        observed[tid]=row
    for pos in data.get('observed_unreachable_talent_positions',()):
        tid=pos['indexed_talent_id']
        if tid in observed:raise ValueError('P2_SOURCE_POSITION_DUPLICATES_RANK_EFFECT')
        if not str(pos.get('source_url','')).startswith('https://') or pos.get('client_build')!=checkpoint.source_build:
            raise ValueError('P2_STALE_OR_UNSOURCED_TALENT_POSITION')
        if int(pos.get('row',-1))<0:raise ValueError('P2_INVALID_SOURCE_TALENT_POSITION')
        observed[tid]={'talent_id':tid,'tree_key':pos['tree_key'],
            'row':int(pos['row']),'position_only':True,
            'source_url':pos['source_url'],'identity_status':pos['identity_status']}
    return observed


def _source_scope_completion(talent, rank: int, effect_rows: list[dict], learned: set[str]):
    """Preserve source tooltip's other L20-relevant targets and effect clauses.

    No class/talent switches: everything below is driven by source tooltip
    and canonical talent coverage metadata. An unavailable target is not
    automatically an illegal spell; the versioned spellbook decides.
    """
    source_rank=next((r for r in talent.ranks if int(r.rank)==rank),None)
    raw=str((source_rank.provenance if source_rank is not None else {}).get('raw_tooltip') or '')
    extra=[];excluded=[];unresolved=[]
    for target in talent.metadata.get('unavailable_action_targets') or ():
        key=str(target).lower()
        if key not in learned:
            excluded.append({'target':key,'reason':'NOT_LEARNED_BY_CHECKPOINT_FROM_PINNED_SPELLBOOK'})
            continue
        matches=[e for e in effect_rows if e['domain'] in ('resource_cost_flat','resource_cost_pct',
            'effect_damage_pct','effect_healing_pct','periodic_duration_delta_s','gcd_delta_s')]
        if matches and key.replace('_',' ') in raw.lower():
            # Rank tooltip explicitly names the unavailable ability and its
            # common magnitude; do not manufacture a new engine modifier.
            m=matches[0]
            extra.append({'domain':m['domain'],'target':key,'target_type':'action_family',
                'sourced_value':float(m['sourced_value']),
                'source':'canonical_talent_rank_tooltip_named_target_L0_only'})
        else:
            unresolved.append({'target':key,'reason':'CHECKPOINT_LEGAL_ACTION_MISSING_L0_MAGNITUDE'})
    for target in talent.metadata.get('unavailable_mode_targets') or ():
        key=str(target).lower()
        if key not in learned:
            excluded.append({'target':key,'reason':'FORM_UNLEARNED_AT_CHECKPOINT'})
        else:
            unresolved.append({'target':key,'reason':'LEARNED_FORM_MISSING_TALENT_MODIFIER'})
    # Reuse generic numeric-source phrase patterns, never spell/talent IDs.
    for pattern,domain,unit in [
        (r'as if you were (\d+) level higher', 'stealth_detection_effective_level_bonus', 1.0),
        (r'take up to (\d+(?:\.\d+)?)% more damage without interrupting',
             'control_break_damage_threshold_fraction',0.01),
        (r'range of your offensive .*? spells by (\d+(?:\.\d+)?)%',
             'offensive_spell_range_bonus_fraction',0.01),
    ]:
        m=re.search(pattern,raw,re.IGNORECASE)
        if m:
            extra.append({'domain':domain,'target':'source_tooltip_conditional',
                'sourced_value':float(m.group(1))*unit,
                'source':'canonical_talent_rank_tooltip_secondary_L0_only'})
    return extra,excluded,unresolved


def _effect_domains(talent, rank:int, captured:dict|None):
    found=next((r for r in talent.ranks if int(r.rank)==rank),None)
    staged_l0=(found.provenance.get('checkpoint_source_l0') if found is not None else None)
    if captured is None and staged_l0:
        return [dict(effect) for effect in staged_l0['effects']], 'SOURCE_POSITION_TOOLTIP_L0_ONLY'
    if captured is None and found is not None and found.modifiers:
        return ({'domain':str(m.kind),'target_type':str(m.target_type),
                 'target':str(m.target_id),'sourced_value':float(m.value),
                 'source':'canonical_game_ir'} for m in found.modifiers), 'GAME_IR_MODIFIERS'
    if captured is not None:
        v=[{'domain':captured['effect_domain'],'target':captured['target'],
            'sourced_value':float(captured['rank_values'][rank-1]),
            'condition':captured['condition'],'source':captured['source_url']}]
        if captured.get('additional_effect_domain'):
            v.append({'domain':captured['additional_effect_domain'],'target':captured['additional_target'],
                'sourced_value':float(captured['additional_rank_values'][rank-1]),
                'condition':captured['condition'],'source':captured['source_url']})
        for extra in captured.get('extra_effects',()):
            v.append({'domain':extra['effect_domain'],'target':extra['target'],
                'sourced_value':float(extra['rank_values'][rank-1]),
                'condition':extra.get('condition','source_context_conditional'),
                'source':captured['source_url'],
                'context_uncertainty':captured.get('context_uncertainty')})
        return v, 'SOURCE_OBSERVED_L0_ONLY'
    return [], 'UNKNOWN_UNSCORED'


def _witness(target,rank,defs,budget:int,points_per_row:int, *,override_rows=None):
    """Deterministically construct one structurally legal same-tree path.

    This is only a witness for source-learnable talent rank, NOT an L2 action
    or statement about executor support. At higher levels a richer search for
    prerequisites may be needed; failure returns unresolved, never illegal.
    """
    override_rows = override_rows or {}
    def row_of(t):
        value=t.metadata.get('row')
        if value is None:
            value=override_rows.get(t.id,{}).get('row')
        return None if value is None else int(value)
    row=row_of(target)
    if row is None:return None
    req=row*points_per_row
    if rank+req>budget:return None
    out={target.id:rank}
    lookup={t.id:t for t in defs}
    # Source-versioned prerequisites are mandatory even if stale GameIR
    # has no prerequisite field. Resolve them before choosing tier fillers.
    active=set()
    def require(t):
        if t.id in active:
            return False
        active.add(t.id)
        prerequisite=(override_rows.get(t.id,{}).get('prerequisite')
                      or t.prerequisite)
        if prerequisite:
            dep=lookup.get(prerequisite.get('talent_id'))
            required=prerequisite.get('required_rank')
            if dep is None or required is None or not 1<=int(required)<=int(dep.max_rank):
                return False
            if out.get(dep.id,0)<int(required):
                out[dep.id]=int(required)
                if not require(dep):return False
        active.remove(t.id)
        return True
    if not require(target):return None
    before=[t for t in defs if t.tree_key==target.tree_key and t.id!=target.id
            and row_of(t) is not None and row_of(t)<row]
    left=req - sum(v for tid,v in out.items() if tid!=target.id
                   and row_of(lookup[tid]) is not None and row_of(lookup[tid])<row)
    if left<0 or sum(out.values())+left>budget:return None
    # Fill tier 1 before tier 2. This satisfies a tier-2 filler gate.
    for t in sorted(before,key=lambda t:(row_of(t),t.id)):
        if left<=0:break
        tier=row_of(t)
        if tier and sum(v for tid,v in out.items() if tid!=target.id
            and any(x.id==tid and row_of(x) is not None
                    and row_of(x)<tier for x in before)) < tier*points_per_row:
            continue
        cap=min(int(t.max_rank),max((int(r.rank) for r in t.ranks),default=0))
        n=min(left,cap-out.get(t.id,0))
        if n>0:out[t.id]=out.get(t.id,0)+n;left-=n
    if left:return None
    return out


def check_structural_allocation(ir, selection:Mapping[str,int], checkpoint:P2Checkpoint,
                                *, override_rows:Mapping[str,dict]|None=None,
                                bonus_talent_points:int=0):
    if str(ir.actor.metadata.get('class_key','')).lower()!=checkpoint.class_key.lower() or int(ir.actor.metadata.get('level',-1))!=checkpoint.level:
        raise ValueError('P2_CHECKPOINT_IR_MISMATCH')
    definitions={t.id:t for t in ir.talents}
    if set(selection)-set(definitions): raise ValueError('P2_UNKNOWN_TALENT')
    if sum(selection.values())>available_talent_points(checkpoint.level,bonus_talent_points=bonus_talent_points):raise ValueError('P2_POINT_BUDGET')
    rules=ir.provenance.get('talent_tree_rules') or {}
    step=int(rules.get('points_per_row') or 0)
    if step<=0:raise ValueError('P2_UNVERIFIED_TIER_RULE')
    captures=override_rows or {}
    def row(t):
        v=t.metadata.get('row')
        return v if v is not None else captures.get(t.id,{}).get('row')
    for tid,rank in selection.items():
        t=definitions[tid]
        if not isinstance(rank,int) or not 1<=rank<=int(t.max_rank):raise ValueError('P2_TALENT_RANK_INVALID')
        if row(t) is None:raise ValueError('P2_TALENT_ROW_UNRESOLVED')
        cur_row=int(row(t))
        earlier=sum(n for other,n in selection.items()
          if definitions[other].tree_key==t.tree_key and row(definitions[other]) is not None
          and int(row(definitions[other]))<cur_row)
        if earlier<cur_row*step:raise ValueError('P2_TIER_GATE')
        prerequisite=captures.get(tid,{}).get('prerequisite') or t.prerequisite
        if prerequisite:
            pid=prerequisite.get('talent_id');required=prerequisite.get('required_rank')
            if required is None or selection.get(pid,0)<int(required):raise ValueError('P2_PREREQUISITE_GATE')
    return True


def evaluate_p2(ir,checkpoint:P2Checkpoint,*,source_observations_path:str|Path|None=None, spellbook_path:str|Path|None=None, source_delta_path:str|Path|None=None):
    if str(ir.actor.metadata.get('class_key','')).lower()!=checkpoint.class_key.lower() or int(ir.actor.metadata.get('level',-1))!=checkpoint.level:
        raise ValueError('P2_CHECKPOINT_IR_MISMATCH')
    captures=_captures(source_observations_path,checkpoint)
    definitions={t.id:t for t in ir.talents}
    if set(captures)-set(definitions):raise ValueError('P2_SOURCE_TALENT_NOT_IN_CANONICAL_IR')
    for tid,s in captures.items():
        t=definitions[tid]
        if (s['tree_key']!=t.tree_key
                or (t.metadata.get('row') is not None and int(s['row'])!=int(t.metadata['row']))):
            raise ValueError('P2_SOURCE_ID_TREE_RANK_ROW_MISMATCH')
    source_build_bridge=None
    if spellbook_path is not None:
        from src.game.data.forever.source_checkpoint_spellbook import SourceSpellbook
        spellbook=SourceSpellbook(spellbook_path,class_key=checkpoint.class_key,
                                  level=checkpoint.level,use_runes=checkpoint.use_runes)
        from src.game.data.forever.source_build_delta import resolve_spellbook_build
        source_build_bridge=resolve_spellbook_build(
            spellbook,class_key=checkpoint.class_key,target_build=checkpoint.source_build,
            delta_path=source_delta_path,missing_error='P2_SPELLBOOK_SOURCE_BUILD_MISMATCH')
        learned={re.sub(r'[^a-z0-9]+','_',name.lower()).strip('_')
                 for name,level in spellbook.learned}
    else:
        if source_delta_path is not None:
            raise ValueError('SOURCE_BUILD_BRIDGE_REQUIRES_SPELLBOOK')
        learned=None
    budget=available_talent_points(checkpoint.level)
    rule=ir.provenance.get('talent_tree_rules') or {}
    points_per_row=int(rule.get('points_per_row') or 0)
    if points_per_row<=0:raise ValueError('P2_UNVERIFIED_TIER_RULE')
    rows=[];unknown_position=[];blocked=[];by_status=Counter();context_exclusions=[]
    source_rank_mismatches=[]
    for tid,capture in captures.items():
        if not capture.get('position_only') and int(capture['max_rank'])!=int(definitions[tid].max_rank):
            source_row=int(capture['row'])
            source_limit=min(int(capture['max_rank']),
                             max(0,budget-source_row*points_per_row))
            canonical_limit=min(int(definitions[tid].max_rank),
                                max(0,budget-source_row*points_per_row))
            source_rank_mismatches.append({'talent_id':tid,
                'source_max_rank':int(capture['max_rank']),
                'canonical_ir_max_rank':int(definitions[tid].max_rank),
                'possibly_missing_source_ranks_at_checkpoint':list(
                    range(canonical_limit+1,source_limit+1)),
                'reason':'CURRENT_SOURCE_RANK_CATALOGUE_DIFFERS_FROM_CANONICAL_IR'})
    for t in ir.talents:
        capture=captures.get(t.id)
        tree_row=t.metadata.get('row')
        if tree_row is None and capture is not None:tree_row=int(capture['row'])
        if tree_row is None:
            unknown_position.append({'talent_id':t.id,'tree_key':t.tree_key,'max_rank':t.max_rank,
                                     'reason':'UNKNOWN_TREE_POSITION_CANNOT_PROVE_LEVEL_ELIGIBILITY'})
            continue
        tree_row=int(tree_row)
        # No rank can fit in this checkpoint when one point plus row unlock exceeds budget.
        if tree_row*points_per_row+1>budget:
            by_status['UNREACHABLE_BY_TIER_BUDGET']+=1
            continue
        if capture and str(capture.get('identity_status','')).startswith('STALE_'):
            unknown_position.append({'talent_id':t.id,'tree_key':t.tree_key,'max_rank':t.max_rank,
                'reason':'SOURCE_TALENT_IDENTITY_SUPERSEDED_REQUIRES_CANONICAL_REINGEST',
                'source_url':capture.get('source_url'),
                'identity_status':capture.get('identity_status')})
            continue
        max_reachable=min(int(t.max_rank),budget-tree_row*points_per_row)
        for rank in range(1,max_reachable+1):
            # One legal witness must accompany every rank; do not use stale
            # source high-rank numbers for an impossible level 20 allocation.
            witness=_witness(t,rank,ir.talents,budget,points_per_row,override_rows=captures)
            if witness is not None:
                try:check_structural_allocation(ir,witness,checkpoint,override_rows=captures)
                except ValueError:witness=None
            if witness is None:
                blocked.append({'talent_id':t.id,'rank':rank,'reason':'NO_PROVEN_TIER_WITNESS'})
                continue
            # Source-backed rank numeric or executable IR modifier.
            effects,status=_effect_domains(t,rank,(capture if capture and not capture.get('position_only') else None))
            effects=list(effects)
            if learned is not None:
                additional,excluded,unresolved=_source_scope_completion(t,rank,effects,learned)
                effects.extend(additional)
                context_exclusions.extend({'talent_id':t.id,'rank':rank,**e} for e in excluded)
                blocked.extend({'talent_id':t.id,'rank':rank,**e} for e in unresolved)
            # Every source L0 value has an explicit checkpoint-context
            # interpretation; a known numerical tooltip for an unlearned
            # ability is NOT free kill-speed value for this checkpoint.
            for effect in effects:
                source=effect.get('source')
                conditional=bool(capture is not None and source==capture.get('source_url'))
                if conditional and learned is not None and capture.get('condition')=='relevant_ability_learned_and_executable':
                    if str(effect['target']).lower() not in learned:
                        effect['context_status']='ZERO_TARGET_NOT_LEARNED_IN_PINNED_SPELLBOOK'
                        effect['context_l0_value']=0.0
                    else:
                        effect['context_status']='POTENTIAL_CONDITIONAL_VALUE'
                        effect['context_l0_value']=effect['sourced_value']
                elif conditional and capture.get('condition')=='competing_threat_target':
                    effect['context_status']='ZERO_SOLO_NO_COMPETING_THREAT_TARGET'
                    effect['context_l0_value']=0.0
                elif effect.get('condition') and effect.get('context_uncertainty'):
                    effect['context_status']='CONDITIONAL_SOURCE_L0_UNCALIBRATED'
                    effect['context_l0_value']=effect['sourced_value']
                else:
                    effect['context_status']='POTENTIAL_SOURCE_EFFECT'
                    effect['context_l0_value']=effect['sourced_value']
            if not effects:
                blocked.append({'talent_id':t.id,'rank':rank,'reason':'NO_L0_NUMERIC_EFFECT'})
            elif not all(isinstance(d['sourced_value'],float) for d in effects):
                raise AssertionError('P2_UNEXPECTED_NON_NUMERIC_EFFECT')
            source_rank=next((r for r in t.ranks if int(r.rank)==rank),None)
            staged_l0=(source_rank.provenance.get('checkpoint_source_l0') if source_rank else None)
            rows.append({'talent_id':t.id,'rank':rank,'tree_key':t.tree_key,'tier_row':tree_row,
                         'witness':witness,'l0_status':status,'l0_effects':effects,
                         'l2_supported':bool(next((r.modifiers for r in t.ranks if r.rank==rank),())),
                         'source_url':(capture or {}).get('source_url') or (staged_l0 or {}).get('source_url'),
                         'potentially_contextual':bool((capture and capture.get('condition')) or staged_l0),
                         'context_uncertainty':(capture or {}).get('context_uncertainty') or
                             (staged_l0 or {}).get('context_uncertainty')})
            by_status[status]+=1
    result={'checkpoint':{'class_key':checkpoint.class_key,'level':checkpoint.level,'profile':checkpoint.profile,
                'use_runes':checkpoint.use_runes,'source_build':checkpoint.source_build},
            'point_budget':budget,'known_reachable_rank_count':len(rows),
            'l0_scored_reachable_rank_count':sum(bool(r['l0_effects']) for r in rows),
            'source_only_l0_rank_count':by_status['SOURCE_OBSERVED_L0_ONLY'],
            'l2_unsupported_scored_rank_count':sum(bool(r['l0_effects']) and not r['l2_supported'] for r in rows),
            'unknown_position_families':unknown_position,'blocked':blocked,
            'source_rank_mismatches':source_rank_mismatches,
            'rank_rows':rows,'status_counts':dict(by_status),'source_scope_context_exclusions':context_exclusions,
            'source_allocation_rules':{tid:{'row':r['row'],
                **({'prerequisite':r['prerequisite']} if r.get('prerequisite') else {})}
                for tid,r in captures.items()},
            'p2_pass':not blocked and not unknown_position and not source_rank_mismatches and len(rows)>0 and checkpoint.profile=='unrestricted',
            'allocation_l0_composer':'source_rank_feature_vectors_with_explicit_interaction_detection_not_s_per_mob',
            'spellbook_scoped_l0_completeness_checked':learned is not None,
            'source_build_bridge':source_build_bridge}
    return result


def evaluate_p2_allocation_l0(certificate:dict,ir,selection:Mapping[str,int],checkpoint:P2Checkpoint):
    """Composable L0 rank vectors for ANY structurally legal selection.

    A missing vector raises rather than masquerading as a zero modifier.
    Cross-talent effects on the same target are surfaced as interactions,
    not incorrectly summed into a damage/time prediction.
    """
    check_structural_allocation(ir,selection,checkpoint,
        override_rows=certificate.get('source_allocation_rules') or {})
    rows={(r['talent_id'],r['rank']):r for r in certificate['rank_rows']}
    selected=[];target_groups={}
    for tid,rank in sorted(selection.items()):
        r=rows.get((tid,rank))
        if r is None or not r['l0_effects']:raise ValueError(f'P2_L0_UNSCORED_LEGAL_RANK:{tid}:{rank}')
        selected.append(r)
        for effect in r['l0_effects']:
            target_groups.setdefault(str(effect['target']),set()).add(tid)
    overlaps={key:sorted(owners) for key,owners in target_groups.items() if len(owners)>1}
    return {'allocation':dict(selection),'point_spend':sum(selection.values()),
            'effects':[{'talent_id':r['talent_id'],'rank':r['rank'],'features':r['l0_effects']} for r in selected],
            'shared_target_interactions':overlaps,
            'context_dependencies':sorted({str(e.get('condition')) for r in selected
                for e in r['l0_effects'] if e.get('condition')}),
            'conditional_effect_uncertainty':[{'talent_id':r['talent_id'],
                'uncertainty':r['context_uncertainty']} for r in selected
                if r.get('context_uncertainty')],
            'rankable':True,'scalar_s_per_mob_predicted':False}
