"""Cold independent Druid L20 gear×talent×policy search, no legacy seed.

The outer controller imposes a HARD wall-clock timeout; a killed child has
no valid checkpoint result. Uses the existing source joint and persistent L2.
"""
from __future__ import annotations
import json,os,sqlite3,tempfile,sys
from hashlib import sha256
from pathlib import Path
from time import monotonic,process_time
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.rulesets.forever.items.runtime_selection import catalogue_path
from src.rulesets.forever.items.source_equipment_semantics import ledger_path
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_persistent_joint_finalists import select_persistent_finalists
from tools.wf321_ingest_control_observations import ingest as ingest_control
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS
ROOT=Path(__file__).resolve().parents[1]

def run(*,max_evaluations=145,max_events=17000,max_finalists=3,max_screens=16):
    if max_evaluations<1 or max_events<1:raise ValueError('INVALID_BUDGET')
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    wall=monotonic();cpu=process_time()
    with tempfile.TemporaryDirectory(prefix='wf340_source_') as tmp:
        staged=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(staged) as dst:src.backup(dst)
        ingest_observations(staged,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(staged,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(staged):
            options={**JOINT_ARGS,'max_evaluations':max_evaluations,'max_event_transitions':max_events,
                'evaluations_per_talent':35,'initial_search':8,'search_per_gear':9,'max_gear_states':2,
                'talent_corridor_reserve':4,'talent_screening_attempts':18,
                'post_talent_refinement_budget':0,'exclude_unknown_item_effects':True}
            joint=run_source_budgeted_joint_talents(**options)
            joint_wall=monotonic()-wall; joint_cpu=process_time()-cpu
            if not joint.get('winner'):raise ValueError('NO_INDEPENDENT_JOINT_WINNER')
            finalist=select_persistent_finalists(class_key='druid',level=20,joint_result=joint,
                screen_mobs=3,finalist_mobs=100,max_finalists=max_finalists,
                max_screen_candidates=max_screens,max_screen_wall_s=3.,max_finalist_wall_s=5.,
                max_shared_evidence_events=45000,max_shared_evidence_cpu_s=13.,
                strict_l2_item_effects=True)
            winner=finalist.get('winner')
            if not winner or winner['persistent']['status']!='COMPLETE':
                raise ValueError('NO_FULL_100_MOB_WINNER')
            s=winner['stage'];p=s['gear_policy_result']['winner']['winner']
            from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
            inventory=checkpoint_item_l0(class_key='druid',level=20)
            known={int(r['item_id']):r for r in inventory['source_items']}
            uncertain={slot:known[int(item['item_id'])]['unresolved_effects']
                for slot,item in s['gear_policy_result']['winner']['gear']['slots'].items()
                if known[int(item['item_id'])]['unresolved_effects']}
            if uncertain:raise ValueError('UNSUPPORTED_WINNER_ITEM_EFFECTS:'+str(uncertain))
            # Number of UNIQUE complete builds exposed as independently paid
            # stages, not a fabricated count of all internal L2 attempts.
            def identity(st):
                gp=(st.get('gear_policy_result') or {}).get('winner') or {}
                g=gp.get('gear') or {};policy=gp.get('winner') or {}
                return json.dumps({'talents':st.get('allocation'),
                    'gear':sorted((k,int(v['item_id'])) for k,v in g.get('slots',{}).items()),
                    'opening':policy.get('prefix'),'fallback':policy.get('fallback'),
                    'guarded':policy.get('guarded_conditions')},sort_keys=True,default=str)
            complete_stages=[s for s in joint.get('stages',()) if s.get('score_s_per_mob') is not None and (s.get('gear_policy_result') or {}).get('winner')]
            ids={identity(s) for s in complete_stages}
            return {'schema':'wf340_druid_l20_cold_p4_v1','checkpoint':'druid:L20:unrestricted',
                'source_stage':'canonical_sqlite_plus_WF322_70338_plus_WF321_control_plus_source_equipment_semantics',
                'oracle_seeded':False,'joint_attempts':joint['attempted'],
                'joint_evaluated':joint['evaluated'],'joint_blocked':joint['blocked'],
                'joint_events':joint['event_transitions'],
                'persistent_events':finalist['paid_persistent_events'],
                'total_events':joint['event_transitions']+finalist['paid_persistent_events'],
                'total_paid_attempts':joint['attempted']+finalist['screen_evaluated']+finalist['finalists_evaluated'],
                'source_context_sha256':joint['source_context_sha256'],
                'item_catalogue_sha256':sha256(Path(catalogue_path()).read_bytes()).hexdigest(),
                'equipment_semantics_sha256':sha256(ledger_path().read_bytes()).hexdigest(),
                'staged_source_sha256':sha256(staged.read_bytes()).hexdigest(),
                'distinct_paid_complete_stages_lower_bound':len(ids),
                'distinct_talent_allocations_paid_L2':joint.get('distinct_talent_allocations_paid_L2'),
                'screens':finalist.get('screen_evaluated'),
                'finalists_100mob':finalist.get('finalists_evaluated'),
                'finalists_100mob_completed':sum(x['persistent']['status']=='COMPLETE' for x in finalist['finalists']),
                'finalists_budget_blocked':sum(x['persistent']['status']!='COMPLETE' for x in finalist['finalists']),
                'screen_failures':finalist['screen_evaluated']-finalist['screen_completed'],
                'screening_events':finalist['paid_persistent_events'],
                'joint_wall_s':joint_wall,'joint_cpu_s':joint_cpu,
                'full_wall_s':monotonic()-wall,'full_cpu_s':process_time()-cpu,
                'winner':{'talents':winner['allocation'],
                    'gear':{k:int(v['item_id']) for k,v in s['gear_policy_result']['winner']['gear']['slots'].items()},
                    'opening':p['prefix'],'fallback':p['fallback'],
                    'predicted_single_mob_s_per_mob':s.get('score_s_per_mob'),
                    'actual_100mob_s_per_mob':winner['persistent']['mean_s_per_mob'],
                    'actual_100mob_events':winner['persistent']['events'],
                    'combat_s':winner['persistent']['combat_s'],
                    'recovery_s':winner['persistent']['recovery_s'],
                    'maintenance_s':winner['persistent']['maintenance_s']},
                'notes':['The single-mob estimate is NOT the actual 100mob objective.',
                    'Unique full combinations count is a LOWER BOUND from paid stages, not all internal attempts.',
                    'P4 needs 30s end-to-end including process startup; P5/P6 not run.']}
if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--evaluations',type=int,default=145)
    ap.add_argument('--events',type=int,default=17000)
    ap.add_argument('--finalists',type=int,default=3)
    ap.add_argument('--screens',type=int,default=16)
    a=ap.parse_args()
    result=run(max_evaluations=a.evaluations,max_events=a.events,max_finalists=a.finalists,max_screens=a.screens)
    tmp=a.output.with_suffix('.partial')
    tmp.write_text(json.dumps(result,indent=2,sort_keys=True,default=str))
    tmp.replace(a.output)
    print(json.dumps({'status':'COMPLETE','full_wall_s':result['full_wall_s'],'winner':result['winner']['actual_100mob_s_per_mob']}),flush=True)
