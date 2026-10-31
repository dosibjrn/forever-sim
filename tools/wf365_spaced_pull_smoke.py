"""Demonstrate a source-legal 20-yard scenario in BOTH available sim paths.

Legacy: pack assembly movement is a PROXY, not combat/threat simulation.
New: persistent, single-target CombatRuntime carries actor state during 20-yard
walks between targets; simultaneous 2/3-target packs are not yet implemented.
"""
from __future__ import annotations
import json,sqlite3,tempfile
from pathlib import Path
from src.shared.leveling.spaced_pulls import SpacedPullLayout
from src.rulesets.forever.classes.druid import Talents
from src.rulesets.forever.classes.druid.mechanics import _bear_pack
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.game.recovery_between_pulls import BetweenPullPolicy
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1]


def run(output:Path|None=None):
    t=Talents(ferocity=5,savage_fury=2,sharpened_claws=2,mangle=1)
    old={str(n):_bear_pack(30,t,n,mob_spacing_yards=20) for n in (1,2,3)}
    with tempfile.TemporaryDirectory(prefix='wf365_spaced_') as temp:
        source=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
        db=Path(temp)/'source.sqlite'
        with sqlite3.connect(f'file:{source.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(db) as dst:
            src.backup(dst)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(db):
            ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
            stage=json.loads((ROOT/'evidence/wf360/WF360_L30_P4_30S.json').read_text())['winner_stage']
            candidate=prepare_candidate(class_key='druid',level=30,stage=stage,source_ir=ir,strict_l2_item_effects=True)
            rec=BetweenPullPolicy(.25,.10,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')
            new={str(x):evaluate_persistent_candidate(candidate,level=30,mobs=2,
                 mob_spacing_yards=x,recovery_policy=rec,max_wall_s=10,max_cpu_s=10)
                 for x in (0,20)}
    layout=SpacedPullLayout(3,spacing_yards=20)
    assert new['0']['status']==new['20']['status']=='COMPLETE'
    assert old['3']['initial_melee_targets']==1
    assert new['20']['spaced_travel_s']==SpacedPullLayout(2).sequential_travel_total_s
    report={'schema':'wf365_spaced_pull_movement_smoke_v1',
            'positions_yards':list(layout.positions_yards),'initial_melee_targets':layout.initial_melee_targets(),
            'old_bear':{n:{k:r.get(k) for k in ('pull_size','profile','total_s','cycle_s','rotation',
                'initial_melee_targets','pack_assembly_s','spatial_multi_pull_fidelity')}
                for n,r in old.items()},
            'new_persistent_2_targets':{n:{k:r.get(k) for k in ('status','total_s','spaced_travel_s',
                'spaced_travel_events','mean_s_per_mob','spatial_mode','events')}
                for n,r in new.items()},
            'new_simultaneous_multi_enemy_pack':'NOT_IMPLEMENTED',
            'legacy_spaced_aggro_and_incoming_damage':'PROVISIONAL_NOT_EVENT_EXECUTED',
            'accepted_as_20yd_multi_pack':'NO'}
    if output is not None:
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return report

if __name__=='__main__':
    p=ROOT/'evidence/wf365/WF365_SPACED_PULL_SMOKE.json'
    print(json.dumps(run(p),sort_keys=True)[:1500])
