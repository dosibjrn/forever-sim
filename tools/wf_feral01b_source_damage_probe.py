from pathlib import Path
import json,sqlite3
from src.game.data.forever.druid import build_source_slice
from src.game.talents import apply_talent_selection
from src.game.talent_search import search_talent_allocations
from src.v2.source_mode_search import evaluate_discovered_mode_search
ir=build_source_slice(20)
talent=next(t for t in ir.talents if t.id=='savage_fury')
changed,application=apply_talent_selection(ir,{'savage_fury':1},level=20)
base=evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=ir,max_policies_per_path=24)
new=evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=changed,max_policies_per_path=24)
b=[base['winner'],*base['alternatives']];n=[new['winner'],*new['alternatives']]
diff=[{'index':i,'baseline_s':x['seconds_per_mob'],'modified_s':y['seconds_per_mob'],'delta_s':round(y['seconds_per_mob']-x['seconds_per_mob'],8)} for i,(x,y) in enumerate(zip(b,n)) if x['seconds_per_mob']-y['seconds_per_mob']>1e-6]
res=search_talent_allocations(ir,level=20,evaluate=lambda s:(0.0,{}))
con=sqlite3.connect('data/forever/catalogue/forever_abilities.sqlite')
coverage=ir.provenance['talent_sqlite_coverage']
evidence={
'baseline':'v0.11.48.223','release':'v0.11.48.224','increment':'WF-FERAL01b-source-damage',
'source':talent.provenance[-1], 'rank_one_tooltip':talent.ranks[0].provenance,
'source_coverage':{'captured':coverage['captured'],'expected':coverage['expected'],'blockers':len(coverage['blockers']), 'all_rank_caps_verified':False,'all_tree_gates_verified':False},
'new_executable_talent':talent.id,'rank_one_effects':[{'target':m.target_id,'kind':m.kind,'value':m.value} for m in talent.ranks[0].modifiers],
'missing_actions':talent.metadata['unavailable_action_targets'],'source_rank_cap_verified':False,'source_tree_gate_verified':False,
'actions_modified':list(application.applied_modifiers),'bounded_candidate_count':res.candidate_count,
'bounded_candidates_source_legality_verified':False,
'fixed_mode_probe':{'policies':len(b),'changed_policy_count':len(diff),'changed':diff,
                    'baseline_best_s':base['winner']['seconds_per_mob'],
                    'modified_best_s':new['winner']['seconds_per_mob']},
'legacy_full_feral_replay':'BLOCKED: missing rank records, tier/position/prerequisites, multiple effects and level legality',
'checkpoint_status':'BLOCKED','source_db_integrity':con.execute('PRAGMA integrity_check').fetchone()[0],
}
Path('WF_FERAL01B_SOURCE_DAMAGE_EVIDENCE_v0.11.48.224.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({k:evidence[k] for k in ['source_coverage','new_executable_talent','bounded_candidate_count','fixed_mode_probe','source_db_integrity']},indent=2))
