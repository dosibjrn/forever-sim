from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.v2.decision_artifacts import bounded_candidate
from src.v2.decision_dashboard import build_decision_payload
from src.v2.dual_spec import build_status
from src.v2.endpoint_paths import analyze_frontier, candidate_matches, route_definitions
from src.v2.spec_matrix import build_matrix
from src.v2.constrained_routes import analyze_constraint, normalize_constraint, rerun_commands
from src.v2.mature_decision_artifacts import build_frontier


def _candidate(seconds, *, holy=0, fury=0, command=0, mph=200.0, name="x"):
    return {
        "level":20,
        "allocation":name,
        "talent_ranks":{"improved_seal_of_fury":fury,"seal_of_command":command},
        "tree_points":{"holy":holy,"protection":fury+5,"retribution":command+5},
        "talent_family":"mixed",
        "combat_profile":"retribution",
        "gear":"2h_normal",
        "pull_size":1,
        "policy":"balanced",
        "mobs_per_hour":mph,
        "score_s_per_100":1800.0,
        "cumulative_objective_s":seconds,
        "steps":[{"level":20,"talent_ranks":{"seal_of_command":command},"allocation":name}],
        "details":{"large":"debug payload"},
    }


def test_bounded_candidate_drops_debug_payload_but_keeps_machine_readable_steps():
    out=bounded_candidate(_candidate(100.0,command=1),include_steps=True)
    assert "details" not in out
    assert out["steps"][0]["talent_ranks"]=={"seal_of_command":1}


def test_paladin_route_identity_is_endpoint_constraint_not_majority_family():
    defs=route_definitions("paladin")
    mixed=_candidate(100.0,holy=8,command=1)
    assert candidate_matches(mixed,defs["retribution"])
    assert not candidate_matches(mixed,defs["holy"])


def test_endpoint_analysis_reports_regret_against_same_frontier_objective():
    frontier={"class":"paladin","levels":[{"level":20,"candidates":[
        _candidate(100.0,fury=1,mph=220,name="best"),
        _candidate(104.0,command=1,mph=210,name="ret"),
        _candidate(106.0,holy=11,mph=205,name="holy"),
    ]}]}
    paths,regret=analyze_frontier(frontier)
    assert paths["targets"]["20"]["routes"]["retribution"]["status"]=="available"
    assert regret["targets"]["20"]["routes"]["retribution"]["regret_percent"]==pytest.approx(4.0)
    assert regret["targets"]["20"]["routes"]["retribution"]["target_level_mobs_per_hour_delta"]==pytest.approx(-10.0)
    curve=regret["level_curve"][0]
    assert curve["level"]==20
    assert curve["routes"]["retribution"]["regret_percent"]==pytest.approx(4.0)


def test_endpoint_analysis_never_invents_unmodeled_milestones():
    paths,_=analyze_frontier({"class":"paladin","levels":[{"level":20,"candidates":[_candidate(100.0)]}]})
    assert paths["targets"]["30"]["status"]=="not_available_in_frontier"
    assert paths["targets"]["60"]["status"]=="not_available_in_frontier"


def test_endpoint_target_above_verified_cap_stays_available_and_is_labeled_provisional():
    candidate={**_candidate(100.0,command=1,name="ret40"),"level":40}
    paths,regret=analyze_frontier({
        "class":"paladin","verified_level_cap":30,
        "levels":[{"level":40,"candidates":[candidate]}],
    },targets=(40,))
    row=paths["targets"]["40"]
    assert row["status"]=="available"
    assert row["uses_unverified_levels"] is True
    assert row["verification_status"]=="provisional_above_verified_cap"
    assert row["unverified_from_level"]==31
    assert regret["targets"]["40"]["uses_unverified_levels"] is True


def test_decision_dashboard_schema_exposes_all_five_north_star_questions(tmp_path):
    payload=build_decision_payload(tmp_path,selected_level=20)
    assert payload["schema_version"]==1
    assert len(payload["questions"])==5
    assert not any(payload["questions"].values())
    assert payload["coverage"]["mage"]["levels"]==[]


