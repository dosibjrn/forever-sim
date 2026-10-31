"""Independent numeric oracle for *isolated* source-backed direct damage components.

This is a verification probe, not a source-to-executable-IR converter.
An isolated synthetic action deliberately excludes real spell costs, cast times,
targeting, additional effects, crits and scaling. Passing proves only the
deterministic unscaled midpoint and trace of one component; whole spells remain
BLOCKED_UNPARSED_EFFECTS until every proof dimension and E2E test passes.

Independence boundary: the oracle reads the original verified tooltip substring
and tokenizes it independently of source_sqlite_spell_semantics' regex. The
candidate executor effect is constructed from the semantic observation, not the
oracle result. Both are compared, along with the actual generic runtime trace.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path

from src.game.model.ir import ActionDefinition, ActorDefinition, DamageEffect
from src.game.runtime.simulator import execute_action
from src.game.runtime.state import ActorState, TargetState
from src.v2.source_sqlite_semantic_audit import audit_semantic_completeness
from src.v2.source_sqlite_spell_semantics import extract_semantic_observations
from src.v2.source_sqlite_typed_spell_facts import extract_verified_header_facts


class OracleMismatch(ValueError):
    """The candidate, source text, or runtime trace did not agree."""


def _source_direct_damage_clause(text: str) -> tuple[Decimal, Decimal, str]:
    """Separate six-token grammar; never use the semantic extractor's regex."""
    words = text.split()  # Unicode NBSP and ordinary whitespace normalize here.
    if (len(words) != 6 or words[0].lower() not in ('causes', 'causing', 'take')
            or words[2].lower() != 'to' or words[5].lower() != 'damage'
            or words[4].lower() not in ('arcane', 'fire', 'frost', 'nature', 'shadow', 'holy')):
        raise OracleMismatch('not an unambiguous isolated direct-damage source clause')
    try:
        low, high = Decimal(words[1]), Decimal(words[3])
    except InvalidOperation as exc:
        raise OracleMismatch('source damage range is not numeric') from exc
    if not low.is_finite() or not high.is_finite() or low < 0 or low > high:
        raise OracleMismatch('invalid source damage range')
    return low, high, words[4].lower()


def verify_direct_damage_trace(*, result, action_id: str, actor_id: str,
                               target_id: str, expected_damage: Decimal,
                               expected_school: str) -> None:
    """Verify the *actual* generic executor result and all damage events."""
    amount = float(expected_damage)
    if not math.isclose(result.total_damage, amount, rel_tol=0, abs_tol=1e-9):
        raise OracleMismatch('runtime total damage differs from source midpoint')
    if not math.isclose(result.target_start_health-result.target_end_health, amount,
                        rel_tol=0, abs_tol=1e-9):
        raise OracleMismatch('runtime target health delta differs from source midpoint')
    if result.target_defeated or result.resources_before != result.resources_after:
        raise OracleMismatch('isolated probe had unexpected death/resource effects')
    events = list(result.events)
    if [event.kind for event in events] != ['ActionStarted', 'ActionCompleted', 'Damage']:
        raise OracleMismatch('unexpected isolated runtime event sequence')
    for event in events:
        if (event.action_id != action_id or event.actor_id != actor_id
                or event.target_id != target_id or not math.isclose(event.time_s, 0.0, abs_tol=1e-12)):
            raise OracleMismatch('unexpected runtime event identity or timing')
    damage = events[-1]
    if (damage.payload.get('school') != expected_school
            or damage.payload.get('periodic') is not False
            or damage.payload.get('applied') is not True
            or damage.payload.get('resolution') != 'expected_value'
            or damage.payload.get('effect_index') != 0
            or not math.isclose(float(damage.payload.get('amount', float('nan'))), amount,
                                rel_tol=0, abs_tol=1e-9)):
        raise OracleMismatch('runtime damage event disagrees with source oracle')


