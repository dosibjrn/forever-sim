"""WF466 P1 contract: no JSON-only PASS and no silent source/optimizer omissions."""
from pathlib import Path
from types import SimpleNamespace as N
import sys
import json
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from wf_gate_p1_live import audit_inventory,run_live


def row(sid=100,name='Shared spell',lvl=10,rank=1):
    return dict(spell_id=sid,name=name,rank_hint=rank,level_hint=lvl,
                raw_listview_json='{}',source_url='https://source.example/spell')


def ir_with(*actions):
    return N(id='source-ir',actor=N(id='actor'),actions=tuple(actions),modes=(),resources=())


def action(sid=100,*,effects=(object(),),req=(),trace=True):
    return N(id=f'source_spell:{sid}',family_key='generic_family',owner_actor_id='actor',
             effects=effects,requirements=req,provenance=({'source_url':'https://x'},) if trace else (),
             metadata={})


def policy(action_id):
    return N(rules=(N(action_id=action_id),))


def check(rows,ir,*,scratch=True,exec_ok=True):
    def builder(ir,rules):return policy(rules[0][0])
    def candidates(ir,max_candidates):
        return [policy(a.id) for a in ir.actions] if scratch else []
    return audit_inventory(rows,ir,parser=lambda a:set(),
                           source_classifier=lambda row,raw:{'role':'ABILITY'},
                           policy_builder=builder,scratch_builder=candidates,
                           executor=lambda ir,a:{'status':'executed' if exec_ok else 'error',
                                                  'events':1 if exec_ok else 0,
                                                  'effect_observed':bool(exec_ok)},
                           effect_checker=lambda effect:'direct_damage')


def codes(result):return {p['code'] for p in result['problems']}


def test_legal_action_passes_for_any_class_key_independent_inventory():
    for sid in (100,200,300):
        result=check([row(sid=sid)],ir_with(action(sid)))
        assert result['status']=='PASS' and result['production_runtime_exercises']==1


def test_missing_gameir_reports_exact_source_ability():
    result=check([row(100),row(200,name='Root',lvl=20,rank=2)],ir_with(action(100)))
    assert result['status']=='FAIL' and 'MISSING_GAME_IR_ACTION' in codes(result)
    assert any('200:Root:rank=2' in (p['ability'] or '') for p in result['problems'])


def test_class_whitelist_or_missing_search_candidate_is_fail():
    result=check([row()],ir_with(action()),scratch=False)
    assert 'OPTIMIZER_OMITS_LEGAL_ACTION' in codes(result)


def test_unknown_executable_and_noop_never_certified():
    r=check([row()],ir_with(action()),exec_ok=False)
    assert r['status']=='FAIL' and 'COMBAT_ACTION_NOT_EXECUTED' in codes(r)
    r=check([row()],ir_with(action(effects=())))
    assert 'EMPTY_GAME_IR_EFFECT' in codes(r)


def test_source_level_and_conditional_checks():
    r=check([row(lvl=10)],ir_with(action(req=({'kind':'minimum_level','value':25},))))
    assert 'WRONG_MINIMUM_LEVEL' in codes(r)
    r=check([row(lvl=None)],ir_with(action()))
    assert 'UNRESOLVED_SOURCE_REQUIRED_LEVEL' in codes(r)


def test_missing_production_baseline_cannot_pass():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmp:
        p=Path(tmp)
        r=run_live(p,'druid',20)
        assert r['status']=='FAIL' and r['reasons']


def test_cli_production_uses_live_baseline_not_earlier_json_verdict():
    # The self-contained WF446 integration tree has real production imports.
    # Test the actual CLI contract; never assume a baseline is missing here.
    cmd=[sys.executable,str(ROOT/'tools'/'wf_gate.py'),'--class','druid',
         '--level','20','--gate','P1']
    r=subprocess.run(cmd,cwd=str(ROOT),capture_output=True,text=True)
    assert r.returncode in (0,1)
    data=json.loads(r.stdout)
    entry=data['results'][0]
    assert entry['source']=='live_production'
    assert data['status']==entry['status']
    assert entry['source_id'] and entry['engine_id']
    assert entry['problem_count']==len(entry['problems'])


