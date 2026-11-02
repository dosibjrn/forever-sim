"""P2 source-indexed pushback must compile and execute, not merely change IR."""
import json
from pathlib import Path
from dataclasses import replace

import pytest

from src.game.data.forever.sqlite_talents import _parse_rank_tooltip
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from tools.wf_gate_p2_live import _cast_pushback_runtime_witness

ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / 'data/forever/staged_druid_l30_talents_70338.sqlite'
CAPTURE = ROOT / 'data/forever/source_captures/secondary_druid_restoration_row1_2026-10-10.json'


def test_exact_sourced_rank_tooltips_compile_without_talent_name_special_case():
    payload = json.loads(CAPTURE.read_text())
    # Pinned captured ranks, not a test-invented coefficient or level.
    talents = payload.get('talents', payload.get('records', []))
    rows = next(t['ranks'] for t in talents if t['name'] == "Nature's Focus")
    mods = []
    for row in rows:
        source = {'url': 'https://wowforevertalents.com/druid/talents/nature-s-focus/'}
        compiled, missing, reason = _parse_rank_tooltip(
            row['raw_tooltip'], action_families={'wrath', 'starfire'},
            source=source)
        assert not missing and reason is None and len(compiled) == 1
        mod = compiled[0]
        assert mod.kind == 'cast_pushback_avoidance_chance'
        assert mod.target_id == 'damage_schools:arcane,nature'
        assert mod.value == pytest.approx(float(
            row['raw_tooltip'].split('%', 1)[0].split()[-1]) / 100.)
        mods.append(mod.value)
    assert mods == pytest.approx([.14, .28, .42, .56, .70])


def test_pushback_parser_rejects_invalid_fraction_and_scope():
    source = {'url': 'https://example.org/captured-rank'}
    for tooltip in (
        'Gives you a 101% chance to avoid interruption caused by damage while casting Arcane and Nature spells.',
        'Gives you a 14% chance to avoid interruption caused by damage while casting Arcane and Arcane spells.',
    ):
        modifiers, _, reason = _parse_rank_tooltip(
            tooltip, action_families={'wrath'}, source=source)
        assert not modifiers and reason == 'invalid_sourced_cast_pushback_scope_or_fraction'


def test_real_p2_cast_pushback_witness_positive_and_wrong_rank_negative():
    compiled, _ = compile_talent_runtime(build_game_ir_slice(
        class_key='druid', level=30, ability_db_path=STAGED))
    talent = next(t for t in compiled.talents if t.id == 'natures_focus')
    _, rank = next((i, r) for i, r in enumerate(talent.ranks) if r.rank == 1)
    before, _ = apply_talent_selection(
        compiled, {}, level=30, bonus_talent_points=5)
    after, _ = apply_talent_selection(
        compiled, {'natures_focus': 1}, level=30, bonus_talent_points=5)
    witness = _cast_pushback_runtime_witness(before, after, rank.modifiers[0])
    assert witness is not None
    assert witness['probe'] == 'paired_production_cast_pushback'
    assert witness['before_delay_s'] - witness['after_delay_s'] == pytest.approx(.5 * .14)
    assert _cast_pushback_runtime_witness(
        before, after, replace(rank.modifiers[0], value=.20)) is None
