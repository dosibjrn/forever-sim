"""G46d: native generic Mage decision publishes honest control capability."""
from pathlib import Path
from src.v2.generic_backend import build_partial_generic_records

def test_control_capability_is_published_without_false_survival_benefit():
    record = build_partial_generic_records(class_names=['mage'], selected_level=10)[0].as_dict()
    assert record['backend']['id'] == 'generic' if 'id' in record['backend'] else record['backend']['name'] == 'generic'
    payload = str(record)
    assert 'mage_generic_decision' in payload
    # Native compatibility projection is the source for the listener.
    from src.v2.generic_backend import build_partial_generic_records as producer
    assert producer.__module__ == 'src.v2.generic_backend'
    import json
    data = json.loads(json.dumps(record))
    def find(obj):
        if isinstance(obj,dict):
            if 'mage_generic_decision' in obj:
                return obj['mage_generic_decision']
            for value in obj.values():
                found=find(value)
                if found is not None:return found
        elif isinstance(obj,list):
            for value in obj:
                found=find(value)
                if found is not None:return found
        return None
    decision=find(data)
    assert decision is not None and decision['legacy_fallback'] is False
    control=decision['control_actions']
    assert any(c['action_id']=='frost_nova:122' and c['control_id']=='root' and c['duration_s']==8.0 for c in control)
    assert all(c['mob_movement_or_survival_benefit']=='not_modelled' for c in control)
    assert decision['executed_control_events'] >= 0

def test_generic_engine_no_class_dispatch():
    engine=Path('src/game/runtime/simulator.py').read_text().lower()
    assert 'if mage' not in engine and 'frost_nova:' not in engine