def test_higher_level_spell_must_not_enter_level_20_gameir():
    def builder(ir,rules):return policy(rules[0][0])
    r=audit_inventory([row(100,lvl=20)],ir_with(action(100),action(300)),
        parser=lambda a:set(),
        source_classifier=lambda a,b:{'role':'ABILITY'},
        policy_builder=builder,
        scratch_builder=lambda i,max_candidates:[policy(a.id) for a in i.actions],
        executor=lambda i,a:{'status':'executed','events':1,'effect_observed':True},
        effect_checker=lambda e:'direct_damage',
        higher_level_rows=[row(300,lvl=30)])
    assert 'ILLEGAL_HIGH_LEVEL_ACTION_IN_GAME_IR' in codes(r)

def test_engraving_setup_not_implicitly_a_castable_spell():
    r=audit_inventory([row(100),row(200)],ir_with(action(100)),
        parser=lambda a:set(),
        source_classifier=lambda x,y:{'role':'SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP' if x['spell_id']==200 else 'ABILITY'},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy(a.id) for a in ir.actions],
        executor=lambda ir,a:{'status':'executed','events':1,'effect_observed':True},
        effect_checker=lambda e:'direct_damage')
    assert r['status']=='PASS' and len(r['excluded_setup_rows'])==1


def test_action_started_only_is_not_proof_of_effect():
    r=audit_inventory([row()],ir_with(action()),parser=lambda a:set(),
        source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy('source_spell:100')],
        executor=lambda ir,a:{'status':'executed','events':1,'effect_observed':False},
        effect_checker=lambda e:'direct_damage')
    assert r['status']=='FAIL' and 'COMBAT_ACTION_NOT_EXECUTED' in codes(r)


def test_conditional_action_with_recognised_requirement_is_not_p1_pass_without_effect():
    a=action(req=({'kind':'relative_position_is','value':'rear'},))
    r=audit_inventory([row()],ir_with(a),parser=lambda a:set(),
        source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy(a.id)],
        executor=lambda ir,a:{'status':'conditional','reason':"requires relative position 'rear'; have None"},
        effect_checker=lambda e:'direct_damage')
    assert r['status']=='FAIL' and len(r['conditional_actions'])==1
    assert r['production_runtime_exercises']==0
    assert 'CONDITIONAL_EFFECT_NOT_EXECUTED' in codes(r)
    assert any('requires relative position' in (p['detail'] or '')
               for p in r['problems'] if p['code']=='CONDITIONAL_EFFECT_NOT_EXECUTED')


def test_source_legal_conditional_with_observed_effect_can_pass():
    # The prerequisite does not waive effect execution, but a genuine
    # observed effect still passes the existing production probe contract.
    for sid in (100, 200):
        a=action(sid,req=({'kind':'relative_position_is','value':'rear'},))
        r=audit_inventory([row(sid=sid)],ir_with(a),parser=lambda a:set(),
            source_classifier=lambda r,raw:{'role':'ABILITY'},
            policy_builder=lambda ir,rules:policy(rules[0][0]),
            scratch_builder=lambda ir,max_candidates:[policy(a.id)],
            executor=lambda ir,a:{'status':'executed','effect_observed':True},
            effect_checker=lambda e:'direct_damage')
        assert r['status']=='PASS',r['problems']
        assert r['production_runtime_exercises']==1
        assert not r['conditional_actions']


def test_conditional_status_cannot_hide_missing_source_prerequisite():
    a=action()
    r=audit_inventory([row()],ir_with(a),parser=lambda a:set(),
        source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy(a.id)],
        executor=lambda ir,a:{'status':'conditional','reason':"requires relative position 'rear'; have None"},
        effect_checker=lambda e:'direct_damage')
    assert 'COMBAT_ACTION_NOT_EXECUTED' in codes(r)


def test_unsupported_effect_fails_even_for_legitimate_conditional():
    a=action(req=({'kind':'aura_present','aura_id':'proc','scope':'actor'},))
    r=audit_inventory([row()],ir_with(a),parser=lambda a:set(),
        source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy(a.id)],
        executor=lambda ir,a:{'status':'conditional','reason':'requires active aura proc'},
        effect_checker=lambda e:'unsupported')
    assert r['status']=='FAIL' and 'UNSUPPORTED_EFFECT_DISPATCH' in codes(r)


