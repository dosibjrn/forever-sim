"""Keep queued-swing source observation tools independent of legacy GameIR imports.

The existing executable GameIR action builder stays live until the selected
MythicSim Rust path replaces its actual callers (#357/#359).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_queued_swing_observation_parser_has_no_eager_game_ir_dependency():
    code = """
import sys
from src.game.data.forever import source_queued_swing as queued
from src.game.data.forever.source_db_scope import DEFAULT_DB

assert queued.DEFAULT_DB is DEFAULT_DB
observed = {
    'cost': '20 Rage', 'effect_text': "Increases the bear's next attack by 45 damage.",
    'cast': 'Next Melee', 'gcd': '0 sec', 'cooldown': 'n/a',
    'required_mode_id': 'bear', 'form_requirement': 'Bear Form',
}
assert queued.parse_observation(observed) == {
    'required_mode_id': 'bear', 'bonus_damage': 45.0,
    'cost_resource': 'rage', 'cost_amount': 20.0,
}
try:
    queued.parse_observation({**observed, 'cast': 'Instant'})
except ValueError as exc:
    assert str(exc) == 'SOURCE_QUEUED_SWING_UNPARSED_OBSERVATION'
else:
    raise AssertionError('malformed observation was accepted')

for name in ('src.game.model.ir',
             'src.game.data.forever.sqlite_talents',
             'src.game.runtime.simulator'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, text=True,
        capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_queued_swing_legacy_builder_remains_executable():
    from src.game.data.forever.registry import build_game_ir_slice

    for class_key, level in (("hunter", 10), ("paladin", 20)):
        ir = build_game_ir_slice(class_key=class_key, level=level)
        assert ir is not None
        assert ir.actor.metadata["class_key"] == class_key
        assert ir.actions
