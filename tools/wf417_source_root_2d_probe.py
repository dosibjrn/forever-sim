"""WF417: reproducible generic 2D root and armor mechanics smoke, not a P4/P7 certificate."""
from __future__ import annotations
import json, hashlib, sys, runpy
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
fixtures=runpy.run_path(str(PROJECT/"tests/test_wf417_2d_roots_and_armor_tdd.py"))
runtime, cc, damage=(fixtures[x] for x in ("runtime", "cc", "damage"))
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB


def count_swing(rt, target):
    return sum(e.kind=='IncomingAttackResolved' and e.actor_id==target
               for e in rt.result().events)


def run():
    control=runtime();control.engage_target('m1');control.select_target('m1')
    control.advance_to(6.)
    rooted=runtime();rooted.engage_target('m1');rooted.select_target('m1')
    rooted.schedule_action(cc(4))
    rooted.advance_to(6.)
    source=build_game_ir_slice(class_key='druid',level=20)
    ent=next(a for a in source.actions if a.family_key=='entangling_roots')
    from src.game.model import ControlEffect
    assert any(isinstance(e,ControlEffect) and e.control_id=='root' for e in ent.effects)
    return {'baseline':'WF416', 'mode':'2D_pair_sourced_mechanics_diagnostic',
        'scenario':{'monster_positions_yards':{'m0':[0,0],'m1':[20,0]},
                    'enemy_speed_yards_s':5,'incoming_swing_period_s':2,
                    'incoming_raw_per_hit':10,'probe_horizon_s':6},
        'without_root':{'m1_swings':count_swing(control,'m1'),
                        'actor_health':control.actor.resources['health']},
        'with_four_second_root':{'m1_swings':count_swing(rooted,'m1'),
                        'actor_health':rooted.actor.resources['health'],
                        'm1_in_melee': 'm1' in rooted._melee_targets},
        'sourced_druid_root':{'action_id':ent.id,'range_yards':ent.metadata.get('range_yards'),
            'control_effect':'root','caveat':'damage_break_chance_heartbeat_unmodeled'},
        'source_db_sha256':hashlib.sha256(Path(DEFAULT_DB).read_bytes()).hexdigest(),
        'status':'MECHANICS_PASS_NOT_CERTIFIED_CHECKPOINT'}

if __name__ == '__main__':
    print(json.dumps(run(),indent=2,sort_keys=True))
