"""WF268: legacy Cat and generic IR use identical, explicit qualified SQL target facts."""
from pathlib import Path
from tempfile import TemporaryDirectory
from shutil import copyfile
from dataclasses import replace
from unittest.mock import patch
import sqlite3
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.target_combat_source import (
    physical_outgoing_expected_factors, source_enrich_target_combat, target_combat_metadata)
from src.game.data.forever.registry import build_game_ir_slice
from src.rulesets.forever.classes.druid.talents import Talents
from src.rulesets.forever.classes.druid.mechanics import _cat_single
import src.rulesets.forever.classes.druid.mechanics as old_druid

@pytest.mark.parametrize('level', (10, 20, 40, 60))
def test_shared_target_profile_matches_ir_source(level):
    ir=build_game_ir_slice(class_key='druid',level=level)
    profile=target_combat_metadata(ir)
    old=physical_outgoing_expected_factors(level)
    assert old['target_armor']==profile['armor']
    assert old['application_hit']==profile['melee_hit']
    assert old['direct_multiplier']==pytest.approx(
        profile['melee_hit']*(1-min(profile['armor_reduction_cap'],
        profile['armor']/(profile['armor']+profile['armor_constant']))))
    assert old['source_status']=='classic_proxy_not_forever_server_verified'


def test_legacy_druid_cat_uses_sqlite_defense_and_historical_unmitigated_is_distinct():
    build=Talents(ferocity=5,heart_of_the_wild=3,thick_hide=2,savage_fury=1)
    current=_cat_single(20,build)
    with patch.object(old_druid,'physical_outgoing_expected_factors',return_value={
        'direct_multiplier':1.0,'application_hit':1.0,
        'target_armor':0.0,'armor_reduction':0.0,'capture_id':'historical-no-defense',
        'source_status':'counterfactual_test_only'}):
        historical=_cat_single(20,build)
    assert current['kill_s']>historical['kill_s']
    assert current['outgoing_target_combat']['direct_multiplier']==pytest.approx(.6794959128065394)
    assert historical['outgoing_target_combat']['capture_id']=='historical-no-defense'


def test_data_only_patch_changes_both_source_compiler_and_old_cat_without_engine_edit():
    with TemporaryDirectory() as temp:
        db=Path(temp)/'source.sqlite'
        copyfile(DEFAULT_DB,db)
        with sqlite3.connect(db) as c:
            c.execute('UPDATE outgoing_combat_profile_source_facts SET target_armor=1100,melee_hit=0.91, capture_id=? '
                'WHERE scenario_key=? AND level=20',('wf268_data_only_negative_probe','ordinary_melee_classic_proxy'))
        factors=physical_outgoing_expected_factors(20,db_path=db)
        source=build_game_ir_slice(class_key='druid',level=20)
        # The IR compiler also reads that one edited SQLite row.
        bare=replace(source,provenance={k:v for k,v in source.provenance.items() if k!='target_combat_profile'})
        with pytest.raises(ValueError, match='duplicate'):
            # Already enriched action types cannot be re-enriched silently.
            source_enrich_target_combat(bare,db_path=db)
        with patch.object(old_druid,'physical_outgoing_expected_factors',return_value=factors):
            legacy=_cat_single(20,Talents(ferocity=5))
        assert legacy['outgoing_target_combat']['capture_id']=='wf268_data_only_negative_probe'
        assert legacy['outgoing_target_combat']['application_hit']==pytest.approx(.91)
        assert factors['direct_multiplier']<physical_outgoing_expected_factors(20)['direct_multiplier']


def test_unsupported_level_fails_closed_not_zero_armor_fallback():
    with pytest.raises(ValueError,match='no sourced enemy armor/hit profile'):
        physical_outgoing_expected_factors(1000)
