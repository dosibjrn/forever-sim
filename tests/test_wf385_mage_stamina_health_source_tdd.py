"""Mage L30 P3: source-backed gear Stamina affects paid combat health without fake naked stats."""
from __future__ import annotations
import sqlite3
from pathlib import Path
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection, executable_gear_stats

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'

@pytest.fixture
def source_db(tmp_path):
    target=tmp_path/'source.sqlite'
    with sqlite3.connect(SOURCE) as src, sqlite3.connect(target) as dest:
        src.backup(dest)
        dest.execute('''INSERT INTO actor_stat_conversion_source_facts
            (class_key,source_stat,target_type,target_id,coefficient,baseline,authority,
             source_url,source_date,evidence,capture_id,operation,threshold,below_coefficient)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            ('mage','stamina','resource_capacity','health',10.,'delta_only',
             'foreverdb_forever_client_character_sheet','https://foreverdb.net/stats/mage',
             '2026-10-14','1 HP for first 20 Stamina, 10 HP thereafter. Naked Mage Stamina is unknown: gear delta uses explicit >=20 marginal assumption.',
             'wf385_mage_stamina_70374','threshold_linear',20.,1.))
    return target

def _health(ir):
    return next(x for x in ir.resources if x.id=='health')

def test_sourced_gear_stamina_increases_health_without_inventing_naked_stamina(source_db):
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=source_db)
    assert 'stamina' not in ir.actor.base_stats
    assert 'stamina' in executable_gear_stats(ir,db_path=source_db)
    assert any(row['source_stat']=='stamina' for row in ir.actor.metadata['canonical_primary_stat_conversions'])
    geared, report=apply_gear_selection(ir,aggregate_stats={'stamina':10.},db_path=source_db)
    assert 'stamina' not in report.unsupported_stats
    assert 'stamina' not in geared.actor.base_stats, 'do not pretend gear Stamina is total Stamina'
    assert _health(geared).capacity==pytest.approx(_health(ir).capacity+100.)
    assert _health(geared).initial_amount==pytest.approx(_health(ir).initial_amount+100.)
    assert geared.actor.metadata['canonical_missing_base_stat_proxies']['stamina']['assumed_at_least']==20.

def test_stamina_threshold_gear_marginal_is_monotone_and_not_first_twenty(source_db):
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=source_db)
    capacities=[]
    for stamina in (0.,5.,10.,20.):
        geared,_=apply_gear_selection(ir,aggregate_stats={'stamina':stamina},db_path=source_db)
        capacities.append(_health(geared).capacity)
    assert [round(x-capacities[0]) for x in capacities]==[0,50,100,200]

def test_without_sourced_conversion_stamina_stays_unknown_not_zero():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=SOURCE)
    assert 'stamina' not in executable_gear_stats(ir,db_path=SOURCE)
    geared, report=apply_gear_selection(ir,aggregate_stats={'stamina':10.},db_path=SOURCE)
    assert report.unsupported_stats['stamina']==10.
    assert _health(geared).capacity==_health(ir).capacity
