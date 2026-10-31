import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'M47_PALADIN_L20_ADVERSARIAL_v0.11.47.1.json'


def _payload():
    return json.loads(P.read_text(encoding='utf-8'))


def test_l20_adversarial_falsifies_baseline_allocation_without_reversing_ret_vs_prot():
    p=_payload()
    assert p['version']=='v0.11.47.1'
    assert p['gate_a']['cell_closed'] is False
    assert p['classification']['baseline_selection']=='search_failure'
    assert p['classification']['smooth_vs_event']=='mechanic_fidelity_gap'
    ret=p['profiles']['retribution']['event_best']
    prot=p['profiles']['protection']['event_best']
    assert ret['event_complete'] and prot['event_complete']
    assert ret['talent_ranks'] != p['baseline']['talent_ranks']
    assert ret['event_mobs_per_hour'] > prot['event_mobs_per_hour']
    assert ret['smooth_rank'] > 1  # proves event rerank is material, not a no-op


def test_l20_adversarial_has_expanded_search_evidence():
    p=_payload()
    assert p['search']['candidate_pool'] >= 100
    assert p['search']['event_top_n_per_profile'] >= 16
    assert p['classification']['ret_vs_prot_event_margin_pct'] > 0