def test_decision_dashboard_marks_raw_cross_class_throughput_non_comparable(tmp_path):
    payload=build_decision_payload(tmp_path,selected_level=20)
    assert payload["cross_class_comparable"] is False
    note=payload["comparability_note"].lower()
    assert "not a class ranking" in note
    assert "mage" in note and "paladin" in note and "druid" in note


def test_decision_dashboard_prefers_event_finalist_for_visual_curve(tmp_path):
    viewer=tmp_path/"state/games/forever-paladin/v2/viewer.json"
    viewer.parent.mkdir(parents=True)
    viewer.write_text(json.dumps({"views":{"experimental":{"level_summaries":[{
        "level":15,"best":{"mobs_per_hour":189,"allocation":"fast"},
        "event_validated_best":{"mobs_per_hour":219,"allocation":"event"},
        "decision_change_kind":"playstyle",
    }]}}}),encoding="utf-8")
    payload=build_decision_payload(tmp_path,selected_level=15)
    pala=next(c for c in payload["cards"] if c["class"]=="paladin")
    assert pala["event_validated_best"]["allocation"]=="event"
    assert payload["curves"]["paladin"][0]["mobs_per_hour"]==219
    assert payload["curves"]["paladin"][0]["fast_mobs_per_hour"]==189


def test_decision_dashboard_normalizes_mage_seconds_to_mobs_per_hour(tmp_path):
    viewer=tmp_path/"state/games/forever-mage/v2/viewer.json"
    viewer.parent.mkdir(parents=True)
    viewer.write_text(json.dumps({"views":{"smooth":{"level_summaries":[{
        "level":20,"best":{"score_s_per_100":3600,"allocation":"frost"},
    }]}}}),encoding="utf-8")
    payload=build_decision_payload(tmp_path,selected_level=20)
    assert payload["curves"]["mage"][0]["mobs_per_hour"]==pytest.approx(100.0)


def test_mature_frontier_adapter_preserves_reachable_prefix_and_normalizes_rate():
    @dataclass(frozen=True)
    class T:
        frost:int=0
        arcane:int=0
        fire:int=0
        def points(self): return self.frost+self.arcane+self.fire
    class E:
        Talents=T
        TREE_NAMES=("frost","arcane","fire")
        MODEL_FIDELITY={"rating":"mature"}
        @staticmethod
        def tree_points(t,name): return getattr(t,name)
        @staticmethod
        def final_allocation(t): return f"frost={t.frost},arcane={t.arcane},fire={t.fire}"
        @staticmethod
        def policy_desc(policy,level): return f"{policy}@{level}"
        @staticmethod
        def add_point(t,name):
            vals={"frost":t.frost,"arcane":t.arcane,"fire":t.fire}; vals[name]+=1
            return T(**vals)
        @staticmethod
        def owl_bonus(level,intensity): return (level,float(level))
    @dataclass(frozen=True)
    class N:
        level:int
        talents:T
        score_s_per_100:float
        policy:str="frost"
        source:str="fixture"
        details:dict|None=None
    pools={11:[N(11,T(frost=2),3600)],12:[N(12,T(frost=3),1800)]}
    out=build_frontier("mage",pools,E,E.SimConfig() if hasattr(E,"SimConfig") else type("C",(),{"owl_intensity":1.0,"gear_bonus_spell_power":0.0})(),start_level=11,end_level=12)
    row=out["levels"][1]["candidates"][0]
    assert row["mobs_per_hour"]==pytest.approx(200.0)
    assert row["steps"][1]["talent_added"]=="frost"
    assert row["cumulative_objective_s"]>row["steps"][1]["score_s_per_100"]


def test_spec_matrix_above_verified_cap_is_provisional_not_blocked():
    @dataclass
    class T:
        x:int=0
    class E:
        Talents=T
        VERIFIED_LEVEL_CAP=30
        @staticmethod
        def experimental_level_score(level,talents,profile):
            return {"profile":"x","gear":"normal","pull_size":1,"mobs_per_hour":200,"rotation":"hit","policy":"hit"}
        @staticmethod
        def marginal_stat_weights(level,talents,profile,baseline=None):
            return {"weights":{"strength":1.0}}
        @staticmethod
        def final_allocation(talents): return f"x={talents.x}"
    route={"steps":[{"level":60,"talent_ranks":{"x":1},"talent_family":"x"}]}
    out=build_matrix(E,route,class_name="paladin",route="x",target=60)
    assert out["status"]=="available"
    assert out["verification_status"]=="provisional_above_verified_cap"
    assert out["uses_unverified_levels"] is True
    assert out["unverified_from_level"]==31


