"""G46 bounded real-action cooldown + resource channel regression."""
from dataclasses import replace
from pathlib import Path
from src.game.data.forever.mage import build_source_slice
from src.v2.generic_backend import _policy_combat_evaluation
from src.game.model import PeriodicResourceEffect
from src.version import SOFTWARE_VERSION


def test_g46_fire_blast_source_cooldown_and_real_policy_damage():
    for level in (10, 15, 20):
        ir = build_source_slice(level)
        blast = next(x for x in ir.actions if x.id == 'fire_blast:2136')
        assert blast.cooldown_s == 8 and blast.cast_time_s == 0
        ev, ex, _ = _policy_combat_evaluation(ir, level=level)
        assert ev and ex.timeline.target_defeated
        starts = [e.time_s for e in ex.timeline.events if e.kind == 'ActionStarted' and e.action_id == blast.id]
        assert starts
        assert all(b - a >= 8. - 1e-6 for a, b in zip(starts, starts[1:]))
        assert any(e.kind == 'Damage' and e.action_id == blast.id for e in ex.timeline.events)


def test_g46_evocation_channel_actual_mana_gain_and_level_gate():
    assert all(x.id != 'evocation:12051' for x in build_source_slice(19).actions)
    ir = build_source_slice(20)
    evo = next(x for x in ir.actions if x.id == 'evocation:12051')
    assert evo.cooldown_s == 480 and evo.cast_time_s == 8
    assert evo.metadata['channel'] and isinstance(evo.effects[0], PeriodicResourceEffect)
    low = replace(ir, resources=tuple(replace(r, initial_amount=100.) if r.id == 'mana' else r for r in ir.resources))
    ev, ex, _ = _policy_combat_evaluation(low, level=20)
    assert ev
    ticks = [e for e in ex.timeline.events if e.kind == 'PeriodicTick' and e.action_id == evo.id]
    assert len(ticks) == 8
    assert sum(e.payload.get('gained', 0) for e in ticks) > 0
    start = next(e.time_s for e in ex.timeline.events if e.kind == 'ActionStarted' and e.action_id == evo.id)
    end = next(e.time_s for e in ex.timeline.events if e.kind == 'ActionCompleted' and e.action_id == evo.id)
    assert abs((end-start)-8.) < 1e-6


def test_g46_no_mage_runtime_fork_and_version():
    code=(Path('src/game/runtime/simulator.py').read_text()+Path('src/game/policy.py').read_text()).lower()
    assert 'if mage' not in code and 'if class_key == "mage"' not in code
    assert SOFTWARE_VERSION=='0.11.48.167'