def verify_isolated_direct_damage(header: dict, semantic: dict, *,
                                  observation_index: int) -> dict:
    """Reproduce one isolated source clause against the generic executor.

    Never promote a spell, even when this component passes. The input header
    must come from the verified SQLite snapshot reader; the adapter itself
    does not certify arbitrary caller-provided headers as genuine HTML.
    """
    audit = audit_semantic_completeness(header, semantic)
    if audit['ir_promotion_allowed'] is not False or audit['execution_status'] != 'BLOCKED_UNPARSED_EFFECTS':
        raise OracleMismatch('source audit is not fail-closed')
    observations = semantic['observations']
    if type(observation_index) is not int or not (0 <= observation_index < len(observations)):
        raise OracleMismatch('invalid observation index')
    obs = observations[observation_index]
    if obs.get('kind') != 'direct_school_damage_range':
        raise OracleMismatch('only isolated direct-school-damage-range is supported')
    lo, hi = obs['text_span']
    original = header['unparsed_effect_text'][lo:hi]
    low, high, school = _source_direct_damage_clause(original)
    if (not math.isclose(float(low), obs['min'], rel_tol=0, abs_tol=1e-12)
            or not math.isclose(float(high), obs['max'], rel_tol=0, abs_tol=1e-12)
            or obs['school'] != school):
        raise OracleMismatch('semantic candidate differs from independent source oracle')
    expected = (low + high) / Decimal(2)
    # Deliberately synthetic, zero-cost, zero-cast, zero-scaling *component*
    # probe. Never add this action to the real Game IR or the policy search.
    action_id = f'isolated-source-probe:{header["spell_id"]}:{observation_index}'
    actor_id, target_id = 'source-oracle-actor', 'source-oracle-target'
    effect = DamageEffect(effect_type='damage', school=obs['school'], target='enemy',
                          base_min=obs['min'], base_max=obs['max'],
                          spell_power_coefficient=0.0)
    action = ActionDefinition(id=action_id, family_key='isolated-source-probe',
                              name='Isolated source component (not a spell)',
                              owner_actor_id=actor_id, requirements=(), costs=(),
                              cast_time_s=0.0, gcd_s=0.0, cooldown_s=0.0,
                              effects=(effect,), provenance=(), metadata={})
    actor = ActorState.from_ir(ActorDefinition(id=actor_id, actor_type='player'), ())
    target = TargetState.with_health(target_id, 1_000_000.0)
    result = execute_action(action=action, actor=actor, target=target, spell_power=0.0)
    verify_direct_damage_trace(result=result, action_id=action_id, actor_id=actor_id,
                               target_id=target_id, expected_damage=expected,
                               expected_school=school)
    return {
        'spell_id': header['spell_id'], 'source': header['source'],
        'observation_index': observation_index, 'source_span': [lo, hi],
        'source_text': original, 'effect_family': 'direct_school_damage_range',
        'source_min': float(low), 'source_max': float(high), 'source_school': school,
        'oracle_expected_midpoint': float(expected),
        'executor_observed_damage': result.total_damage,
        'trace_event_kinds': [event.kind for event in result.events],
        'isolated_component_verified': True,
        'verification_scope': 'unscaled_expected_value_midpoint_only',
        'whole_spell_verified': False, 'independent_reproduction_verified': False,
        'end_to_end_regression_verified': False,
        'ir_promotion_allowed': False, 'execution_status': 'BLOCKED_UNPARSED_EFFECTS',
        'executable_effects': [], 'remaining_source_blockers': audit['blockers'],
    }


def verify_verified_direct_damage(database: str | Path, *, batch_id: str,
                                  spell_id: int, observation_index: int = 0) -> dict:
    header = extract_verified_header_facts(database, batch_id=batch_id, spell_id=spell_id)
    semantic = extract_semantic_observations(header)
    return verify_isolated_direct_damage(header, semantic, observation_index=observation_index)