def test_spec_matrix_reuses_fixed_talent_steps_without_talent_search():
    @dataclass
    class T:
        seal_of_command:int=0
    class E:
        Talents=T
        @staticmethod
        def experimental_level_score(level,talents,profile):
            return {"profile":"ret","gear":"2h","pull_size":1,"mobs_per_hour":200,"rotation":"hit","policy":"balanced",
                    "seconds_per_mob":18.0,"kill_seconds_per_mob":12.0,"recovery_seconds_per_mob":5.0,"travel_seconds_per_mob":1.0}
        @staticmethod
        def marginal_stat_weights(level,talents,profile,baseline=None):
            return {"stat_mix_guidance_rank":["strength"]}
        @staticmethod
        def final_allocation(talents):
            return f"soc={talents.seal_of_command}"
    route={"steps":[{"level":20,"talent_ranks":{"seal_of_command":1},"talent_family":"retribution"}]}
    out=build_matrix(E,route,class_name="paladin",route="retribution",target=20)
    assert out["status"]=="available" and len(out["rows"])==1
    assert out["rows"][0]["stat_weights"]["stat_mix_guidance_rank"]==["strength"]
    assert out["rows"][0]["seconds_per_mob"]==pytest.approx(18.0)
    assert out["rows"][0]["kill_seconds_per_mob"]==pytest.approx(12.0)
    assert out["rows"][0]["recovery_seconds_per_mob"]==pytest.approx(5.0)
    assert out["rows"][0]["travel_seconds_per_mob"]==pytest.approx(1.0)


def test_paladin_event_finalist_is_separate_from_fast_authority(monkeypatch):
    from src.rulesets.forever.classes.paladin import engine
    from src.rulesets.forever.classes.paladin import validation_report
    monkeypatch.setattr(validation_report,"validate_candidate",lambda level,t,row:{
        "event_adjusted_mobs_per_hour":row["event_mph"],"gear":row.get("gear"),
        "pull_size":row.get("pull_size"),"profile":"retribution","policy":"balanced",
        "aura":"devotion","mana_plan":"full",
        "event_combat_s":12.0,"event_recovery_s":3.0,"event_travel_s":2.0,"event_cycle_s":18.0,
    })
    candidates=[
        {"allocation":"fast","talent_ranks":{"divine_strength":1},"gear":"2h","pull_size":1,"combat_profile":"retribution","details":{"event_mph":190,"gear":"2h","pull_size":1,"policy":"balanced","aura":"devotion","mana_plan":"full"}},
        {"allocation":"event","talent_ranks":{"divine_strength":1},"gear":"shield","pull_size":2,"combat_profile":"retribution","details":{"event_mph":220,"gear":"shield","pull_size":2,"policy":"balanced","aura":"devotion","mana_plan":"full"}},
    ]
    out=engine.event_validate_candidates(15,candidates)
    assert candidates[0]["allocation"]=="fast"
    assert out["event_validated_best"]["allocation"]=="event"
    assert out["decision_change_kind"]=="playstyle"
    b=out["event_validated_best"]
    # Event-adjusted rows must not keep the smooth candidate's timing.  The
    # cooldown-floor remainder (18 - 12 - 2 = 4s/pack) is folded into recovery.
    assert b["seconds_per_mob"] == pytest.approx(9.0)
    assert b["kill_seconds_per_mob"] == pytest.approx(6.0)
    assert b["recovery_seconds_per_mob"] == pytest.approx(2.0)
    assert b["travel_seconds_per_mob"] == pytest.approx(1.0)


