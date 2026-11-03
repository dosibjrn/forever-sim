"""P3 source raw chance stats really change paid gear and CombatRuntime.

No mock combat, artificial weights, or invented stat conversion constants.
The old source-backed item rating adapter owns chance meanings.
"""
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3_ratings import (
    source_item_stat_to_combat,
)
from src.game.gear import apply_stat_delta, apply_gear_selection
from src.game.runtime import ActorState
from src.game.model.ir import DamageEffect
from src.rulesets.forever.items.runtime_selection import available_items, item_vector


def _action_runtime_probe(ir, action, *, observe_periodic=False,
                          observe_controls=False, target_id='p3_gear_fixture',
                          target_spell_hit=1.0, capture_source_hit=False):
    """Execute real action on a live actor/target; deterministic fixture.

    Only differences that are actually observed in runtime count. No event
    count / ActionStarted shortcut. If not eligible, return no probe.
    """
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    from src.game.runtime.simulator import action_eligibility
    # A sourced positional precondition belongs to the encounter, not to a
    # hardcoded class whitelist. Construct the required controlled situation
    # for this effect probe and separately reject the opposite position.
    # This fixture is local to the P3 gear regression, not a world/2D execution path.
    positions={str(req.get('value') or '') for req in action.requirements
               if req.get('kind')=='relative_position_is'}
    if len(positions)>1 or (positions and not positions <= {'front','behind'}):
        return None
    required_position=next(iter(positions),None)

    def fixture_target(*, opposite=False):
        target=TargetState.with_health(target_id,100000.0,armor=0.0)
        target.metadata['spell_hit'] = float(target_spell_hit)
        if capture_source_hit:
            # The real source-captured target activates the production
            # expected-hit resolver; an ordinary generic dummy intentionally
            # does not apply sourced hit/miss mechanics.
            target.metadata['combat_capture_id'] = 'p3_sourced_hit_fixture'
        if required_position is not None:
            position=({'front':'behind','behind':'front'}[required_position]
                      if opposite else required_position)
            target.metadata['attacker_relative_position']=position
        return target

    # Check the *actual* runtime eligibility in each source mode. A caster mode
    # with an unrestricted enabled_action_ids list does not necessarily permit
    # a Bear-only action (e.g. Swipe). No class-specific mode names here.
    actor=None
    for mode in [None, *(m.id for m in ir.modes)]:
        candidate=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
        if mode is not None and candidate.current_mode_id!=mode:
            try:candidate.transition_mode(mode)
            except (ValueError,KeyError,AttributeError):continue
        target=fixture_target()
        if action_eligibility(action=action,actor=candidate,target=target).eligible:
            actor=candidate
            break
        # Resource availability is adjusted below; initial eligibility can
        # fail simply because Rage/Energy has not yet been seeded.
        for cost in action.costs:
            if cost.resource_id in candidate.resources:
                cap=max(float(cost.amount)+500.0,float(candidate.resource_capacity.get(cost.resource_id,0)))
                candidate.resource_capacity[cost.resource_id]=cap
                candidate.resources[cost.resource_id]=cap
        if action_eligibility(action=action,actor=candidate,target=target).eligible:
            actor=candidate
            break
    if actor is None:return None
    for cost in action.costs:
        if cost.resource_id in actor.resources:
            cap=max(float(cost.amount)+500.0,float(actor.resource_capacity.get(cost.resource_id,0)))
            actor.resource_capacity[cost.resource_id]=cap
            actor.resources[cost.resource_id]=cap
    if 'health' in actor.resources:
        actor.resource_capacity['health']=max(float(actor.resource_capacity.get('health',0)),10000.)
        actor.resources['health']=actor.resource_capacity['health']-1000.
    rt=CombatRuntime(actor=actor,target=fixture_target())
    if not action_eligibility(action=action,actor=actor,target=rt.target).eligible:return None
    if required_position is not None:
        # Positive/negative positional control through production eligibility:
        # a Shred-style rear-only action must remain illegal from the front.
        if action_eligibility(action=action,actor=actor,
                              target=fixture_target(opposite=True)).eligible:
            return None
    before=dict(actor.resources)
    try:
        end=rt.schedule_action(action)
        rt.advance_to(end + 0.01)
        # A target debuff can expire before the final periodic tick. Capture
        # actual applied state immediately, not merely a queued aura intent.
        target_stat_modifiers_on_apply=dict(rt.target.active_stat_modifiers)
        if observe_periodic:
            # Observe the actual tick series, not just the aura application.
            duration=max((float(e.duration_s) for e in action.effects if hasattr(e,'tick_interval_s')),default=0.0)
            if duration>0:rt.advance_to(end+duration+0.02)
    except (ValueError,KeyError,RuntimeError,AttributeError,TypeError):return None
    events=[{'kind':e.kind,'amount':float(e.payload.get('amount',0.0)),
             'periodic':bool(e.payload.get('periodic'))}
            for e in rt.trace if e.kind in ('Damage','Heal')]
    controls=([{'control_id':str(e.payload.get('control_id')),
                'duration_s':float(e.payload.get('duration_s',0.)),
                'proc_chance':float(e.payload.get('proc_chance',0.)),
                'proc_roll':e.payload.get('proc_roll'),
                'proc_triggered':e.payload.get('proc_triggered') is True,
                'applied':e.payload.get('applied') is True,
                'prevents_enemy_actions':e.payload.get('prevents_enemy_actions') is True,
                'breaks_on_damage':e.payload.get('breaks_on_damage') is True}
               for e in rt.trace if e.kind=='ControlApplied']
              if observe_controls else [])
    return {'controls':controls,
            'active_controls':(dict(rt.target.active_controls) if observe_controls else {}),
            'target_stat_modifiers_on_apply':target_stat_modifiers_on_apply,
            'completion_s':float(end), 'gcd_ready_s':float(actor.gcd_ready_s),'spent':{
                c.resource_id:round(before.get(c.resource_id,0)-actor.resources.get(c.resource_id,0),6)
                for c in action.costs},
            'damage':sum(e['amount'] for e in events if e['kind']=='Damage'),
            'heal':sum(e['amount'] for e in events if e['kind']=='Heal'),
            'direct_damage':sum(e['amount'] for e in events if e['kind']=='Damage' and not e['periodic']),
            'periodic_damage':sum(e['amount'] for e in events if e['kind']=='Damage' and e['periodic']),
            'direct_heal':sum(e['amount'] for e in events if e['kind']=='Heal' and not e['periodic']),
            'periodic_heal':sum(e['amount'] for e in events if e['kind']=='Heal' and e['periodic']),
            'events':events}




