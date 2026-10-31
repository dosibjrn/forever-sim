"""Real-snapshot and adversarial tests of the independent isolated-effect oracle."""
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import copy
import pytest

from src.v2.source_sqlite_direct_damage_oracle import (
    OracleMismatch, verify_direct_damage_trace, verify_isolated_direct_damage,
    verify_verified_direct_damage,
)
from src.v2.source_sqlite_spell_semantics import extract_semantic_observations
from src.v2.source_sqlite_typed_spell_facts import extract_verified_header_facts
from src.game.model.ir import ActionDefinition, ActorDefinition, DamageEffect
from src.game.runtime.simulator import execute_action
from src.game.runtime.state import ActorState, TargetState

DB = Path(__file__).resolve().parents[1] / 'data/forever/catalogue/forever_abilities.sqlite'
BATCH = '20261008T145657Z'


@pytest.mark.parametrize('spell_id,expected,school', [
    (116, 19.8, 'frost'), (120, 101.0, 'frost'), (133, 19.0, 'fire'),
])
def test_real_html_source_and_runtime_trace(spell_id, expected, school):
    proof = verify_verified_direct_damage(DB, batch_id=BATCH, spell_id=spell_id)
    assert proof['isolated_component_verified'] is True
    assert proof['oracle_expected_midpoint'] == pytest.approx(expected)
    assert proof['executor_observed_damage'] == pytest.approx(expected)
    assert proof['source_school'] == school
    assert proof['trace_event_kinds'] == ['ActionStarted', 'ActionCompleted', 'Damage']
    assert proof['source']['html_sha256']
    assert proof['whole_spell_verified'] is False
    assert proof['independent_reproduction_verified'] is False
    assert proof['ir_promotion_allowed'] is False
    assert proof['executable_effects'] == []


def _inputs():
    header = extract_verified_header_facts(DB, batch_id=BATCH, spell_id=116)
    return header, extract_semantic_observations(header)


@pytest.mark.parametrize('patch', [
    {'min': 1.0}, {'max': 999.0}, {'school': 'fire'},
])
def test_candidate_tampering_rejected(patch):
    h, s = _inputs()
    s = copy.deepcopy(s)
    s['observations'][0].update(patch)
    with pytest.raises(OracleMismatch):
        verify_isolated_direct_damage(h, s, observation_index=0)


def test_non_damage_observation_cannot_be_verified_as_damage():
    h, s = _inputs()
    with pytest.raises(OracleMismatch):
        verify_isolated_direct_damage(h, s, observation_index=1)


def test_source_clause_mutation_fails_closed():
    h, s = _inputs()
    h = copy.deepcopy(h)
    h['unparsed_effect_text'] = h['unparsed_effect_text'].replace('18.8', '98.8')
    with pytest.raises(ValueError):
        verify_isolated_direct_damage(h, s, observation_index=0)


def test_source_hash_or_spell_mismatch_fails_closed():
    h, s = _inputs()
    h = copy.deepcopy(h)
    h['source']['html_sha256'] = 'different'
    with pytest.raises(ValueError):
        verify_isolated_direct_damage(h, s, observation_index=0)


def test_wrong_index_and_bool_index_rejected():
    h, s = _inputs()
    for idx in (-1, 99, True):
        with pytest.raises(OracleMismatch):
            verify_isolated_direct_damage(h, s, observation_index=idx)


def _executor_probe():
    action = ActionDefinition(
        id='probe', family_key='test', name='test', owner_actor_id='actor',
        requirements=(), costs=(), cast_time_s=0.0, gcd_s=0.0,
        cooldown_s=0.0, effects=(DamageEffect(effect_type='damage', school='frost',
                              target='enemy', base_min=18.8, base_max=20.8),),
        provenance=(), metadata={})
    actor = ActorState.from_ir(ActorDefinition(id='actor', actor_type='player'), ())
    target = TargetState.with_health('target', 1_000_000)
    return execute_action(action=action, actor=actor, target=target)


def test_tampered_runtime_trace_is_rejected():
    result = _executor_probe()
    kwargs = dict(action_id='probe', actor_id='actor', target_id='target',
                  expected_damage=Decimal('19.8'), expected_school='frost')
    verify_direct_damage_trace(result=result, **kwargs)
    with pytest.raises(OracleMismatch):
        verify_direct_damage_trace(result=replace(result, total_damage=19.0), **kwargs)
    bad = list(result.events)
    bad[-1] = replace(bad[-1], payload={**bad[-1].payload, 'school': 'fire'})
    with pytest.raises(OracleMismatch):
        verify_direct_damage_trace(result=replace(result, events=tuple(bad)), **kwargs)
    with pytest.raises(OracleMismatch):
        verify_direct_damage_trace(result=replace(result, events=result.events[:-1]), **kwargs)
    with pytest.raises(OracleMismatch):
        verify_direct_damage_trace(result=result, **{**kwargs, 'expected_damage': Decimal('20.0')})


def test_unparseable_clause_rejected_even_if_semantics_were_prepopulated():
    h, s = _inputs()
    h = copy.deepcopy(h)
    s = copy.deepcopy(s)
    # Modify the source text and observation consistently: semantic audit still
    # passes, but independent grammar refuses an unsupported source sentence.
    text = h['unparsed_effect_text']
    lo, hi = s['observations'][0]['text_span']
    replacement = 'damage around 18.8 to 20.8 Frost damage'
    h['unparsed_effect_text'] = text[:lo] + replacement + text[hi:]
    s['observations'][0]['source_text'] = replacement
    s['observations'][0]['text_span'] = [lo, lo+len(replacement)]
    s['observations'][1]['text_span'] = [
        v+len(replacement)-(hi-lo) for v in s['observations'][1]['text_span']]
    s['unparsed_text'] = 'Launches a bolt of frost at the enemy, and'
    # This malformed residual may be caught by the audit before the oracle.
    with pytest.raises((OracleMismatch, ValueError)):
        verify_isolated_direct_damage(h, s, observation_index=0)