def test_fast_damage_cadence_cannot_end_between_damage_events():
    from src.rulesets.forever.classes.paladin.mechanics import _discrete_damage_kill_s
    cadence={"auto_first":3.0,"auto_period":3.0,"auto_damage":40.0}
    got=_discrete_damage_kill_s(100.0,7.5,1.0,cadence)
    assert got==pytest.approx(9.0)
    assert got>=7.5


def test_general_constraint_regret_supports_talent_tree_and_playstyle_conditions():
    frontier={"class":"paladin","levels":[{"level":20,"candidates":[
        _candidate(100.0,fury=1,mph=220,name="best"),
        {**_candidate(105.0,command=1,mph=210,name="ret"),"gear":"1h_shield_normal","pull_size":2},
    ]}]}
    out=analyze_constraint(frontier,20,{"talent_minimums":{"seal_of_command":1},"gear":"1h_shield_normal","pull_size":2})
    assert out["status"]=="available"
    assert out["regret_percent"]==pytest.approx(5.0)




def test_general_constraint_can_pin_the_talents_already_owned_at_an_earlier_level():
    best={**_candidate(100.0,fury=1,mph=220,name="best"),"level":30,"steps":[
        {"level":20,"talent_ranks":{"toughness":5,"precision":1},"allocation":"old"},
        {"level":30,"talent_ranks":{"toughness":5,"precision":3,"improved_seal_of_fury":1},"allocation":"best"},
    ]}
    continued={**_candidate(104.0,command=1,mph=210,name="continued"),"level":30,"steps":[
        {"level":20,"talent_ranks":{"toughness":5,"precision":2},"allocation":"mine"},
        {"level":30,"talent_ranks":{"toughness":5,"precision":2,"seal_of_command":1},"allocation":"continued"},
    ]}
    frontier={"class":"paladin","levels":[{"level":30,"candidates":[best,continued]}]}
    out=analyze_constraint(frontier,30,{"at_level":20,"at_level_talent_minimums":{"toughness":5,"precision":2}})
    assert out["status"]=="available"
    assert out["path"]["allocation"]=="continued"
    assert out["regret_percent"]==pytest.approx(4.0)


def test_at_level_talent_constraint_requires_at_level():
    with pytest.raises(ValueError):
        normalize_constraint({"at_level_talent_minimums":{"toughness":5}})

def test_general_constraint_reports_missing_corridor_instead_of_inventing_result():
    frontier={"class":"paladin","levels":[{"level":20,"candidates":[_candidate(100.0,fury=1)]}]}
    out=analyze_constraint(frontier,20,{"talent_minimums":{"seal_of_command":1}})
    assert out["status"]=="not_preserved_requires_constrained_rerun"
    assert "path" not in out
    assert len(out["rerun_commands"])==2
    assert "--beam-width 24" in out["rerun_commands"][0]
    assert "src.v2.constrained_routes" in out["rerun_commands"][1]


def test_rerun_commands_shell_quote_constraint_json():
    cmds=rerun_commands("mage",27,{"gear":"staff's choice"},start_level=10)
    assert "--end-level 27" in cmds[0]
    assert "constraint-json" in cmds[1]
    assert "staff" in cmds[1]


def test_general_constraint_rejects_unknown_or_empty_shapes():
    with pytest.raises(ValueError): normalize_constraint({})
    with pytest.raises(ValueError): normalize_constraint({"secret_guess":True})


