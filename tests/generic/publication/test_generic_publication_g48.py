from src.v2.backend_decision import DecisionRecord
from src.v2.generic_backend import build_partial_generic_records


def test_g48_source_only_record_does_not_fabricate_decisions(monkeypatch):
    from src.game.data.forever import registry
    monkeypatch.setitem(registry._PROVIDERS, "proof_empty", lambda level: None)
    row = build_partial_generic_records(class_names=("proof_empty",), selected_level=10)[0].as_dict()
    availability = row["publication_availability"]
    assert set(availability) == {"selected_build", "gear", "stat_weights", "policy", "timing", "route"}
    assert set(availability.values()) == {"not_computed", "not_in_level_record"}
    assert row["capability"]["game_ir"] is False


def test_g48_manifest_is_field_derived_not_class_name():
    base = dict(record_id="test", backend={"kind": "generic"},
                identity={"class_name": "test"}, objective={},
                timing={"seconds_per_mob": 9},
                capability={"combat_evaluation": True,"policy_execution":True,
                            "gear_optimization":True,"stat_weight_evaluation":True},
                talents={"search_performed": True},
                gear={"status":"selected_named_catalogue_gear"},
                stat_weights={"strength": 1}, policy={"priority": ["a"]})
    availability = DecisionRecord(**base).as_dict()["publication_availability"]
    assert all(v == "available" for k,v in availability.items() if k != "route")
    assert availability["route"] == "not_in_level_record"