def test_unsupported_requirement_fails_even_if_executor_claims_execution():
    a=action(req=({'kind':'unimplemented_condition','value':1},))
    r=audit_inventory([row()],ir_with(a),parser=lambda a:set(),
        source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy(a.id)],
        executor=lambda ir,a:{'status':'executed','effect_observed':True},
        effect_checker=lambda e:'direct_damage')
    assert r['status']=='FAIL' and 'INVALID_OR_UNSUPPORTED_PREREQUISITE' in codes(r)


def test_unrelated_runtime_error_not_mislabeled_conditional():
    a=action(req=({'kind':'aura_present','aura_id':'proc','scope':'actor'},))
    r=audit_inventory([row()],ir_with(a),parser=lambda a:set(),
        source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy(a.id)],
        executor=lambda ir,a:{'status':'conditional','reason':'unsupported runtime effect'},
        effect_checker=lambda e:'direct_damage')
    assert r['status']=='FAIL' and 'COMBAT_ACTION_NOT_EXECUTED' in codes(r)


def test_condition_referring_to_nonexistent_mode_cannot_pass():
    a=action(req=({'kind':'mode_is','value':'imaginary_form'},))
    r=audit_inventory([row()],ir_with(a),parser=lambda a:set(),
        source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy(a.id)],
        executor=lambda ir,a:{'status':'conditional','reason':'requires mode imaginary_form'},
        effect_checker=lambda e:'mode_change')
    assert r['status']=='FAIL' and 'UNKNOWN_PREREQUISITE_MODE' in codes(r)


def test_source_level_zero_nonaction_rank_not_mistaken_for_castable_ability():
    # L0 includes passive rank records in the source spell index.  Report the
    # exclusion; do not require a fictitious combat action for every passive.
    rows=[row(100,lvl=10),row(16836,name='Improved Thorns',lvl=0,rank=1)]
    r=check(rows,ir_with(action(100)))
    assert r['status']=='PASS'
    assert r['checked_source_abilities']==1
    assert r['excluded_nonaction_or_inactive_rows']==[
        {'source_spell_id':16836, 'role':'ZERO_LEVEL_NONACTION_RANK',
         'reason':'source level zero, no actionable GameIR mapping'}]


def test_source_level_zero_nonaction_must_not_hide_a_compiled_action():
    rows=[row(100,lvl=10),row(16836,name='Improved Thorns',lvl=0,rank=1)]
    r=check(rows,ir_with(action(100),action(16836)))
    assert r['status']=='PASS' and r['checked_source_abilities']==2


def test_source_unverified_rune_inactive_without_erasing_ordinary_missing_ability():
    r=audit_inventory([row(100),row(200),row(300)],ir_with(action(100)),
        parser=lambda a:set(),source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy(a.id) for a in ir.actions],
        executor=lambda ir,a:{'status':'executed','effect_observed':True},
        source_inactive_ids={200:'rune_grant_unverified_default_off'},
        effect_checker=lambda e:'direct_damage')
    assert r['status']=='FAIL'
    assert 'MISSING_GAME_IR_ACTION' in codes(r)
    assert any('300:' in (p['ability'] or '') for p in r['problems']
               if p['code']=='MISSING_GAME_IR_ACTION')
    assert not any('200:' in (p['ability'] or '') for p in r['problems'])
    assert any(x['source_spell_id']==200 for x in r['excluded_nonaction_or_inactive_rows'])


def test_inactive_rune_leaking_into_legal_actions_fails():
    r=audit_inventory([row(100),row(200)],ir_with(action(100),action(200)),
        parser=lambda a:set(),source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy(a.id) for a in ir.actions],
        executor=lambda ir,a:{'status':'executed','effect_observed':True},
        source_inactive_ids={200:'rune_grant_unverified_default_off'},
        effect_checker=lambda e:'direct_damage')
    assert 'INACTIVE_SOURCE_ACTION_ENTERED_GAME_IR' in codes(r)


def test_an_exclusion_requires_actual_source_scope_not_merely_a_missing_action():
    r=check([row(100),row(200)],ir_with(action(100)))
    assert 'MISSING_GAME_IR_ACTION' in codes(r)
    assert r['status']=='FAIL'