def _actual_druid():
    ir = build_game_ir_slice(class_key="druid", level=60)
    assert ir is not None
    return ir


def _offensive_cast(ir):
    # Real canonical source action, no synthetic damage effect constructed.
    for action in ir.actions:
        if any(isinstance(e, DamageEffect) and
               str(e.school).lower() != "physical"
               and e.crit_multiplier > 1 for e in action.effects):
            probe = _action_runtime_probe(
                ir, action, target_spell_hit=.5, capture_source_hit=True)
            if probe and probe["direct_damage"] > 0:
                return action, probe
    raise AssertionError("NO_EXECUTABLE_SOURCED_MAGIC_DAMAGE_ACTION")


def test_crit_and_hit_raw_gear_axes_exist_on_actual_source_items():
    rows = available_items("druid", 60, required_level_policy="catalogue")
    for axis in ("crit", "hit", "dodge"):
        row = next((item for item in rows if getattr(item, axis, 0) > 0), None)
        assert row is not None, f"NO_SOURCED_ITEM_WITH_{axis}"
        assert item_vector(row)[axis] == pytest.approx(float(getattr(row, axis)))


def test_real_source_gear_application_feeds_live_hit_and_crit_channels():
    ir = _actual_druid()
    for key, amount, dest in (("crit", 14., ("spell_crit_chance", "melee_crit_chance")),
                              ("hit", 10., ("spell_hit_bonus", "melee_hit_bonus")),
                              ("dodge", 12., ("dodge_chance",))):
        source = source_item_stat_to_combat(key, amount, level=60)
        assert source["mechanic_status"] == "SOURCE_DISPLAY_MAPPING_AND_EXECUTOR_CHANCE"
        via_probe = apply_stat_delta(ir, key, amount)
        via_gear, receipt = apply_gear_selection(ir, aggregate_stats={key: amount})
        for actual in (via_probe, via_gear):
            actor = ActorState.from_ir(actual.actor, actual.resources, actual.modes)
            baseline = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
            for channel in dest:
                assert actor.stats[channel] - baseline.stats.get(channel, 0.) == pytest.approx(.01)
        assert receipt.applied_stats[key] == amount


def test_actual_combat_cast_damage_improves_with_sourced_item_crit():
    ir = _actual_druid()
    action, baseline = _offensive_cast(ir)
    improved = apply_stat_delta(ir, "crit", 14.)
    same_action = next(a for a in improved.actions if a.id == action.id)
    actual = _action_runtime_probe(
        improved, same_action, target_spell_hit=.5, capture_source_hit=True)
    assert actual is not None
    assert actual["direct_damage"] > baseline["direct_damage"]


def test_actual_combat_hit_chance_improves_with_sourced_item_hit():
    ir = _actual_druid()
    action, baseline = _offensive_cast(ir)
    improved = apply_stat_delta(ir, "hit", 10.)
    same_action = next(a for a in improved.actions if a.id == action.id)
    actual = _action_runtime_probe(
        improved, same_action, target_spell_hit=.5, capture_source_hit=True)
    assert actual is not None
    assert actual["direct_damage"] > baseline["direct_damage"]
