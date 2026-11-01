"""Current `.289` held-out Druid 60-level L2 replay cannot silently promote DONE."""
from pathlib import Path
import json,copy
from src.v2.source_reference_route_evidence import (REFERENCE_PATH,checked_reference_druid_route)
from src.version import SOFTWARE_VERSION

ROOT=Path(__file__).resolve().parents[1]

def test_current_fullpoint_source_reference_reexecutes_all_sixty_levels():
    diag,rows=checked_reference_druid_route(ROOT,version=SOFTWARE_VERSION)
    assert diag['valid'] and len(rows)==60
    assert rows[('druid',1)]['seconds_per_mob']>0
    assert rows[('druid',60)]['seconds_per_mob']>0
    assert all(x['bounded_route_source']=='wf288-fullpoint-parent-replay' for x in rows.values())
    assert all('route_complete' not in x for x in rows.values())


def test_tampering_score_or_source_context_blocks_parent_route(tmp_path):
    original=json.loads((ROOT/REFERENCE_PATH).read_text())
    for field,value in [('full_cycle_s_per_mob',-1.),('source_context','bad')]:
        broken=copy.deepcopy(original)
        broken['steps'][0][field]=value
        path=tmp_path/REFERENCE_PATH;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(broken))
        diag,rows=checked_reference_druid_route(tmp_path,version=SOFTWARE_VERSION)
        assert not diag['valid'] and rows=={}


def test_parent_is_not_a_complete_world_route():
    x=json.loads((ROOT/REFERENCE_PATH).read_text())
    assert x['full_source_complete_checkpoints']==0
    assert x['full_world_legal_leveling_routes']==0
    assert x['gear_acquisition_verified'] is False
    assert x['trainer_quest_rune_verified'] is False
    assert x['independent_joint_search_performed'] is False