def test_decision_dashboard_builds_one_canonical_route_row_contract(tmp_path):
    decision_root=tmp_path/'state/decisions/forever'; decision_root.mkdir(parents=True)
    endpoint={
        'schema_version':1,'ruleset':'forever','classes':{'paladin':{
            'targets':{'20':{'status':'available','target_level':20,'routes':{
                'unconstrained':{'status':'available','path':{'steps':[{
                    'level':20,
                    'allocation':'holy(0) / protection(0) / retribution(11)[deflection:5,benediction:1,conviction:4,seal_of_command:1]',
                    'talent_ranks':{'deflection':5,'benediction':1,'conviction':4,'seal_of_command':1},
                    'tree_points':{'holy':0,'protection':0,'retribution':11},
                    'talent_family':'retribution','combat_profile':'retribution','gear':'2h_normal','pull_size':2,
                    'score_s_per_100':1320.0,'mobs_per_hour':272.727,
                }]},'transitions':[]}
            }}}
        }}
    }
    matrix={
        'schema_version':1,'ruleset':'forever','classes':{'paladin':{'schema_version':2,'class':'paladin','matrices':{
            '20:unconstrained':{'status':'available','target_level':20,'route':'unconstrained','rows':[{
                'level':20,
                # deliberately contradictory display identity: endpoint path must win for talents
                'allocation':'holy(11)[divine_strength:5,healing_light:3,improved_holy_strike:2,spiritual_focus:1]',
                'talent_ranks':{'divine_strength':5},
                'combat_profile':'retribution','gear':'2h_normal','pull_size':2,'mobs_per_hour':273.4,
                'seconds_per_mob':13.17,'kill_seconds_per_mob':8.55,'recovery_seconds_per_mob':3.52,'travel_seconds_per_mob':1.10,
                'rotation':'Seal of Command up; Judgement on CD; Holy Strike on CD; melee weave',
                'stat_weights':{'stats':{'strength':{'seconds_saved_per_100_per_point':2.5},'intellect':{'seconds_saved_per_100_per_point':0.0}}},
                'gear_stats':{'slots':{
                    'feet':{'slot':'feet','name':'Crusader Boots','stamina':5,'spell_power':6},
                    'weapon':{'slot':'weapon','name':'Wolfsbane','weapon_dps':25.6,'weapon_speed':3.4},
                }}
            }]}
        }}}
    }
    (decision_root/'endpoint_paths.json').write_text(json.dumps(endpoint),encoding='utf-8')
    (decision_root/'spec_matrix.json').write_text(json.dumps(matrix),encoding='utf-8')
    (decision_root/'spec_regret.json').write_text(json.dumps({'classes':{}}),encoding='utf-8')
    (decision_root/'dual_spec.json').write_text(json.dumps({'classes':{}}),encoding='utf-8')

    payload=build_decision_payload(tmp_path,selected_level=20)
    row=payload['route_rows']['paladin']['20']['routes']['unconstrained']['rows'][0]
    assert row['allocation'].startswith('holy(0) / protection(0) / retribution(11)')
    assert row['talent_ranks']['seal_of_command']==1
    assert row['talent_trees']['retribution']['points']==11
    assert {x['name']:x['rank'] for x in row['talent_trees']['retribution']['talents']}['deflection']==5
    assert row['seconds_per_mob']==pytest.approx(13.17)
    assert row['recovery_seconds_per_mob']==pytest.approx(3.52)
    assert row['stat_weights']['stats']['intellect']['seconds_saved_per_100_per_point']==0.0
    assert row['gear_stats']['slots']['feet']['name']=='Crusader Boots'
    assert row['missing']=={}
    assert row['data_sources']==['endpoint_path','spec_matrix']


def test_decision_dashboard_derives_total_timing_but_explains_missing_detail(tmp_path):
    decision_root=tmp_path/'state/decisions/forever'; decision_root.mkdir(parents=True)
    endpoint={'classes':{'paladin':{'targets':{'20':{'status':'available','routes':{
        'unconstrained':{'status':'available','path':{'steps':[{
            'level':20,'allocation':'holy(0) / protection(0) / retribution(1)[seal_of_command:1]',
            'talent_ranks':{'seal_of_command':1},'tree_points':{'holy':0,'protection':0,'retribution':1},
            'score_s_per_100':1500.0,'mobs_per_hour':240.0,
        }]}}
    }}}}}}
    for name,obj in {
        'endpoint_paths.json':endpoint,
        'spec_matrix.json':{'classes':{}},'spec_regret.json':{'classes':{}},'dual_spec.json':{'classes':{}},
    }.items(): (decision_root/name).write_text(json.dumps(obj),encoding='utf-8')
    row=build_decision_payload(tmp_path)['route_rows']['paladin']['20']['routes']['unconstrained']['rows'][0]
    assert row['seconds_per_mob']==pytest.approx(15.0)
    assert 'stat_weights' in row['missing']
    assert 'gear' in row['missing']
    assert 'timing' not in row['missing']
