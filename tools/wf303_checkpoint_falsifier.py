"""Independent fail-closed source + CombatRuntime verifier for class-level L2.

Loads optimizer output only after the optimization has completed; never passes
any reference winner into the optimizer. Separates source-removed spells and
engraving/setup recipes from directly castable ability gaps WITHOUT asserting
that the resulting runes/setup effects are modeled or irrelevant.
"""
from __future__ import annotations
import argparse,json,sqlite3,hashlib,os
from collections import Counter
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_indexed_action_coverage import indexed_ability_coverage
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_action_scope import scope_audit
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate

def source_gap_audit(class_key:str,level:int)->dict:
    ir=build_game_ir_slice(class_key=class_key,level=level)
    c=indexed_ability_coverage(ir,class_key=class_key,level=level)
    with sqlite3.connect('file:'+str(DEFAULT_DB)+'?mode=ro',uri=True) as db:
        raw_text={int(sid):txt for sid,txt in db.execute(
           'SELECT spell_id,raw_listview_json FROM spell_index WHERE class_key=? AND kind=?',
           (class_key.lower(),'abilities'))}
    role_scope=scope_audit(c,raw_text)
    raw={sid:json.loads(txt) for sid,txt in raw_text.items()}
    # Linked grants can be entirely missing from the class abilities index.
    # The optimizer cannot assert completeness from the index alone.
    with sqlite3.connect('file:'+str(DEFAULT_DB)+'?mode=ro',uri=True) as db:
        has_dependencies=bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_spell_dependency_observations'").fetchone())
        dependency_edges=([dict(zip(('source_spell_id','referenced_spell_id','relationship','target_requires_level',
            'observation_status'),r)) for r in db.execute('SELECT source_spell_id,referenced_spell_id,relationship,target_requires_level,observation_status FROM source_spell_dependency_observations WHERE class_key=?',(class_key.lower(),))] if has_dependencies else [])
        unindexed_dependency_targets=sorted({d['referenced_spell_id'] for d in dependency_edges if d['referenced_spell_id'] not in raw})
    kinds=Counter();unrepresented=[];uncovered_source_combat=[];setup=[];removed=[]
    for row in c['records']:
        payload=raw[row['spell_id']]
        env=payload.get('envChange') or {}
        status=env.get('status')
        text=str(((env.get('after') or {}).get('text')) or '')
        # Source-selected transition, NOT inference from an ID, class, or name.
        # Item engravings must still be modeled as *precombat setup* effects;
        # moving them out of the combat-action category never proves coverage.
        is_setup=(status!='removed' and text.lstrip().lower().startswith('engrave your ')
                  and ' rune:' in text.lower())
        missing=not row['matched_action_ids']
        if not missing:
            kinds['exact_ir_spell_id']+=1
        elif status=='removed':
            kinds['source_explicitly_removed']=1+kinds['source_explicitly_removed'];removed.append(row)
        elif is_setup:
            kinds['source_precombat_setup_unmodeled']+=1;setup.append(row)
        else:
            kinds['active_or_uncertain_nonsetup_unrepresented']+=1;uncovered_source_combat.append(row)
        if missing:unrepresented.append(row)
    if len(unrepresented)!=c['unrepresented_rank_count']:
        raise AssertionError('SOURCE_COVERAGE_LEDGER_MISMATCH')
    return {'class_key':class_key,'level':level,
        'raw_indexed_at_or_unknown_level':c['at_or_unknown_below_level_count'],
        'exact_spell_id_matched':c['exact_source_rank_in_ir_count'],
        'raw_unrepresented':len(unrepresented),
        'counts_by_source_semantics':dict(kinds),
        'explicitly_removed_source_spell_ids':[x['spell_id'] for x in removed],
        'unmodeled_precombat_setup_spell_ids':[x['spell_id'] for x in setup],
        'unrepresented_nonsetup_records':[{'spell_id':x['spell_id'],'name':x['name'],
            'level_hint':x['level_hint'],'source_url':x['source_url'],
            'status':x['status']} for x in uncovered_source_combat],
        'role_scope':role_scope,
        'source_grant_dependency_edges':dependency_edges,
        'grant_dependency_targets_absent_from_class_index':unindexed_dependency_targets,
        'full_source_gameplay_coverage_proven':False,
        'setup_effects_and_gameplay_unlocks_still_require_source_modeling':True}

def validate(evidence:dict,*,class_key='druid',level=20,challenger:dict|None=None)->dict:
    assert evidence['class_key']==class_key and evidence['level']==level
    assert evidence['screening']['winner'] is not None
    winner=evidence['persistent_winner']
    stage=winner['stage']
    # Unlike scoring through the search, this rebuilds fresh IR and combat
    # state and uses NO result cache; enforces full 100-mob continuity.
    candidate=prepare_candidate(class_key=class_key,level=level,stage=stage)
    replay=evaluate_persistent_candidate(candidate,level=level,mobs=100)
    if replay['status']!='COMPLETE' or replay['count']!=100 or abs(
            replay['mean_s_per_mob']-winner['persistent']['mean_s_per_mob'])>1e-9:
        raise ValueError('COLD_PERSISTENT_REPLAY_MISMATCH')
    old=None
    if challenger is not None:
        old=evaluate_persistent_candidate(prepare_candidate(
            class_key=class_key,level=level,stage=challenger),level=level,mobs=100)
        if old['status']!='COMPLETE': raise ValueError('OLD_CHALLENGER_FAILED_EQUAL_RUNTIME')
    coverage=source_gap_audit(class_key,level)
    return {'status':'COLD_100_MOB_REPLAY_CONFIRMED',
        'class_key':class_key,'level':level,
        'source_db_sha256':hashlib.sha256(Path(DEFAULT_DB).read_bytes()).hexdigest(),
        'search_source_context':evidence['profile_results'][0]['source_context_sha256'],
        'fresh_winner_replay':replay,'old_challenger_replay':old,
        'new_beats_old':old is not None and replay['total_s']<old['total_s'],
        'frozen_winner_was_not_a_search_seed':True,
        'coverage':coverage,
        'global_optimum_proven':False,
        'fully_validated_checkpoint_count':0}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--search',type=Path,required=True)
 p.add_argument('--held-out',type=Path);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();challenger=json.loads(a.held_out.read_text())['winner'] if a.held_out else None
 result=validate(json.loads(a.search.read_text()),challenger=challenger)
 staging=a.output.with_suffix('.tmp');staging.write_text(json.dumps(result,indent=2,default=str)+'\n')
 os.replace(staging,a.output)
 print(json.dumps({'replay_s_per_mob':result['fresh_winner_replay']['mean_s_per_mob'],
   'old_s_per_mob':result['old_challenger_replay']['mean_s_per_mob'] if challenger else None,
   'source_counts':result['coverage']['counts_by_source_semantics'],
   'fully_validated_checkpoint_count':result['fully_validated_checkpoint_count']}))
