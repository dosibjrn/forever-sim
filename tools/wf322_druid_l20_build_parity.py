"""Druid L20 only: newer beta-client observation versus canonical index L2.

Reuses production Game IR, joint gear/talent/policy search and held-out oracle.
A web-text observation stage is never a verified detail-HTML promotion.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import process_time_ns

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.source_index_rank_parity import indexed_rank_fact
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_stateful_budgeted import _make_policy
from src.v2.generic_backend import _policy_combat_evaluation
from tools.wf319_druid_l20_current_source import _build_at
from tools.wf297_druid_l20_checkpoint import run as existing_joint_search

OBS=Path(__file__).resolve().parents[1]/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json'


def _index_rows_hash(db):
    with sqlite3.connect(db) as con:
        rows=con.execute('SELECT class_key,spell_id,raw_listview_json FROM spell_index ORDER BY class_key,spell_id').fetchall()
    return sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()


def _wrath_only_l2(ir):
    score,exe,details=_policy_combat_evaluation(ir,level=20,
        policy_override=_make_policy(ir,'wrath:5178'),schedule_incoming_attacks=True)
    if score is None or exe is None or not exe.timeline.target_defeated or not details['actor_survived']:
        raise ValueError('WRATH_ONLY_REAL_L2_DID_NOT_SURVIVE')
    return {'score_s_per_mob':score.seconds_per_mob,
            'kill_s':exe.timeline.target_death_s,
            'recovery_s':details['recovery']['total_s'],
            'events':details['event_transitions_new'],
            'survived':details['actor_survived']}


def run(*,stage:Path,observations:Path=OBS,as_of:date=date(2026,10,13)):
    if stage.exists():
        raise FileExistsError('REFUSE_TO_REPLACE_STAGE')
    stage.parent.mkdir(parents=True,exist_ok=True)
    source_hash_before=sha256(DEFAULT_DB.read_bytes()).hexdigest()
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(stage) as dest:
        src.backup(dest)
    imported=ingest_observations(stage,observations)
    assert _index_rows_hash(stage)==_index_rows_hash(DEFAULT_DB)
    raw_observations=json.loads(observations.read_text())['observations']
    source_facts=[]
    started=process_time_ns()
    with _build_at(as_of):
        for obs in raw_observations:
            query=dict(class_key=obs['class_key'],name=obs['name'],
                required_level=obs['required_level'],effect_kind=obs['effect_kind'])
            canonical=indexed_rank_fact(**query,db_path=DEFAULT_DB)
            staged=indexed_rank_fact(**query,db_path=stage)
            fields=['mana','cast_s']+(
                ['low','high','periodic_total','duration_s'] if obs['effect_kind']=='direct_periodic_damage'
                else ['low','high'] if obs['effect_kind'] in ('direct_damage','direct_heal')
                else ['total','duration_s'])
            changes={field:{'canonical':canonical[field],'observed':staged[field]}
                     for field in fields if canonical[field]!=staged[field]}
            source_facts.append({'spell_id':obs['spell_id'],'name':obs['name'],
                'required_level':obs['required_level'],'changed':changes,
                'source_build':staged['source_build'],
                'web_text_urls':staged['external_source_urls'],
                'html_independently_sha_verified':False})
        before_ir=build_game_ir_slice(class_key='druid',level=20)
        after_ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
        fixed_before=_wrath_only_l2(before_ir)
        fixed_after=_wrath_only_l2(after_ir)
        canonical_joint=existing_joint_search()
        observed_joint=existing_joint_search(ability_db_path=stage)
    cpu_ns=process_time_ns()-started
    if sha256(DEFAULT_DB.read_bytes()).hexdigest()!=source_hash_before:
        raise ValueError('CANONICAL_SOURCE_DB_WAS_MUTATED')
    if canonical_joint['new_checkpoint_count'] or observed_joint['new_checkpoint_count']:
        raise ValueError('UNVERIFIED_WEB_TEXT_MUST_NOT_ACCEPT_CHECKPOINT')
    return {'schema':'wf322_druid_l20_web_observed_build_parity_v1',
       'case':'druid:L20:unrestricted','as_of':as_of.isoformat(),
       'source_build':'1.60.1.70338','accepted_checkpoints_before':0,
       'accepted_checkpoints_after':0,'checkpoint_denominator':148,
       'canonical_sqlite_sha256':source_hash_before,
       'stage_sqlite_sha256':sha256(stage.read_bytes()).hexdigest(),
       'canonical_index_unchanged':_index_rows_hash(stage)==_index_rows_hash(DEFAULT_DB),
       'web_text_observation_count':imported['count'],
       'web_text_observations_with_numeric_differences':sum(bool(x['changed']) for x in source_facts),
       'source_rank_differences':source_facts,
       'full_L2_fixed_wrath_policy':{'canonical':fixed_before,'web_observed_stage':fixed_after},
       'full_L2_independent_joint_search':{
           key:{'score_s_per_mob':r['comparison']['new_score_s_per_mob'],
                'held_out_score_s_per_mob':r['comparison']['old_score_s_per_mob'],
                'attempted':r['search']['attempted'],'evaluated':r['search']['evaluated'],
                'blocked':r['search']['blocked'],'events':r['search']['event_transitions'],
                'cpu_ns_including_heldout':r['controller_cpu_ns_including_old_replay'],
                'talent_states_evaluated':r['search']['talent_states_evaluated'],
                'legal_talent_states_discovered':r['search']['legal_talent_states_discovered'],
                'named_gear_states_evaluated':sum(s['gear_policy_result']['named_gear_states_evaluated']
                     for s in r['search']['stages']),
                'winner_talents':r['search']['winner']['allocation'],
                'complete_search':r['search']['complete_search'],
                'independent_replay_score_s_per_mob':r['comparison']['winner_independent_scratch_replay_s_per_mob'],
                'unmatched_source_ranks':r['source_completeness']['unrepresented'],
                'missing_verified_html':r['source_completeness']['missing_independently_verified_spell_detail_html'],
                'winner_item_acquisition_routes_unverified':len(r['source_completeness']['selected_item_acquisition_routes_unverified']),
                'unverified_external_rank_observations':r['source_completeness']['external_web_text_observations_not_html_verified'],
                'formal_validated_checkpoint':r['formal_validated_checkpoint']}
           for key,r in [('canonical',canonical_joint),('web_observed_stage',observed_joint)]},
       'controller_cpu_ns_including_fixed_and_joint':cpu_ns,
       'limitations':['External web text is NOT independently SHA-verified HTML or in-game server verification.',
                      'Current source index remains unchanged; stage is evidence-only.',
                      'Not all legal ranks/actions/effects/gear acquisitions are complete.',
                      'Joint search is bounded; global gear/talent/policy optimum unproven.',
                      'Server-side approximate beta tuning remains separately unresolved.']}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stage',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--observations',type=Path,default=OBS)
    p.add_argument('--as-of',type=date.fromisoformat,default=date(2026,10,13))
    a=p.parse_args()
    result=run(stage=a.stage,observations=a.observations,as_of=a.as_of)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'accepted':result['accepted_checkpoints_after'],
        'changed_rank_count':result['web_text_observations_with_numeric_differences'],
        'joint':result['full_L2_independent_joint_search']},indent=2))
if __name__=='__main__':main()
