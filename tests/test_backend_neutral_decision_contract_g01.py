from __future__ import annotations

import json

from src.v2.backend_decision import DECISION_CONTRACT_VERSION, DecisionRecord
from src.v2 import decision_dashboard


def _paladin_endpoint() -> dict:
    return {
        "schema_version": 1,
        "ruleset": "forever",
        "classes": {
            "paladin": {
                "targets": {
                    "20": {
                        "status": "available",
                        "target_level": 20,
                        "routes": {
                            "unconstrained": {
                                "status": "available",
                                "path": {
                                    "steps": [
                                        {
                                            "level": 20,
                                            "allocation": "holy(0) / protection(0) / retribution(11)[deflection:5,benediction:1,conviction:4,seal_of_command:1]",
                                            "talent_ranks": {
                                                "deflection": 5,
                                                "benediction": 1,
                                                "conviction": 4,
                                                "seal_of_command": 1,
                                            },
                                            "tree_points": {"holy": 0, "protection": 0, "retribution": 11},
                                            "talent_family": "retribution",
                                            "combat_profile": "retribution",
                                            "gear": "2h_normal",
                                            "pull_size": 2,
                                            "score_s_per_100": 1320.0,
                                            "mobs_per_hour": 272.727,
                                        }
                                    ]
                                },
                                "transitions": [],
                            }
                        },
                    }
                }
            }
        },
    }


def _paladin_matrix() -> dict:
    return {
        "schema_version": 1,
        "ruleset": "forever",
        "classes": {
            "paladin": {
                "schema_version": 2,
                "class": "paladin",
                "matrices": {
                    "20:unconstrained": {
                        "status": "available",
                        "target_level": 20,
                        "route": "unconstrained",
                        "rows": [
                            {
                                "level": 20,
                                "combat_profile": "retribution",
                                "gear": "2h_normal",
                                "pull_size": 2,
                                "mobs_per_hour": 273.4,
                                "seconds_per_mob": 13.17,
                                "kill_seconds_per_mob": 8.55,
                                "recovery_seconds_per_mob": 3.52,
                                "travel_seconds_per_mob": 1.10,
                                "rotation": "Seal of Command up; Judgement on CD; Holy Strike on CD; melee weave",
                                "stat_weights": {
                                    "stats": {
                                        "strength": {"seconds_saved_per_100_per_point": 2.5},
                                        "intellect": {"seconds_saved_per_100_per_point": 0.0},
                                    }
                                },
                                "gear_stats": {
                                    "slots": {
                                        "weapon": {
                                            "slot": "weapon",
                                            "name": "Wolfsbane",
                                            "weapon_dps": 25.6,
                                            "weapon_speed": 3.4,
                                        }
                                    }
                                },
                            }
                        ],
                    }
                },
            }
        },
    }


def test_decision_record_is_backend_neutral_and_roundtrips_listener_row():
    row = {
        "level": 20,
        "decision_row_id": "paladin:20:unconstrained:20:test",
        "score_s_per_100": 1317.0,
        "mobs_per_hour": 273.4,
        "seconds_per_mob": 13.17,
        "kill_seconds_per_mob": 8.55,
        "recovery_seconds_per_mob": 3.52,
        "travel_seconds_per_mob": 1.10,
        "allocation": "retribution",
        "talent_ranks": {"seal_of_command": 1},
        "gear": "2h_normal",
        "gear_stats": {"slots": {"weapon": {"name": "Wolfsbane"}}},
        "rotation": "Seal; Judgement; melee",
        "stat_weights": {"stats": {"strength": {"seconds_saved_per_100_per_point": 2.5}}},
        "data_sources": ["endpoint_path", "spec_matrix"],
    }
    record = DecisionRecord.from_legacy_route_row(
        class_name="paladin", target_level=20, route_name="unconstrained", row=row
    )
    data = record.as_dict()
    assert data["schema_version"] == DECISION_CONTRACT_VERSION
    assert data["backend"]["id"] == "legacy"
    assert data["identity"]["class_name"] == "paladin"
    assert data["identity"]["target_level"] == 20
    assert data["objective"]["mobs_per_hour"] == 273.4
    assert data["timing"]["kill_seconds_per_mob"] == 8.55
    assert data["talents"]["ranks"]["seal_of_command"] == 1
    assert data["gear"]["snapshot"]["slots"]["weapon"]["name"] == "Wolfsbane"
    # G02+ will populate these first-class collections; G01 already fixes their
    # stable location in the contract instead of adding class-shaped fields.
    assert data["actors"] == []
    assert data["resources"] == []
    assert data["actions"] == []
    compat = record.legacy_route_row()
    assert compat["decision_contract"]["record_id"] == data["record_id"]
    assert compat["decision_contract"]["backend"]["id"] == "legacy"
    assert compat["kill_seconds_per_mob"] == 8.55


def test_decisions_api_publishes_flat_contract_and_listener_rows_cross_it(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_dashboard, "CLASSES", ("paladin",))
    decision_root = tmp_path / "state/decisions/forever"
    decision_root.mkdir(parents=True)
    for name, obj in {
        "endpoint_paths.json": _paladin_endpoint(),
        "spec_matrix.json": _paladin_matrix(),
        "spec_regret.json": {"classes": {}},
        "dual_spec.json": {"classes": {}},
    }.items():
        (decision_root / name).write_text(json.dumps(obj), encoding="utf-8")

    payload = decision_dashboard.build_decision_payload(tmp_path, selected_level=20)
    assert payload["decision_contract_version"] == DECISION_CONTRACT_VERSION
    assert payload["backends"][0]["id"] == "legacy"
    decisions = payload["decisions"]
    assert decisions
    record = next(
        d for d in decisions
        if d["identity"]["class_name"] == "paladin"
        and d["identity"]["target_level"] == 20
        and d["identity"]["route"] == "unconstrained"
    )
    assert record["backend"]["id"] == "legacy"
    assert record["identity"]["level"] == 20
    assert record["objective"]["mobs_per_hour"] == 273.4
    assert record["policy"]["label"].startswith("Seal of Command")

    # The compatibility route consumed by today's listener is derived from the
    # same DecisionRecord authority, not published independently beside it.
    row = payload["route_rows"]["paladin"]["20"]["routes"]["unconstrained"]["rows"][0]
    assert row["decision_contract"]["record_id"] == record["record_id"]
    assert row["decision_contract"]["backend"]["id"] == "legacy"


def test_listener_surfaces_backend_contract_provenance():
    from src import listener
    html = listener.DECISIONS_HTML
    assert "row?.decision_contract?.backend" in html
    assert "backend ${esc(backendLabel)}" in html