def test_zero_level_without_rank_proof_is_unresolved_not_silently_discarded():
    r=check([row(100),row(250,name='Possible conditional spell',lvl=0,rank=None)],
            ir_with(action(100)))
    assert 'MISSING_GAME_IR_ACTION' in codes(r)
    assert any('250:' in (p['ability'] or '') for p in r['problems'])


def test_real_p1_probe_rejects_bookkeeping_only_and_accepts_effect_event(monkeypatch):
    """Probe contract, not a mocked acceptance JSON: test the actual probe path."""
    from wf_gate_p1_live import _runtime_exercise
    import types
    events_holder={'events':[]}
    class Actor:
        def __init__(self):
            self.metadata={};self.current_mode_id=None
            self.resource_capacity={};self.resources={}
        @classmethod
        def from_ir(cls,*_):return cls()
        def transition_mode(self,mode):self.current_mode_id=mode
    class Target:
        @classmethod
        def with_health(cls,*_):return N(metadata={})
    class Runtime:
        def __init__(self,actor,target):pass
        def schedule_action(self,action):pass
        def run_until_idle(self):pass
        def result(self):return N(events=events_holder['events'])
    runtime_mod=types.ModuleType('src.game.runtime')
    runtime_mod.ActorState=Actor;runtime_mod.TargetState=Target
    runtime_mod.CombatRuntime=Runtime
    simulator_mod=types.ModuleType('src.game.runtime.simulator')
    simulator_mod.action_eligibility=lambda **kw:N(eligible=True,reason=None)
    monkeypatch.setitem(sys.modules,'src.game.runtime',runtime_mod)
    monkeypatch.setitem(sys.modules,'src.game.runtime.simulator',simulator_mod)
    test_ir=N(actor=N(id='actor'),resources=(),modes=())
    a=action()
    events_holder['events']=[N(kind=k,action_id=a.id) for k in ('ActionStarted','ActionCompleted')]
    result=_runtime_exercise(test_ir,a,20)
    assert result['status']=='invalid' and result['reason']=='ACTION_COMPLETED_WITHOUT_OBSERVABLE_EFFECT'
    events_holder['events'].append(N(kind='ResourceChanged',action_id=a.id,
        payload={'before':100.0,'after':100.0}))
    assert _runtime_exercise(test_ir,a,20)['status']=='invalid'
    events_holder['events'].append(N(kind='Damage',action_id=a.id,payload={'amount':10.0}))
    assert _runtime_exercise(test_ir,a,20)['status']=='executed'


def test_probe_tries_next_legal_mode_if_first_raises(monkeypatch):
    from wf_gate_p1_live import _runtime_exercise
    import types
    class Actor:
        def __init__(self):
            self.metadata={};self.current_mode_id=None
            self.resource_capacity={};self.resources={}
        @classmethod
        def from_ir(cls,*_):return cls()
        def transition_mode(self,mode):
            if mode == 'broken':raise ValueError('Cannot enter temporary test mode')
            self.current_mode_id=mode
    class Target:
        @classmethod
        def with_health(cls,*_):return N(metadata={})
    class Runtime:
        def __init__(self,actor,target):pass
        def schedule_action(self,action):self.action=action
        def run_until_idle(self):pass
        def result(self):return N(events=[N(kind=k,action_id=self.action.id,
                 payload={'amount':10.0} if k=='Damage' else {})
                 for k in ('ActionStarted','Damage','ActionCompleted')])
    runtime_mod=types.ModuleType('src.game.runtime')
    runtime_mod.ActorState=Actor;runtime_mod.TargetState=Target;runtime_mod.CombatRuntime=Runtime
    simulator_mod=types.ModuleType('src.game.runtime.simulator')
    simulator_mod.action_eligibility=lambda **kw:N(eligible=True,reason=None)
    monkeypatch.setitem(sys.modules,'src.game.runtime',runtime_mod)
    monkeypatch.setitem(sys.modules,'src.game.runtime.simulator',simulator_mod)
    test_ir=N(actor=N(id='actor'),resources=(),modes=(
       N(id='broken',enabled_action_ids=None),N(id='working',enabled_action_ids=None)))
    assert _runtime_exercise(test_ir,action(),20)['status']=='executed'


