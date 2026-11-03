"""Source-only player state facts do not eagerly load the legacy GameIR model.

This boundary is a transitional compatibility step: legacy normalization still
constructs the same ActorDefinition / ResourceDefinition instances. The selected
MythicSim Rust engine remains the long-term game-facts authority (#357/#359).
"""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_source_player_starting_state_import_and_legacy_normalization():
    code = """
import sys
from src.game.data.forever.player_state import (
    PlayerStartingStateSourceFact,
    classic_mana_bonus_from_intellect,
    normalize_player_starting_state,
)

assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules
assert classic_mana_bonus_from_intellect(-3) == 0.0
assert classic_mana_bonus_from_intellect(0) == 0.0
assert classic_mana_bonus_from_intellect(20) == 20.0
assert classic_mana_bonus_from_intellect(25) == 95.0
assert 'src.game.model.ir' not in sys.modules

fact = PlayerStartingStateSourceFact(
    class_key='mage', race_key='human', level=20,
    base_stats={'intellect': 25.0, 'stamina': 15.0}, base_mana=100.0,
    stat_provenance={'source': 'test'}, mana_provenance={'source': 'test'},
    health_capacity=250.0, health_provenance={'source': 'test'},
)
actor, mana, health = normalize_player_starting_state(fact)
from src.game.model.ir import ActorDefinition, ResourceDefinition
assert isinstance(actor, ActorDefinition)
assert isinstance(mana, ResourceDefinition)
assert isinstance(health, ResourceDefinition)
assert actor.id == 'player' and actor.base_stats['intellect'] == 25.0
assert actor.metadata == {'class_key': 'mage', 'race_key': 'human', 'level': 20}
assert mana.owner_actor_id == 'player'
assert mana.initial_amount == mana.capacity == 195.0
assert mana.metadata['intellect_mana_bonus'] == 95.0
assert mana.metadata['gear_included'] is False
assert health.id == 'health'
assert health.initial_amount == health.capacity == 250.0
assert health.state_status == 'qualified_proxy_starting_state'
assert 'src.game.model.ir' in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
