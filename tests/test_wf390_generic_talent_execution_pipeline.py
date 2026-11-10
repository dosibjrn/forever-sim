from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime

ROOT=Path(__file__).resolve().parents[1]
MAGE=ROOT/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'


def test_retained_mage_source_talent_compiler_reports_coverage():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
    compiled,coverage=compile_talent_runtime(ir)
    assert len(compiled.talents)==coverage['talent_count']
    assert coverage['rank_count'] == coverage['rank_with_modifiers']+coverage['rank_missing_executor']
    assert coverage['rank_count'] >= 100
    assert coverage['eligible_for_checkpoint_acceptance'] is False
    assert coverage['full_talent_execution_certified'] is False
    assert coverage['rank_with_modifiers'] > 0
