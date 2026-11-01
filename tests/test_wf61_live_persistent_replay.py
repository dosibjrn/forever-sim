"""Contract-only negative controls for the WF61 live gsim replay tool.

These synthetic rows test rejection only; they are NOT simulated kills.
The Actions workflow runs the separate actual source-backed 1/2/100 replay.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools.wf61_live_persistent_replay import load_source_stage, validate_real_replay


def _contract_only(n=2):
    rows=[]
    for i in range(n):
        start=float(i*10)
        rows.append({'mob':i+1,'target_id':f'source_mob_{i+1}',
                     'pull_started_s':start,'kill_finished_s':start+4,
                     'recovery_s':6.,'recovery_finished_s':start+10,
                     'combat_s':4.,'actions':{'source_spell':1},
                     'long_cooldown_timer_ready_at_pull':{},
                     'long_cooldowns_used':{},
                     'long_cooldowns_not_ready_at_kill':{},
                     'health_mana_energy_before':{'health':100., 'mana':50., 'energy':10.},
                     'health_mana_energy_at_kill':{'health':80., 'mana':40., 'energy':10.},
                     'health_mana_energy_after_recovery':{'health':100., 'mana':50., 'energy':10.}})
    return {'status':'COMPLETE','count':n,'continuous_actor_state':True,
            'source_only':True,'spatial_mode':'2d_sequential_not_simultaneous_pack',
            'events':n,'source_action_counts':{'source_spell':n},
            'long_cooldown_source_actions_s':{},
            'settle_final_recovery':True,
            'final_resources':{'health':100., 'mana':50., 'energy':10.},
            'total_s':10.*n,'mean_s_per_mob':10.,'combat_s':4.*n,
            'recovery_s':6.*n,'maintenance_s':0.,'spaced_travel_s':0.,'pull_trace':rows,
            'pull_trace_audit':{'status':'GSIM_PERSISTENT_TRACE_INVARIANTS_ONLY',
                                'distinct_targets':n,
                                'native_world_action_ack_verified':False}}


def test_valid_contract_rows_are_not_a_native_certificate():
    assert validate_real_replay(_contract_only(),2)['native_world_action_ack_verified'] is False


@pytest.mark.parametrize('mutation',[
    lambda r:r.update(status='BLOCKED_COMBAT'),
    lambda r:r.update(count=1),
    lambda r:r.update(continuous_actor_state=False),
    lambda r:r.update(source_only=False),
    lambda r:r.update(events=0),
    lambda r:r.update(source_action_counts={}),
    lambda r:r.update(mean_s_per_mob=float('nan')),
    lambda r:r.update(recovery_s=0.),
    lambda r:r['pull_trace_audit'].update(native_world_action_ack_verified=True),
    lambda r:r['pull_trace_audit'].update(distinct_targets=1),
    lambda r:r['pull_trace'][1].update(target_id='source_mob_1'),
    lambda r:r['pull_trace'][1].update(pull_started_s=9.),
    lambda r:r['pull_trace'][1].update(actions={}),
    lambda r:r['pull_trace'][0].update(recovery_finished_s=5.),
])
def test_fabricated_or_incomplete_replay_cannot_be_reported_complete(mutation):
    result=deepcopy(_contract_only());mutation(result)
    with pytest.raises(ValueError,match='WF61_'):
        validate_real_replay(result,2)


def test_unsettled_final_recovery_cannot_pass_as_paid_100_mob_objective():
    """A valid quest-horizon clock is not a fully paid leveling objective."""
    result = deepcopy(_contract_only())
    last = result['pull_trace'][-1]
    last['recovery_s'] = 0.
    last['recovery_finished_s'] = last['kill_finished_s']
    result.update(settle_final_recovery=False, recovery_s=6.,
                  total_s=14., mean_s_per_mob=7.)
    # All existing combat, recovery, actor-clock and aggregate sums agree.
    with pytest.raises(ValueError, match='WF61_FINAL_RECOVERY_NOT_SETTLED'):
        validate_real_replay(result, 2)


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(settle_final_recovery=False),
    lambda r: r.pop('settle_final_recovery'),
])
def test_missing_or_false_final_recovery_contract_is_rejected(mutation):
    result = deepcopy(_contract_only())
    mutation(result)
    with pytest.raises(ValueError, match='WF61_FINAL_RECOVERY_NOT_SETTLED'):
        validate_real_replay(result, 2)


@pytest.mark.parametrize('fail_at', (1, 100))
def test_runtime_exception_preserves_prior_source_horizons(monkeypatch, fail_at):
    """Unit-only failure path: fake evaluator outputs are NEVER combat evidence."""
    import sys
    from types import ModuleType, SimpleNamespace
    from tools import wf61_live_persistent_replay as replay

    actor = SimpleNamespace(id='unit_actor')
    health = SimpleNamespace(id='health', owner_actor_id='unit_actor',
                             scope='actor', initial_amount=1.)
    candidate = SimpleNamespace(ir=SimpleNamespace(actor=actor, resources=(health,)))
    fake = ModuleType('src.v2.source_persistent_joint_finalists')
    fake.prepare_candidate = lambda **kwargs: candidate

    def evaluate(candidate, *, mobs, **kwargs):
        if mobs == fail_at:
            raise RuntimeError('UNIT_ONLY_SOURCE_EXECUTION_ERROR')
        return {'status': 'UNIT_STUB_NOT_COMBAT', 'requested_mobs': mobs}

    fake.evaluate_persistent_candidate = evaluate
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    monkeypatch.setattr(replay, 'load_source_stage',
                        lambda path: ({'allocation': {}, 'gear_policy_result': {}},
                                      'unit-only-stage-sha'))
    monkeypatch.setattr(replay, 'validate_real_replay',
                        lambda actual, count, **kwargs: {'status': 'UNIT_ONLY'})

    report = replay.execute_source_replays(
        class_key='druid', level=30, stage_path=Path('unit-only.json'),
        max_wall_s=1., source_identity={'unit_only': True})
    assert report['status'] == 'EXECUTION_ERROR'
    assert report['checkpoint_certified'] is False
    assert report['source_stage_sha256'] == 'unit-only-stage-sha'
    assert report['source_identity'] == {'unit_only': True}
    assert [r['requested_mobs'] for r in report['runs']] == [
        n for n in (1, 2, 100) if n <= fail_at]
    assert report['runs'][-1]['execution_error'] == {
        'status': 'EXECUTION_ERROR', 'error_type': 'RuntimeError',
        'reason': 'UNIT_ONLY_SOURCE_EXECUTION_ERROR'}
    assert all(r['actual_gsim_result']['status'] == 'UNIT_STUB_NOT_COMBAT'
               for r in report['runs'][:-1])


def test_source_stage_loader_fingerprints_exact_bytes(tmp_path):
    source=tmp_path/'source.json'
    source.write_text(json.dumps({'winner':{'allocation':{},'gear_policy_result':{'winner':{}}}}))
    stage,sha=load_source_stage(source)
    assert stage['allocation']=={}
    assert len(sha)==64
    source.write_text(source.read_text()+'\n')
    assert load_source_stage(source)[1]!=sha


def test_reject_non_stage_json(tmp_path):
    source=tmp_path/'bad.json'
    source.write_text('{"winner":{"score":123}}')
    with pytest.raises(ValueError,match='WF61_INVALID_SOURCE_STAGE'):
        load_source_stage(source)


@pytest.mark.parametrize('mutation', [
    lambda r: r['source_action_counts'].update(source_spell=3),
    lambda r: r['source_action_counts'].update(unseen_spell=1),
    lambda r: r['source_action_counts'].update(source_spell=True),
    lambda r: r['pull_trace'][1].update(actions={'different_spell': 1}),
    lambda r: r.update(total_s=30., mean_s_per_mob=15.),
    lambda r: r.update(maintenance_s=-1.),
])
def test_source_action_and_clock_aggregate_mismatch_rejected(mutation):
    """Actual per-pull source actions and paid actor clock must agree with totals."""
    result = deepcopy(_contract_only())
    mutation(result)
    with pytest.raises(ValueError, match='WF61_'):
        validate_real_replay(result, 2)



def test_reject_unpaid_or_fabricated_actor_clock_gaps():
    """The trace clock must equal the paid objective, not merely be monotonic."""
    # Previously accepted: last actor timestamp exceeds the reported objective.
    after_end = deepcopy(_contract_only())
    after_end['pull_trace'][-1]['recovery_finished_s'] += 1.
    with pytest.raises(ValueError, match='WF61_'):
        validate_real_replay(after_end, 2)

    # Previously accepted: fictitious maintenance cost with no actor-clock gap.
    phantom_upkeep = deepcopy(_contract_only())
    phantom_upkeep.update(maintenance_s=1., total_s=21., mean_s_per_mob=10.5)
    with pytest.raises(ValueError, match='WF61_'):
        validate_real_replay(phantom_upkeep, 2)

    # Previously accepted: a recovery timestamp includes unpaid extra time.
    hidden_recovery = deepcopy(_contract_only())
    hidden_recovery['pull_trace'][0]['recovery_finished_s'] = 11.
    hidden_recovery['pull_trace'][1].update(
        pull_started_s=11., kill_finished_s=15., recovery_finished_s=21.)
    hidden_recovery.update(maintenance_s=1., total_s=21., mean_s_per_mob=10.5)
    with pytest.raises(ValueError, match='WF61_'):
        validate_real_replay(hidden_recovery, 2)


def test_accept_actor_clock_gap_paid_as_maintenance_or_travel():
    """A real inter-pull delay is allowed when it is included in paid time."""
    for field in ('maintenance_s', 'spaced_travel_s'):
        paid = deepcopy(_contract_only())
        paid['pull_trace'][1].update(
            pull_started_s=11., kill_finished_s=15., recovery_finished_s=21.)
        paid.update(total_s=21., mean_s_per_mob=10.5)
        paid[field] = 1.
        assert validate_real_replay(paid, 2)['actual_distinct_targets'] == 2


@pytest.mark.parametrize('mutation', [
    lambda r: r['pull_trace'][0]['health_mana_energy_at_kill'].update(health=0.),
    lambda r: r['pull_trace'][-1]['health_mana_energy_after_recovery'].update(health=-1.),
    lambda r: r.update(final_resources={'health':0.}),
    lambda r: r.update(final_resources={'health':99.}),
    lambda r: r['pull_trace'][0].pop('health_mana_energy_at_kill'),
])
def test_reject_dead_or_inconsistent_actor_resource_evidence(mutation):
    """COMPLETE cannot hide dead actor or a fabricated final resource snapshot."""
    result = deepcopy(_contract_only())
    mutation(result)
    with pytest.raises(ValueError, match='WF61_'):
        validate_real_replay(result, 2)


@pytest.mark.parametrize('mutation', [
    lambda r: r['pull_trace'][0]['health_mana_energy_at_kill'].update(mana=-1.),
    lambda r: r['pull_trace'][1]['health_mana_energy_after_recovery'].update(energy=float('nan')),
    lambda r: r['pull_trace'][0]['health_mana_energy_at_kill'].pop('mana'),
    lambda r: r['pull_trace'][0]['health_mana_energy_after_recovery'].pop('energy'),
    lambda r: r['final_resources'].update(mana=49.),
    lambda r: r['final_resources'].update(energy=11.),
    lambda r: r['final_resources'].pop('mana'),
])
def test_reject_corrupt_actor_mana_energy_evidence(mutation):
    """A COMPLETE trace cannot silently invent or lose retained resources."""
    result = deepcopy(_contract_only())
    mutation(result)
    with pytest.raises(ValueError, match='WF61_'):
        validate_real_replay(result, 2)


def test_zero_mana_or_energy_is_valid_if_actor_survives():
    result = deepcopy(_contract_only())
    result['pull_trace'][0]['health_mana_energy_at_kill'].update(mana=0., energy=0.)
    assert validate_real_replay(result, 2)['actual_distinct_targets'] == 2


@pytest.mark.parametrize('channel', ('health', 'mana', 'energy'))
def test_reject_resource_teleport_between_adjacent_pulls(channel):
    """No paid time gap means retained actor resources cannot teleport."""
    result = deepcopy(_contract_only())
    result['pull_trace'][1]['health_mana_energy_before'][channel] += 1.
    with pytest.raises(ValueError, match='WF61_ZERO_GAP_RESOURCE_DISCONTINUITY'):
        validate_real_replay(result, 2)


@pytest.mark.parametrize('channel', ('health', 'mana', 'energy'))
def test_reject_missing_pre_pull_resource_channel(channel):
    result = deepcopy(_contract_only())
    result['pull_trace'][0]['health_mana_energy_before'].pop(channel)
    with pytest.raises(ValueError, match='WF61_'):
        validate_real_replay(result, 2)


def test_allow_resource_change_during_paid_inter_pull_gap():
    """Source upkeep/periodic ticks can change resources while time advances."""
    result = deepcopy(_contract_only())
    result['pull_trace'][1].update(
        pull_started_s=11., kill_finished_s=15., recovery_finished_s=21.)
    result['pull_trace'][1]['health_mana_energy_before']['mana'] = 40.
    result.update(maintenance_s=1., total_s=21., mean_s_per_mob=10.5)
    assert validate_real_replay(result, 2)['actual_distinct_targets'] == 2



@pytest.mark.parametrize('present', [
    frozenset(('health', 'mana')),
    frozenset(('health',)),
])
def test_source_absent_channels_are_explicit_none_not_fabricated_zero(present):
    """Mage/other actors need not invent resources absent from source GameIR."""
    result = deepcopy(_contract_only())
    for row in result['pull_trace']:
        for field in ('health_mana_energy_before',
                      'health_mana_energy_at_kill',
                      'health_mana_energy_after_recovery'):
            for channel in ('health', 'mana', 'energy'):
                if channel not in present:
                    row[field][channel] = None
    for channel in ('health', 'mana', 'energy'):
        if channel not in present:
            result['final_resources'][channel] = None
    assert validate_real_replay(
        result, 2, expected_resource_channels=present
    )['actual_distinct_targets'] == 2
    # Without explicit source identity, missing resource data cannot pass.
    with pytest.raises(ValueError, match='WF61_'):
        validate_real_replay(result, 2)
    # Even an absent resource must have an explicit trace key (not omission).
    result['pull_trace'][0]['health_mana_energy_before'].pop('energy')
    with pytest.raises(ValueError, match='WF61_ACTOR_RESOURCE_EVIDENCE_MISSING'):
        validate_real_replay(result, 2, expected_resource_channels=present)


def test_source_resource_presence_must_match_every_snapshot():
    result = deepcopy(_contract_only())
    present = frozenset(('health', 'mana'))
    for row in result['pull_trace']:
        for field in ('health_mana_energy_before',
                      'health_mana_energy_at_kill',
                      'health_mana_energy_after_recovery'):
            row[field]['energy'] = None
    result['final_resources']['energy'] = None
    # An unexplained numeric channel cannot appear when source IR lacks it.
    result['pull_trace'][1]['health_mana_energy_at_kill']['energy'] = 10.
    with pytest.raises(ValueError, match='WF61_UNEXPECTED_ACTOR_RESOURCE'):
        validate_real_replay(result, 2, expected_resource_channels=present)


def test_source_defined_channel_cannot_be_null_and_health_is_required():
    result = deepcopy(_contract_only())
    # This two-channel source actor has no energy. Keep the rest of the
    # evidence consistent so the intentionally null mana is the first error.
    for row in result['pull_trace']:
        for field in ('health_mana_energy_before',
                      'health_mana_energy_at_kill',
                      'health_mana_energy_after_recovery'):
            row[field]['energy'] = None
    result['final_resources']['energy'] = None
    result['pull_trace'][0]['health_mana_energy_before']['mana'] = None
    with pytest.raises(ValueError, match='WF61_INVALID_NUMBER'):
        validate_real_replay(
            result, 2, expected_resource_channels=frozenset(('health', 'mana')))
    with pytest.raises(ValueError, match='WF61_INVALID_SOURCE_RESOURCE_CHANNEL_SET'):
        validate_real_replay(result, 2, expected_resource_channels=frozenset(('mana',)))


@pytest.mark.parametrize('mutation', [
    lambda r: r.pop('long_cooldown_source_actions_s'),
    lambda r: r['pull_trace'][0].pop('long_cooldown_timer_ready_at_pull'),
    lambda r: r['pull_trace'][0].pop('long_cooldowns_used'),
    lambda r: r['pull_trace'][0].pop('long_cooldowns_not_ready_at_kill'),
    lambda r: r['pull_trace'][0].update(long_cooldown_timer_ready_at_pull={'unknown':True}),
    lambda r: r['pull_trace'][0].update(long_cooldown_timer_ready_at_pull={'source_spell':1}),
    lambda r: r['pull_trace'][0].update(long_cooldowns_used={'unknown':1}),
    lambda r: r['pull_trace'][0].update(long_cooldowns_used={'source_spell':True}),
    lambda r: r['pull_trace'][0].update(long_cooldowns_used={'source_spell':2}),
    lambda r: r['pull_trace'][0].update(long_cooldowns_not_ready_at_kill={'unknown':30.}),
    lambda r: r['pull_trace'][0].update(long_cooldowns_not_ready_at_kill={'source_spell':float('nan')}),
    lambda r: r['pull_trace'][0].update(long_cooldowns_not_ready_at_kill={'source_spell':-1.}),
    lambda r: r['long_cooldown_source_actions_s'].update(source_spell=float('inf')),
    lambda r: r['long_cooldown_source_actions_s'].update(source_spell=True),
])
def test_reject_corrupt_source_long_cooldown_trace(mutation):
    """The actual producer reports source cooldown identity and per-pull state."""
    result = _contract_with_used_long_cooldown()
    mutation(result)
    with pytest.raises(ValueError, match='WF61_'):
        validate_real_replay(result, 2)


def test_accept_source_declared_idle_long_cooldown():
    """An unused long action is still a valid source cooldown to track."""
    result = deepcopy(_contract_only())
    result['long_cooldown_source_actions_s'] = {'unused_source_spell':90.}
    for row in result['pull_trace']:
        row['long_cooldown_timer_ready_at_pull'] = {'unused_source_spell':True}
    assert validate_real_replay(result, 2)['actual_distinct_targets'] == 2


def _contract_with_used_long_cooldown():
    """Synthetic bookkeeping fixture, not an executed source combat trace."""
    result = _contract_only()
    result['long_cooldown_source_actions_s'] = {'source_spell': 60.}
    result['pull_trace'][0]['long_cooldown_timer_ready_at_pull'] = {'source_spell': True}
    result['pull_trace'][0]['long_cooldowns_used'] = {'source_spell': 1}
    result['pull_trace'][0]['long_cooldowns_not_ready_at_kill'] = {'source_spell': 56.}
    result['pull_trace'][1]['actions'] = {'filler_spell': 1}
    result['pull_trace'][1]['long_cooldown_timer_ready_at_pull'] = {'source_spell': False}
    result['pull_trace'][1]['long_cooldowns_not_ready_at_kill'] = {'source_spell': 46.}
    result['source_action_counts'] = {'source_spell': 1, 'filler_spell': 1}
    return result


def test_declared_long_cooldown_usage_matches_executed_source_actions():
    result = _contract_with_used_long_cooldown()
    assert validate_real_replay(result, 2)['actual_distinct_targets'] == 2


def test_reject_omitted_long_cooldown_use_even_when_action_counts_agree():
    """Previously a trace could hide a real source long-cooldown cast."""
    result = _contract_with_used_long_cooldown()
    result['pull_trace'][0]['long_cooldowns_used'] = {}
    with pytest.raises(ValueError, match='WF61_LONG_COOLDOWN_TRACE_INVALID'):
        validate_real_replay(result, 2)


def test_reject_underreported_long_cooldown_uses():
    """Reported cooldown uses must equal, not merely be <=, source actions."""
    result = _contract_with_used_long_cooldown()
    result['pull_trace'][0]['actions']['source_spell'] = 2
    result['source_action_counts']['source_spell'] = 2
    with pytest.raises(ValueError, match='WF61_LONG_COOLDOWN_TRACE_INVALID'):
        validate_real_replay(result, 2)
