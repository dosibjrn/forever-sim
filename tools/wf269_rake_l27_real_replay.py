"""WF269 real L27 source-action frontier with the named Dense Triangle Mace.

Not a recreation of the player's unidentified full L27 gear or L23-24 target.
"""
import json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.multi_pull import evaluate_repeated_pulls
from src.rulesets.forever.items.runtime_selection import available_items,item_payload,item_vector,effective_level
from src.v2.source_policy_search import synthesize_source_policies
from src.game.runtime.state import ActorState

source=build_game_ir_slice(class_key='druid',level=27)
item=next(i for i in available_items('druid',27,required_level_policy='observed') if i.item_id==3203)
ir,applied=apply_gear_selection(source,aggregate_stats=item_vector(item),
    selected_items=(item_payload(item,display_slot='weapon',effective_level=effective_level(item)),),
    source='canonical_sqlite_forever_catalogue')
env=synthesize_source_policies(ir,level=27,max_policies=28,include_auto_resource_fallback=True,
    mode_id='cat',budget_mode='balanced_frontier')
cat=[p for p in ir.policies if 'cat-builder-finisher' in p.id][0]
cases=[cat,*env['policies']]
rows=[];fail=[]
for p in cases:
    try:
        r=evaluate_repeated_pulls(ir_slice=ir,policy=p,level=27,
             target_health=484,count=3,pre_combat_action_ids=('cat_form:768',),
             post_combat_action_ids=('cancel_mode:cat',),
             prepared_first_pull_resources={'energy':100,'rage':0},
             recovery_mode='threshold',retain_mode_between_pulls=True,
             travel_time_s=2.2,apply_target_defense=True)
        rows.append({'id':p.id,'seconds_per_mob':r.seconds_per_mob,
                     'rake_in_policy':any(x.action_id=='rake:1822' for x in p.rules),
                     'actions':[[a['action_id'] for a in q['selected_actions']] for q in r.pulls],
                     'kill_s':[q['kill_s'] for q in r.pulls]})
    except (ValueError,RuntimeError) as exc:
        fail.append({'policy_id':p.id,'reason':str(exc)})
rows.sort(key=lambda x:(x['seconds_per_mob'],x['id']))
actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes);actor.transition_mode('cat')
report={'source':'WoW Forever canonical SQLite: captured current Rake ranks 2026-10-08, build qualified',
        'scope':'Druid 27 vs level 27 representative 484HP/qualified Classic defense, 3 pulls, only named weapon gear applied',
        'comparison_to_player_screenshot':'NOT same full gear (screenshot AP325 crit17.4%, modeled partial gear AP128 crit1.4%); not same target level (player L23-24)',
        'weapon':{'id':item.item_id,'name':item.name,'dps':item.weapon_dps},
        'actor_stats':{'attack_power':actor.stats.get('attack_power'),'melee_crit_chance':actor.stats.get('melee_crit_chance')},
        'generated':len(cases),'successful':len(rows),'failed':len(fail),'rejected':fail,
        'best':rows[0] if rows else None,
        'runnerup':rows[1] if len(rows)>1 else None,
        'rake_candidate_count':sum(x['rake_in_policy'] for x in rows),
        'rake_executed_count':sum(any('rake:1822' in seq for seq in x['actions']) for x in rows),
        'all_scored':rows,
        'frontier_unrepresented':env['supported_actions_not_represented'],
        'frontier_truncated':env['policy_frontier_truncated'],
        'ignored_source_legal_candidates':'bounded policy frontier, not a global optimum'}
path=Path(__file__).resolve().parents[1]/'WF269_L27_RAKE_REAL_REPLAY.json'
path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({k:v for k,v in report.items() if k in ('generated','successful','failed','best','runnerup','rake_candidate_count','rake_executed_count','actor_stats','frontier_truncated')},indent=2))
