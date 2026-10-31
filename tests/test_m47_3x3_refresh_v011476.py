import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'M47_3X3_REFRESH_v0.11.47.6.json'

def test_refresh_has_exact_matrix_and_current_paladin_selection():
    p=json.loads(P.read_text(encoding='utf-8'))
    rows={(r['class'],int(r['level'])):r for r in p['rows']}
    assert set(rows)=={(c,l) for c in ('mage','paladin','druid') for l in (20,40,60)}
    expected={20:299.6347129412936,40:225.37597362605996,60:221.78195009230603}
    for level,mph in expected.items():
        r=rows[('paladin',level)]
        assert r['selection_authority']=='deterministic_event_reranked_expanded_finalists'
        assert abs(float(r['mobs_per_hour'])-mph)<1e-6
        assert r['gate_a_status']['selection']=='closed'
        assert r['gate_a_status']['gate_a']=='open'

def test_refresh_carries_druid_l60_bounded_closure_and_explicit_gap_list():
    p=json.loads(P.read_text(encoding='utf-8'))
    rows={(r['class'],int(r['level'])):r for r in p['rows']}
    assert rows[('druid',60)]['gate_a_status']['gate_a']=='closed_bounded'
    gaps={(g['class'],int(g['level'])) for g in p['remaining_gate_a_gaps']}
    assert ('druid',60) not in gaps
    assert ('druid',20) in gaps and ('druid',40) in gaps
    assert all(('paladin',l) in gaps for l in (20,40,60))
