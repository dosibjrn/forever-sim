import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_m47_baseline_has_exact_3x3_contract():
    p=json.loads((ROOT/'M47_3X3_BASELINE_v0.11.47.0.json').read_text(encoding='utf-8'))
    assert p['milestone']=='M47'
    assert p['status']=='BASELINE_IN_PROGRESS'
    rows=p['rows']
    cells={(r['class'],int(r['level'])) for r in rows}
    assert cells=={(c,l) for c in ('mage','paladin','druid') for l in (20,40,60)}
    for r in rows:
        assert float(r['mobs_per_hour'])>0
        assert float(r['seconds_per_mob'])>0
        assert str(r.get('allocation') or '').strip()
        assert str(r.get('rotation') or r.get('policy') or '').strip()
        assert r.get('search',{}).get('not_exhaustive') is True
        gear=r.get('gear_stats') or (r.get('details') or {}).get('gear_stats') or {}
        assert len(gear.get('slots') or {}) > 0
        sw=r.get('stat_weights') or (r.get('details') or {}).get('stat_weights') or {}
        assert sw


def test_m47_l20_mage_baseline_uses_all_spec_ice_lance_winner():
    p=json.loads((ROOT/'M47_3X3_BASELINE_v0.11.47.0.json').read_text(encoding='utf-8'))
    r=next(x for x in p['rows'] if x['class']=='mage' and int(x['level'])==20)
    assert 'ice_lance=1' in r['allocation']
    assert r['search']['event_rerank']['winner_has_ice_lance'] is True