def test_probe_builds_generic_positive_relative_position_for_execution(monkeypatch):
    from wf_gate_p1_live import _runtime_exercise
    import types
    class Actor:
        def __init__(self):
            self.metadata={};self.current_mode_id=None
            self.resource_capacity={};self.resources={}
        @classmethod
        def from_ir(cls,*_):return cls()
        def transition_mode(self,mode):self.current_mode_id=mode
    class Target:
        @classmethod
        def with_health(cls,*_):return N(metadata={})
    class Runtime:
        def __init__(self,actor,target):
            assert target.metadata['attacker_relative_position']=='rear'
        def schedule_action(self,action):self.a=action
        def run_until_idle(self):pass
        def result(self):return N(events=[N(kind=k,action_id=self.a.id,
                payload={'amount':10.0} if k=='Damage' else {})
                for k in ('ActionStarted','Damage','ActionCompleted')])
    runtime_mod=types.ModuleType('src.game.runtime')
    runtime_mod.ActorState=Actor;runtime_mod.TargetState=Target;runtime_mod.CombatRuntime=Runtime
    simulator_mod=types.ModuleType('src.game.runtime.simulator')
    simulator_mod.action_eligibility=lambda action,actor,target:N(
        eligible=target.metadata.get('attacker_relative_position')=='rear',
        reason='requires relative position rear')
    monkeypatch.setitem(sys.modules,'src.game.runtime',runtime_mod)
    monkeypatch.setitem(sys.modules,'src.game.runtime.simulator',simulator_mod)
    a=action(req=({'kind':'relative_position_is','value':'rear'},))
    assert _runtime_exercise(N(actor=N(id='actor'),resources=(),modes=()),a,20)['status']=='executed'


def test_p1_false_positive_background_regeneration_must_fail(monkeypatch):
    from wf_gate_p1_live import _runtime_exercise
    import types
    class Actor:
        def __init__(self):
            self.metadata={};self.current_mode_id=None;self.resource_capacity={};self.resources={}
        @classmethod
        def from_ir(cls,*args):return cls()
    class Target:
        @classmethod
        def with_health(cls,*args):return N(metadata={})
    events=['ActionStarted','ResourceRegenerated','ActionCompleted']
    class Runtime:
        def __init__(self,actor,target):pass
        def schedule_action(self,a):self.a=a
        def run_until_idle(self):pass
        def result(self):return N(events=[N(kind=k,action_id=self.a.id) for k in events])
    pkg=types.ModuleType('src.game.runtime');pkg.ActorState=Actor;pkg.TargetState=Target;pkg.CombatRuntime=Runtime
    sim=types.ModuleType('src.game.runtime.simulator')
    sim.action_eligibility=lambda **kw:N(eligible=True,reason=None)
    monkeypatch.setitem(sys.modules,'src.game.runtime',pkg)
    monkeypatch.setitem(sys.modules,'src.game.runtime.simulator',sim)
    ir=N(actor=N(id='actor'),resources=(),modes=())
    assert _runtime_exercise(ir,action(),20)['status']=='invalid'
    events[1]='AuraApply'  # real sourced effect, not timing/bookkeeping
    assert _runtime_exercise(ir,action(),20)['status']=='executed'


def test_matching_conditional_requirement_only():
    a=action(req=({'kind':'resource_min','resource_id':'energy','value':35},))
    def run(reason):
        return audit_inventory([row()],N(**{**ir_with(a).__dict__, 'resources':(N(id='energy'),)}),parser=lambda a:set(),
           source_classifier=lambda r,raw:{'role':'ABILITY'},
           policy_builder=lambda ir,rules:policy(rules[0][0]),
           scratch_builder=lambda ir,max_candidates:[policy(a.id)],
           executor=lambda ir,a:{'status':'conditional','reason':reason},
           effect_checker=lambda e:'direct_damage')
    assert run('requires mode cat')['status']=='FAIL'
    assert run('requires 35 rage; have 0')['status']=='FAIL'
    recognized=run('requires 35 energy; have 0')
    assert recognized['status']=='FAIL'
    assert 'CONDITIONAL_EFFECT_NOT_EXECUTED' in codes(recognized)
    assert recognized['conditional_actions'][0]['reason']=='requires 35 energy; have 0'


