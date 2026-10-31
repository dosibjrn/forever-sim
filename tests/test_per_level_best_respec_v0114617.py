from types import SimpleNamespace

from src.v2.runner import _per_level_best_path
from src.v2 import decision_dashboard


class Node:
    def __init__(self, level, score, key, allocation):
        self.level=level; self.score_s_per_100=score; self.key=key
        self._allocation=allocation


def test_per_level_path_charges_one_second_only_when_allocation_changes(monkeypatch):
    monkeypatch.setattr('src.v2.runner._node_json', lambda n: {
        'level': n.level, 'score_s_per_100': n.score_s_per_100,
        'allocation': n._allocation, 'policy': 'x',
    })
    monkeypatch.setattr('src.objective.level_weight_per_100', lambda level: 1.0)
    pools={20:[Node(20,100,'b','B'),Node(20,90,'a','A')],
           21:[Node(21,80,'c','C')],
           22:[Node(22,70,'d','C')]}
    p=_per_level_best_path(pools,start_level=20,end_level=22,respec_seconds=1.0)
    assert [s['allocation'] for s in p['steps']]==['A','C','C']
    assert p['respec_levels']==[21]
    assert p['respecs_used']==1
    assert abs(p['hours']-(90+80+70+1)/3600)<1e-12


def test_decision_payload_exposes_per_level_rows(monkeypatch, tmp_path):
    # Keep file reads empty and inject one current-level summary for each production class.
    monkeypatch.setattr(decision_dashboard, 'read_json', lambda *a, **k: {})
    monkeypatch.setattr(decision_dashboard, 'CLASSES', ('mage','paladin','druid'))
    monkeypatch.setattr(decision_dashboard, '_level_rows', lambda cls, viewer: [
        {'level':20,'best':{'allocation':f'{cls}-fast','score_s_per_100':100.0,'stat_weights':{'x':1}},
         'event_validated_best':({'rotation':'event-rot'} if cls=='mage' else {})}
    ])
    payload=decision_dashboard.build_decision_payload(tmp_path,20)
    assert payload['per_level_best']['enabled'] is True
    assert payload['per_level_best']['respec_seconds']==1.0
    assert payload['per_level_rows']['mage'][0]['allocation']=='mage-fast'
    assert payload['per_level_rows']['mage'][0]['rotation']=='event-rot'
    assert payload['per_level_rows']['mage'][0]['decision_mode']=='per_level_best'
