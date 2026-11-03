"""Source spell-fact records must not import the transitional GameIR runtime.

The existing legacy normalizers still create the same executable actions.
MythicSim Rust remains the intended source-of-truth engine (#357/#359).
"""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_source_spell_facts_import_without_gameir_and_legacy_actions_still_build():
    code = """
import sys
from src.game.data.forever.direct_spells import DirectSpellSourceFact, normalize_direct_spell_slice
from src.game.data.forever.healing_spells import (
    DirectHealSourceFact, PeriodicHealSourceFact,
    normalize_direct_heal_action, normalize_periodic_heal_action,
)
from src.game.data.forever.periodic_spells import (
    DirectPeriodicSpellSourceFact, normalize_direct_periodic_action,
)
from src.shared.field_overlays import FieldOverlay
from src.game.model.overlay import FieldOverlay as LegacyFieldOverlay
assert LegacyFieldOverlay is FieldOverlay

assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

direct = DirectSpellSourceFact(
    family_key='fireball', name='Fireball', source_id=133, required_level=20,
    resource_id='mana', resource_cost=30.0, cast_time_s=2.5,
    damage_min=40.0, damage_max=50.0, spell_power_coefficient=0.4,
    school='fire', source_url='https://example.invalid/fireball',
    provenance={'sample': 'source-boundary-regression'},
)
assert direct.damage_min == 40.0
ir = normalize_direct_spell_slice(
    ruleset='forever', class_key='mage', fact=direct,
    overlays=(FieldOverlay(
        id='test', target_path='effects.0.base_min', operation='add', value=3.0,
    ),),
)
from src.game.model.ir import ActionDefinition, ResourceDefinition
assert 'src.game.model.ir' in sys.modules
assert ir.actor.id == 'player'
assert ir.resources[0].id == 'mana'
assert isinstance(ir.actions[0], ActionDefinition)
assert ir.actions[0].effects[0].base_min == 43.0
assert ir.actions[0].effects[0].base_max == 50.0
assert ir.actions[0].costs[0].amount == 30.0
assert ir.source_facts[0]['source']['entity_id'] == 133

health = ResourceDefinition(
    id='health', name='Health', owner_actor_id='player', scope='actor',
)
heal, raw = normalize_direct_heal_action(
    fact=DirectHealSourceFact(
        family_key='healing_touch', name='Healing Touch', rank_level=20,
        resource_id='mana', resource_cost=35.0, cast_time_s=3.0,
        heal_min=100.0, heal_max=130.0, spell_power_coefficient=0.85,
        source_url='https://example.invalid/heal', provenance={},
    ), actor=ir.actor, mana_resource=ir.resources[0], health_resource=health,
)
assert isinstance(heal, ActionDefinition)
assert heal.effects[0].effect_type == 'heal'
assert raw['fact_kind'] == 'direct_heal_tooltip'

hot, raw_hot = normalize_periodic_heal_action(
    fact=PeriodicHealSourceFact(
        family_key='rejuvenation', name='Rejuvenation', rank_level=20,
        resource_id='mana', resource_cost=25.0, total_heal=80.0,
        duration_s=12.0, tick_interval_s=3.0,
        spell_power_coefficient_per_tick=0.1,
        source_url='https://example.invalid/hot', provenance={},
    ), actor=ir.actor, mana_resource=ir.resources[0], health_resource=health,
)
assert isinstance(hot, ActionDefinition)
assert hot.effects[0].effect_type == 'periodic_heal'
assert raw_hot['fact_kind'] == 'periodic_heal_tooltip'

periodic, raw_periodic = normalize_direct_periodic_action(
    fact=DirectPeriodicSpellSourceFact(
        family_key='moonfire', name='Moonfire', source_id=8921,
        required_level=20, resource_id='mana', resource_cost=25.0,
        direct_min=25.0, direct_max=33.0, direct_spell_power_coefficient=0.2,
        periodic_total=40.0, periodic_duration_s=12.0,
        tick_interval_s=3.0, periodic_spell_power_coefficient_per_tick=0.05,
        school='arcane', source_url='https://example.invalid/periodic',
        provenance={},
    ), actor=ir.actor, resource=ir.resources[0],
)
assert isinstance(periodic, ActionDefinition)
assert len(periodic.effects) == 2
assert periodic.effects[1].effect_type == 'periodic_damage'
assert raw_periodic['fact_kind'] == 'direct_periodic_spell_tooltip'

try:
    normalize_direct_spell_slice(
        ruleset='forever', class_key='mage', fact=direct, resource=health,
    )
except ValueError as error:
    assert 'resource mismatch' in str(error)
else:
    raise AssertionError('legacy mismatched resource must still fail closed')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
