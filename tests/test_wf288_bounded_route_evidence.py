"""No fake promotion of stale or tampered multi-level native route results."""
import copy
import json
from pathlib import Path
from hashlib import sha256

from src.v2.source_bounded_route_evidence import (EVIDENCE_FILE,
    checked_source_scenario_routes)
from src.version import SOFTWARE_VERSION

ROOT=Path(__file__).resolve().parents[1]
ITEM=ROOT/'data/forever/catalogue/items_2026-09-29.sqlite'


def checked(root=ROOT):
    return checked_source_scenario_routes(root,version=SOFTWARE_VERSION,
        item_db_sha=sha256(ITEM.read_bytes()).hexdigest())


def staged(tmp_path,data):
    path=tmp_path/EVIDENCE_FILE
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data))
    return checked(tmp_path)


def test_real_evidence_is_legal_and_bounded_but_not_complete():
    info,rows=checked()
    assert info['valid'] and info['full_bounded_corridors']==8
    assert len(rows)==97 and info['scratch_verified_source_scenario_steps']==97
    assert rows['druid',20]['seconds_per_mob']>0
    assert ('warlock',19) not in rows
    assert all('route_complete' not in row for row in rows.values())


def test_bad_version_source_and_legality_do_not_promote(tmp_path):
    original=json.loads((ROOT/EVIDENCE_FILE).read_text())
    cases=[]
    def case(modify):
        d=copy.deepcopy(original);modify(d);cases.append(d)
    case(lambda d:d.__setitem__('software_version','0.11.48.0'))
    case(lambda d:d.__setitem__('canonical_item_db_sha256','0'*64))
    case(lambda d:d['classes']['mage']['selected_route'][3].__setitem__('source_context','0'*64))
    case(lambda d:d['classes']['druid']['selected_route'][0].__setitem__('full_cycle_s_per_mob',999.0))
    case(lambda d:d['classes']['rogue']['selected_route'][3].__setitem__('level',42))
    case(lambda d:d['classes']['druid']['selected_route'][3].__setitem__('talents',{'improved_wrath':999}))
    case(lambda d:d['classes']['druid']['selected_route'][3].__setitem__('scratch_verification_complete',False))
    case(lambda d:d['classes']['hunter'].__setitem__('named_gear_acquisition_verified',True))
    case(lambda d:d['summary'].__setitem__('full_bounded_legal_source_scenario_corridors',9))
    for value in cases:
        info,rows=staged(tmp_path,value)
        assert not info['valid'] and not rows and info['failures']


def test_missing_evidence_cannot_claim_route(tmp_path):
    info,rows=checked(tmp_path)
    assert not info['valid'] and rows=={}
