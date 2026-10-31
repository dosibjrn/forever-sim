"""Generic L0 rank -> opt-in L2 atomic probe, deliberately not a build optimum.

Candidates are JSON data; runner has NO class-specific talent or spell names.
The 100-mob source proxy is never scored for a candidate missing effects.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path

from src.game.checkpoint_pipeline import checkpoint_enemy
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint,check_structural_allocation
from src.game.data.forever.source_rank_promotion import promote_atomic_source_talent_effects
from src.game.model import PolicyDefinition,PolicyRuleDefinition
from src.game.recovery_threshold_search import search_recovery_thresholds
from src.game.talents import apply_talent_selection


def probe(source:dict):
    cls=str(source['class_key']);level=int(source['level'])
    ir=build_game_ir_slice(class_key=cls,level=level,ability_db_path=source['source_db'])
    if ir is None:raise ValueError('PROBE_MISSING_GAME_IR')
    if ir.provenance['talent_tree_rules']['source_build']!=source['source_build']:
        raise ValueError('PROBE_WRONG_SOURCE_BUILD')
    upgraded,ledger=promote_atomic_source_talent_effects(ir)
    enemy=checkpoint_enemy(ir=ir,level=level)
    family=str(source['policy_action_family'])
    actions=[a for a in ir.actions if a.family_key==family]
    if len(actions)!=1:raise ValueError('PROBE_POLICY_ACTION_NOT_UNIQUE')
    policy=PolicyDefinition(id='source_family_probe:'+family,label='Fixed source action',
        rules=(PolicyRuleDefinition(id='source:'+family,action_id=actions[0].id),))
    rows=[]
    for item in source['candidates']:
        choice=dict(item['selection']);bonus=int(item['bonus_talent_points'])
        status='NOT_SCORED'; reason=None
        try:
            # Structural audit does not entail executable talent semantics.
            check_structural_allocation(ir,choice,P2Checkpoint(cls,level,source_build=source['source_build']),
                bonus_talent_points=bonus)
            structural='PASS'
        except ValueError as exc:
            structural='FAIL';reason=str(exc)
        missing=[{'talent_id':tid,'rank':rank,
                  'source_domains':[e['domain'] for e in next(t for t in ir.talents if t.id==tid)
                    .ranks[rank-1].provenance.get('checkpoint_source_l0',{}).get('effects',[])]}
                 for tid,rank in choice.items() if not next(t for t in upgraded.talents
                    if t.id==tid).ranks[rank-1].modifiers]
        best=None; attempts=None
        if structural=='PASS' and not missing:
            applied=apply_talent_selection(upgraded,choice,level=level,bonus_talent_points=bonus)[0]
            run=search_recovery_thresholds(ir_slice=applied,policy=policy,
                level=level,target_health=float(enemy.hp),count=100,
                health_fractions=(.5,),mana_fractions=(.1,),
                schedule_incoming_attacks=True,apply_target_defense=True)
            best=run['best']; attempts=run['candidates']
            status='SCORED_PARTIAL_TALENT_MODEL' if best else 'NO_SURVIVING_CANDIDATE'
        elif structural=='PASS':
            status='BLOCKED_UNEXECUTABLE_SELECTED_RANKS'
        else:status='BLOCKED_SOURCE_STRUCTURE'
        rows.append({'name':item['name'],'selection':choice,'spent':sum(choice.values()),
            'bonus_talent_points':bonus,'structural':structural,'status':status,
            'missing_rank_effects':missing,'seconds_per_mob':None if not best else best['seconds_per_mob'],
            'best_recovery':best,'scored_trials':attempts,'blocker':reason,
            'complete_talent_optimum':False})
    return {'schema':'wf387_atomic_source_talent_probe_v1',
        'source_build':source['source_build'],'checkpoint':{'class_key':cls,'level':level},
        'enemy':enemy.as_dict(),'policy_action_id':actions[0].id,
        'objective':'100 consecutive mobs with incoming, armor, paid full recovery',
        'max_complete_checkpoint_count_increase':0,'full_talent_optimum':False,
        'atomic_promotion':ledger,'candidates':rows}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('config',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=probe(json.loads(args.config.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,indent=2,ensure_ascii=False,sort_keys=True)+'\n')
    for r in data['candidates']:
        print(r['name'],r['status'],r['seconds_per_mob'],
              'unexecuted',len(r['missing_rank_effects']))
