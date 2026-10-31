"""Reuse frozen self-discovered WF351 L30 seed and OS-isolate stat probes."""
from pathlib import Path
from hashlib import sha256
import json,sqlite3,tempfile,os
from time import monotonic
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,verify_checkpoint_item_l0
from src.game.data.forever.source_checkpoint_p3_weights import ranked_top_items,verify_weighted_ranking
from src.game.data.forever.source_checkpoint_p3_isolated import measured_axis_suite
from src.game.data.forever.source_checkpoint_p3_acceptance import l0_gear_top5_certificate

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/wf352'

def run(axes=None,per_probe_timeout_s=8.):
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    OUT.mkdir(exist_ok=True,parents=True)
    stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    old=json.loads((ROOT/'evidence/wf351/WF351_L30_P3_TOP5.json').read_text())['stat_weights']
    inv=checkpoint_item_l0(class_key='druid',level=30)
    verify_checkpoint_item_l0(inv,class_key='druid',level=30)
    with tempfile.TemporaryDirectory(prefix='wf352_l30_') as tmp:
        src=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a, sqlite3.connect(src) as b:
            a.backup(b)
        ingest_observations(src,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(src,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(src):
            ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=src)
            cand=prepare_candidate(class_key='druid',level=30,stage=stage,source_ir=ir,strict_l2_item_effects=True)
            base=evaluate_persistent_candidate(cand,level=30,mobs=100,max_total_events=200000,max_wall_s=35)
            if base.get('status')!='COMPLETE' or abs(base['mean_s_per_mob']-19.02888801859612)>1e-7:
                raise ValueError('L30_BASELINE_SOURCE_STAGE_PARITY_FAILED:'+str(base))
            print('BASELINE_PARITY',base['mean_s_per_mob'],base.get('events'),flush=True)
            weights=measured_axis_suite(candidate=cand,class_key='druid',level=30,
                base_score_s_per_mob=base['mean_s_per_mob'],
                out_dir=OUT/'axis_probes',per_probe_timeout_s=per_probe_timeout_s,
                axes=axes,prior_weights=old)
            print('ISOLATED_EVENTS',weights['worker_events'],flush=True)
            report=ranked_top_items(class_key='druid',level=30,stage=stage,
                weight_evidence=weights,top_n=5,source_certificate=inv)
            verify_weighted_ranking(report,class_key='druid',level=30,stage=stage)
            if len(report['slots'])!=18 or report['total_legal_items']!=1974:
                raise ValueError('P3_ITEM_UNIVERSE_CHANGED')
            certificate=l0_gear_top5_certificate(report)
            if not certificate['pass']:raise ValueError('L30_P3_FAIL:'+str(certificate['failures']))
            (OUT/'WF352_P3_ACCEPTANCE.json').write_text(json.dumps(certificate,indent=2,sort_keys=True)+'\n')
            measured=[k for k,v in weights['weights'].items() if v['weight_s_saved_per_mob_per_unit'] is not None]
            summary={'release':'WF352','parent':'WF351 on published WF350','checkpoint':'druid:L30:unrestricted',
                'accepted_checkpoints':'1/148','p1':'PASS 86/86','p2':'PASS 117/117',
                'p3':'PASS_L0_WITH_EXPLICIT_UNCERTAINTY', 'p4_p5_p6':'NOT RUN','legal_items':1974,'slots':18,
                'baseline_100mob_s_per_mob':base['mean_s_per_mob'],'baseline_events':base.get('events'),
                'measured_axes':measured,'uncertain_items':report['unknown_item_count'],
                'axis_events':weights['worker_events'],
                'source_stage_sha256':sha256((ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').read_bytes()).hexdigest(),
                'p3_accepted':True,'p3_certificate':certificate,
                'reason':'L0 gate accepts explicitly uncertain effects like WF347; not all L2 item effects executable and no global optimum claim'}
            (OUT/'WF352_L30_P3_TOP5.json').write_text(json.dumps(report,indent=2,sort_keys=True,default=str)+'\n')
            (OUT/'WF352_SUMMARY.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
            lines=['# WF352 L30 Top 5 — OS-isolated 100-mob measurements','',
                   f"Seed {base['mean_s_per_mob']:.6f} s/mob; measured axes: {len(measured)}; uncertain items: {report['unknown_item_count']}",
                   '','## Stat weights','', '| Stat | Weight (s/mob per point) | Status |','|---|---:|---|']
            for st,v in sorted(weights['weights'].items()):
                w=v['weight_s_saved_per_mob_per_unit'];lines.append(f"| {st} | {'UNKNOWN' if w is None else f'{w:.8f}'} | {v['status']} |")
            for slot,sec in sorted(report['slots'].items()):
                lines.extend(['',f'## {slot} ({sec["available_legal"]} legal candidates)','',
                        '| # | Item | ID | Known score | Unknown? |','|---:|---|---:|---:|---|'])
                for i,item in enumerate(sec['weighted_top'],1):
                    lines.append(f"| {i} | {item['name']} | {item['item_id']} | {item['known_score_s_saved_per_mob']:.5f} | {bool(item['unknown_effects'])} |")
            (OUT/'WF352_L30_P3_TOP5.md').write_text('\n'.join(lines)+'\n')
            return summary
if __name__=='__main__':
    import sys
    axes=sys.argv[1:] or None
    print(json.dumps(run(axes=axes),indent=2),flush=True)