def test_source_rank_cannot_be_cast_before_own_minimum_level():
    a=action(req=({'kind':'minimum_level','value':10},))
    r=check([row(lvl=20)],ir_with(a))
    assert 'ACTION_AVAILABLE_BEFORE_SOURCE_LEVEL' in codes(r)
    assert r['status']=='FAIL'


def test_malformed_requirement_gets_named_fail_instead_of_crashing():
    a=action(req=('broken_requirement',))
    r=check([row()],ir_with(a))
    assert 'INVALID_OR_UNSUPPORTED_PREREQUISITE' in codes(r)
    assert r['status']=='FAIL'


def test_probe_checks_next_source_legal_mode_after_empty_completion(monkeypatch):
    from wf_gate_p1_live import _runtime_exercise
    import types
    class Actor:
        def __init__(self):
            self.metadata={};self.current_mode_id=None;self.resource_capacity={};self.resources={}
        @classmethod
        def from_ir(cls,*args):return cls()
        def transition_mode(self,m):self.current_mode_id=m
    class Target:
        @classmethod
        def with_health(cls,*args):return N(metadata={})
    class Runtime:
        def __init__(self,actor,target):self.mode=actor.current_mode_id
        def schedule_action(self,a):self.a=a
        def run_until_idle(self):pass
        def result(self):
            events=['ActionStarted','ActionCompleted']
            if self.mode=='effective':events.append('ModeChanged')
            return N(events=[N(kind=k,action_id=self.a.id) for k in events])
    pkg=types.ModuleType('src.game.runtime');pkg.ActorState=Actor;pkg.TargetState=Target;pkg.CombatRuntime=Runtime
    sim=types.ModuleType('src.game.runtime.simulator')
    sim.action_eligibility=lambda **kw:N(eligible=True,reason=None)
    monkeypatch.setitem(sys.modules,'src.game.runtime',pkg)
    monkeypatch.setitem(sys.modules,'src.game.runtime.simulator',sim)
    ir=N(actor=N(id='actor'),resources=(),modes=(N(id='neutral',enabled_action_ids=None),N(id='effective',enabled_action_ids=None)))
    r=_runtime_exercise(ir,action(),20)
    assert r['status']=='executed' and r['mode']=='effective'


def test_p1_zero_delta_events_cannot_certify_effect_execution():
    """Real CombatRuntime emits resource receipts even when capped at full."""
    from wf_gate_p1_live import _p1_effect_observed
    assert not _p1_effect_observed(N(kind='ResourceChange',
        payload={'before':100.,'after':100.}))
    assert not _p1_effect_observed(N(kind='ResourceChanged',
        payload={'before':100.,'after':100.}))
    assert not _p1_effect_observed(N(kind='ResourceEventGain',
        payload={'requested_gain':25.,'gained':0.,'capped':True}))
    assert not _p1_effect_observed(N(kind='Damage',payload={'amount':0.}))
    assert not _p1_effect_observed(N(kind='Heal',payload={'amount':0.}))
    assert _p1_effect_observed(N(kind='ResourceChange',
        payload={'before':100.,'after':110.}))
    assert _p1_effect_observed(N(kind='ResourceChanged',
        payload={'before':100.,'after':110.}))
    assert _p1_effect_observed(N(kind='ResourceEventGain',
        payload={'requested_gain':25.,'gained':10.,'capped':True}))
    assert _p1_effect_observed(N(kind='Damage',payload={'amount':10.}))
    assert _p1_effect_observed(N(kind='Heal',payload={'amount':10.}))


def test_p1_missing_or_nonfinite_effect_payload_fails_closed():
    from wf_gate_p1_live import _p1_effect_observed
    for kind in ('ResourceChange','ResourceChanged','ResourceEventGain','Damage','Heal'):
        assert not _p1_effect_observed(N(kind=kind,payload={}))
    assert not _p1_effect_observed(N(kind='Damage',payload={'amount':float('nan')}))
    assert not _p1_effect_observed(N(kind='ResourceChange',
        payload={'before':0.,'after':float('inf')}))
