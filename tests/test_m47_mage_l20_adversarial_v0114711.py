import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'M47_MAGE_L20_ADVERSARIAL_v0.11.47.11.json'

def _payload():
    return json.loads(ART.read_text(encoding='utf-8'))

def test_l20_mage_gate_a_bounded_authority_keeps_published_winner():
    p=_payload()
    assert p['classification']=='closed_bounded'
    assert p['winner_matches_published_allocation'] is True
    assert p['authority_samples'] >= 32
    assert p['adversarial_winner']['allocation']==p['production_published']['allocation']
    assert abs(float(p['published_regret_mobs_per_hour'])) < 1e-9

def test_l20_mage_adversarial_pool_challenges_rotation_and_talent_families():
    p=_payload()
    assert p['candidate_count'] >= 20
    assert p['authority_finalist_count'] >= 8
    sources={r['source'] for r in p['authority_top']}
    # At least explicit non-published family/corridor evidence must survive to authority replay.
    assert any(s.startswith('family_corridor:') for s in sources)
    schools={r['school'] for r in p['authority_top']}
    assert 'frost' in schools
    # The tool evaluates Frost/Arcane/Fire for every finalist; scope text is part of the evidence contract.
    assert 'Frost/Arcane/Fire' in p['scope']
