"""Compact machine-readable evidence from W3 real-runtime replay JSONs."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CASES={k:json.loads((ROOT/f'WF260_{k}_JOINT_REPLAY.json').read_text())
       for k in ('MAGE_L20','DRUID_L10','DRUID_L20')}
rows={}
for key,r in CASES.items():
    w=r['winner']; stage=w['gear_policy_result']['winner']; p=stage['winner']; g=stage['gear']
    rows[key]={
        'budget':r['total_budget_including_challenger'] if 'total_budget_including_challenger' in r else r['budget'],
        'real_attempts':r.get('total_real_simulator_attempts',r['attempted']),
        'successful':r['evaluated'],'blocked':r['blocked'],
        'legal_talent_states_discovered':r['legal_talent_states_discovered'],
        'talent_states_evaluated':r['talent_states_evaluated'],
        'talent_states_pending':r['pending_legal_talent_states'],
        'talent_source_families':r['source_talent_families'],
        'executable_talent_families':r['executable_talent_families'],
        'winning_allocation':w['allocation'],
        'winning_score_s_per_mob':w['score_s_per_mob'],
        'runner_up_score_s_per_mob':r['runner_up']['score_s_per_mob'] if r['runner_up'] else None,
        'winning_prefix':p['prefix'],'fallback':p['fallback'],
        'kill_s':p['kill_s'],'recovery_s':p['recovery_s'],
        'incoming_hits':p['incoming_hits'],'actor_survived':p['actor_survived'],
        'gear_ids':{slot:int(item['item_id']) for slot,item in g['slots'].items()},
        'gear_source_urls':{slot:item.get('source_url') for slot,item in g['slots'].items()},
        'first_stage_score_s_per_mob':r['stages'][0]['score_s_per_mob'],
        'status':'EVALUATED_BOUNDED',
        'source_ir_id':r['source_ir_id'],
        'complete_search':False,
    }
    if r.get('heldout_challenger'):
        rows[key]['heldout_challenger']={k:r['heldout_challenger'][k] for k in (
            'baseline','talents','seconds_per_mob','same_named_gear_as_new_winner',
            'valid_full_OG_comparison','incomparable_reason')}
coverage={'version':'v0.11.48.260','parent':'v0.11.48.259',
          'scope':'W3 on-demand source-legal talent neighbor + full gear/policy reoptimization',
          'new_runtime_capabilities':[
              'source-legal rank up/down, rank sweep, one-point reallocation with tier/prerequisite gates',
              'every changed talent allocation recompiles canonical IR and restarts actual named gear + ordered prefix search',
              'single hard real simulator budget includes blocked combat attempts and independent held-out replay',
              'observed combat actions inform talent relevance, measured score and marginal select subsequent candidates',
              'source family exploration before local exploitation; no Cartesian gear/talent grid',
              'exact per-talent/gear IR hash isolation, monotonic best-vs-budget evidence'],
          'cases':rows,
          'limitations':['mixed beta source snapshots and proxy player/enemy stats',
                         'talent coverage incomplete (Mage 4/54, Druid L20 24/52)',
                         'source tree rows/columns may be provisional',
                         'no exhaustive item acquisition route, no 1-60 leveling proof',
                         'bounded offensive ordered-prefix fallback only, not complete modes or legal actions',
                         'old Mage full gear fixture unavailable; heldout compares talent+policy at new named gear'],
          'validated_levels_done':0}
(ROOT/'WF260_COVERAGE_DELTA.json').write_text(json.dumps(coverage,indent=2)+'\n')
print(json.dumps({k:{'score':v['winning_score_s_per_mob'],'attempts':v['real_attempts'],
    'talent_states':v['talent_states_evaluated']} for k,v in rows.items()}))
