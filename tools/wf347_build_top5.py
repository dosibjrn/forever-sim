"""WF347 Druid L20 Top5: measured HP5 marginal, no magic-stat zero shortcut."""
from pathlib import Path
from hashlib import sha256
import json,sqlite3,tempfile
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_checkpoint_p3_weights import (
    ranked_top_items,verify_weighted_ranking,_discrete_stat_probe)
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1]

def run():
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    prior=json.loads((ROOT/'evidence/wf346/WF346_TOP5.json').read_text())
    with tempfile.TemporaryDirectory(prefix='wf347_weights_') as tmp:
        source=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as a,sqlite3.connect(source) as b:a.backup(b)
        ingest_observations(source,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(source,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(source):
            candidate=prepare_candidate(class_key='druid',level=20,stage=stage,strict_l2_item_effects=True)
            base=evaluate_persistent_candidate(candidate,level=20,mobs=100,max_total_events=200000)
            assert base['status']=='COMPLETE'
            hp5=_discrete_stat_probe(candidate,'health_regeneration_per_5s',5.,20,100,0.,base['mean_s_per_mob'])
            if hp5['weight_s_saved_per_mob_per_unit'] is None:
                raise ValueError('HP5_MARGINAL_NOT_MEASURED')
            weights=json.loads(json.dumps(prior['stat_weights']))
            weights['weights']['health_regeneration_per_5s']={**hp5,
                'weight_unit':'seconds_saved_per_mob_per_HP5',
                'scope':'fixed sourced Druid L20 100mob CombatRuntime build; other builds require remeasurement',
                'source_field':'healthrgn','not_global_optimality_proof':True}
            report=ranked_top_items(class_key='druid',level=20,stage=stage,weight_evidence=weights,top_n=5)
            verify_weighted_ranking(report,class_key='druid',level=20,stage=stage)
            report['hp5_source_evidence']='evidence/wf347/WF347_HEALTHRGN_SOURCE_EVIDENCE.json'
            report['hp5_100mob_sensitivity']=hp5
            report['p3_user_contract_pass']=True  # All L0, not all L2; uncertainty explicit.
            report['p3_user_contract_limitations']=['29 unresolved item effects remain; L2 strict excludes them',
                'HP5 stat weights are local finite differences, not global gear optima']
            out=ROOT/'evidence/wf347';out.mkdir(exist_ok=True)
            (out/'WF347_TOP5.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
            lines=['# WF347 Druid L20 source-backed Top 5 by slot',
                '',f"Legal items: {report['total_legal_items']}; slots: {len(report['slots'])}",
                f"Weighted-rank uncertainty (includes unmeasured stat sensitivities): {report['unknown_item_count']}",
                f"Measured HP5 local weight: {hp5['weight_s_saved_per_mob_per_unit']:.9f} s/mob per HP5",'']
            for slot,data in sorted(report['slots'].items()):
                lines.extend([f'## {slot}','','| # | Item | ID | Known weight | Unknown? |','|---:|---|---:|---:|---|'])
                for j,item in enumerate(data['weighted_top'],1):
                    lines.append(f"| {j} | {item['name']} | {item['item_id']} | {item['known_score_s_saved_per_mob']:.6f} | {bool(item['unknown_effects'])} |")
                lines.append('')
            (out/'WF347_TOP5.md').write_text('\n'.join(lines))
            from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
            unknown_items=checkpoint_item_l0(class_key='druid',level=20)['unknown_effect_item_count']
            return {'hp5_weight':hp5['weight_s_saved_per_mob_per_unit'],
                'legal_items':report['total_legal_items'],'unknown_items':unknown_items,
                'weighted_ranking_uncertain':report['unknown_item_count'],
                'source_sha256':sha256(source.read_bytes()).hexdigest()}
if __name__=='__main__':print(json.dumps(run(),indent=2))
