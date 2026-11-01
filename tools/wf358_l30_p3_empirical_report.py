"""Publish build-context stat contributions and source-bounded measured Top5."""
import json
from pathlib import Path
from src.game.data.forever.source_checkpoint_p3_empirical_weights import fit_swap_weights,rank_all_legal_items_with_proxy
from src.game.data.forever.source_checkpoint_p3_causal_summary import summarize_causal_probes
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/wf358'

def run():
 stage=json.loads((ROOT/'evidence/wf357/WF357_L30_BEST_P3_STAGE.json').read_text())
 direct=json.loads((OUT/'WF358_L30_P3_TOP5_DIRECT_REPLAYS.json').read_text())
 model=fit_swap_weights(stage=stage,results=direct['results'],
     baseline_s_per_mob=direct['baseline']['mean_s_per_mob'],class_key='druid',level=30)
 context={(r['slot'],r['item_id']):r for r in model['per_item']}
 sections={}
 for slot,section in direct['slots'].items():
  top=[]
  for row in section['top5_measured_challengers']:
   r={**row,'measured_contextual_stat_contributions':context.get((slot,row['item_id']))}
   top.append(r)
  sections[slot]={'legal_item_count':section['source_legal_count'],
    'unknown_source_effect_count':section['unresolved_source_item_count'],
    'measured_candidate_count':section['direct_completed'],
    'top5_measured_challengers':top,
    'ranking_scope':'MEASURED_CHALLENGERS_NOT_ALL_SOURCE_ITEMS'}
 legal_proxy=rank_all_legal_items_with_proxy(stage=stage,model=model,class_key='druid',level=30,
     paired_offhand_weapon_id=direct['paired_offhand_weapon_id'])
 for slot,section in sections.items():
  section['all_source_legal_proxy']=legal_proxy[slot]
  paid={int(x['item_id']) for x in section['top5_measured_challengers']}
  all_paid={int(x['item_id']) for x in direct['results'] if x['slot']==slot and x['result']['status']=='COMPLETE'}
  proxy_ids={int(x['item_id']) for x in legal_proxy[slot]['known_component_top5']}
  attempted={int(x['item_id']) for x in direct['results'] if x['slot']==slot}
  section['proxy_top5_directly_completed_count']=len(proxy_ids & all_paid)
  section['proxy_top5_attempted_incomplete_item_ids']=sorted((proxy_ids & attempted)-all_paid)
  section['proxy_top5_not_attempted_item_ids']=sorted(proxy_ids-attempted)
  section['measured_top5_and_proxy_top5_overlap']=len(proxy_ids & paid)
 causal_path=OUT/'WF358_L30_CAUSAL_STAT_100MOB.json'
 causal=summarize_causal_probes(json.loads(causal_path.read_text())) if causal_path.exists() else None
 if causal is not None:
  (OUT/'WF358_L30_CAUSAL_STAT_WEIGHT_TABLE.json').write_text(json.dumps(causal,indent=2,sort_keys=True)+'\n')
 report={'checkpoint':'druid:L30:unrestricted','accepted_checkpoints':'1/148',
  'p3_status':'FAIL_PARTIAL_CONTEXTUAL_TOP5','legal_item_count':direct['source_legal_items'],
  'l0_item_count':direct['l0_assessed'],'slots':sections,'empirical_weights':model,
  'controlled_causal_weights':causal,
  'recovery_policy':direct['recovery_policy'],'context_fingerprint':direct['context_fingerprint'],
  'uncertainty':'unknown item effects and nonlinear out-of-sample ranking remain unresolved'}
 path=OUT/'WF358_L30_P3_CONTEXTUAL_TOP5_AND_WEIGHTS.json'
 path.write_text(json.dumps(report,indent=2,sort_keys=True,default=str)+'\n')
 return report
if __name__=='__main__':
 r=run();print(json.dumps({'status':r['p3_status'],'measured_axes':len(r['empirical_weights']['weights']),
   'cv_mae':r['empirical_weights'].get('cv_mae_s_per_mob')}))
