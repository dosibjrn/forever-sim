"""100-mob contextual gear Top5 from independently discovered L30 build."""
from pathlib import Path
from time import monotonic
from hashlib import sha256
import json,os,sqlite3,tempfile
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,verify_checkpoint_item_l0
from src.game.data.forever.source_checkpoint_p3_weights import budgeted_measured_stat_weights,ranked_top_items,verify_weighted_ranking
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint,evaluate_p2
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from tools.wf321_ingest_control_observations import ingest as ingest_control
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/wf351'
def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13';t=monotonic()
    inv=checkpoint_item_l0(class_key='druid',level=30);verify_checkpoint_item_l0(inv,class_key='druid',level=30)
    OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wf351_l30_') as tmp:
        src=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(src) as b:a.backup(b)
        ingest_observations(src,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(src,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(src):
            ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=src)
            p2=evaluate_p2(ir,P2Checkpoint('druid',30),
                source_observations_path=ROOT/'evidence/wf350/druid_l30_source_talent_catalogue_70338.json',
                spellbook_path=ROOT/'evidence/wf348/druid_spellbook_70338_level1_30.json')
            if not p2.get('p2_pass') or p2.get('known_reachable_rank_count')!=117:raise ValueError('L30_P2_INCOMPLETE')
            opts={**JOINT_ARGS,'level':30,'ir_slice':ir,'talent_l0_certificate':p2,'max_evaluations':85,'max_event_transitions':13500,'initial_search':9,'search_per_gear':7,'max_gear_states':2,'evaluations_per_talent':29,'talent_corridor_reserve':3,'talent_screening_attempts':12,'exclude_unknown_item_effects':True}
            joint=run_source_budgeted_joint_talents(**opts)
            if not joint.get('winner'):raise ValueError('L30_NO_INDEPENDENT_SEED')
            stage=joint['winner'];cand=prepare_candidate(class_key='druid',level=30,stage=stage,source_ir=ir,strict_l2_item_effects=True)
            score=evaluate_persistent_candidate(cand,level=30,mobs=100,max_wall_s=60,max_total_events=200000)
            if score.get('status')!='COMPLETE':raise ValueError('L30_100MOB_INCOMPLETE:'+str(score.get('status')))
            print('L30 seed',score['mean_s_per_mob'],'s/mob',flush=True)
            weights=budgeted_measured_stat_weights(candidate=cand,class_key='druid',level=30,mobs=100,max_wall_s=42.,max_measured_axes=6)
            print('Measured stat axes',len(weights['weights']),flush=True)
            report=ranked_top_items(class_key='druid',level=30,stage=stage,weight_evidence=weights,top_n=5,source_certificate=inv)
            verify_weighted_ranking(report,class_key='druid',level=30,stage=stage)
            assert report['total_legal_items']==1974 and len(report['slots'])==18
            assert all(len(x['weighted_top'])==min(5,x['available_legal']) for x in report['slots'].values())
            (OUT/'WF351_L30_SEED_STAGE.json').write_text(json.dumps(stage,indent=2,sort_keys=True,default=str)+'\n')
            (OUT/'WF351_L30_P3_TOP5.json').write_text(json.dumps(report,indent=2,sort_keys=True,default=str)+'\n')
            summary={'checkpoint':'druid:L30:unrestricted','p1':'PASS','p2':'PASS','p3_l0':report['p3_pass'],'p3_user_contract_pass':False,'p3_status':'PARTIAL_MEASURED_CONTEXT_NOT_ALL_AXIS_WEIGHTS','measured_stat_axes':len(weights['completed_stat_probes']),'l0_item_count':report['total_legal_items'],'slots':len(report['slots']),'unknown_effect_items':inv['unknown_effect_item_count'],'uncertain_weight_ranking_items':report['unknown_item_count'],'p4_p5_p6':'NOT RUN','accepted_checkpoints':'1/148','seed_discovery':'independent bounded L30 joint, no historical seed','seed_attempts':joint['attempted'],'seed_l2_evaluations':joint['evaluated'],'seed_events':joint['event_transitions'],'seed_100mob_s_per_mob':score['mean_s_per_mob'],'seed_100mob_events':score.get('events'),'source_context_sha256':joint['source_context_sha256'],'ability_db_sha256':sha256(src.read_bytes()).hexdigest(),'catalogue_sha256':inv['catalogue_sha256'],'limitations':['build-local stat weights, not proof of global optima','unknown item effects are explicit, not zero','P4/P5 independent deadline-bound searches not run'],'elapsed_wall_s':monotonic()-t}
            (OUT/'WF351_L30_P3_SUMMARY.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
            lines=['# WF351 Druid L30 100-mob-context Top 5 per equipment slot','',f"Seed: {score['mean_s_per_mob']:.5f} s/mob; legal L0 items: {report['total_legal_items']}; uncertain: {report['unknown_item_count']}",'','## Stat weights','', '| Stat | Weight (s/mob per point) | Status |','|---|---:|---|']
            for st,row in sorted(weights['weights'].items()):
                v=row.get('weight_s_saved_per_mob_per_unit');lines.append(f"| {st} | {'UNKNOWN' if v is None else f'{v:.8f}'} | {row['status']} |")
            for slot,section in sorted(report['slots'].items()):
                lines+=['',f'## {slot}: {section["available_legal"]} source-legal candidates','', '| # | Item | ID | Known s/mob value | Unknown effect? |', '|---:|---|---:|---:|---|']
                for rank,r in enumerate(section['weighted_top'],1):lines.append(f"| {rank} | {r['name']} | {r['item_id']} | {r['known_score_s_saved_per_mob']:.6f} | {bool(r['unknown_effects'])} |")
                lines+=['',f"Unknown challengers: {section['unknown_challenger_count']}; item contributions and source URLs in JSON."]
            (OUT/'WF351_L30_P3_TOP5.md').write_text('\n'.join(lines)+'\n')
            return summary
if __name__=='__main__':print(json.dumps(run(),indent=2),flush=True)
