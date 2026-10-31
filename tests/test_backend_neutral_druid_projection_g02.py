from __future__ import annotations

from src.v2.backend_decision import DecisionRecord


def _cat_row() -> dict:
    return {
        "level": 20,
        "decision_row_id": "druid:20:unconstrained:20:test",
        "decision_mode": "unconstrained",
        "combat_profile": "cat",
        "score_s_per_100": 1045.4,
        "mobs_per_hour": 344.3,
        "seconds_per_mob": 10.454,
        "kill_seconds_per_mob": 7.006,
        "recovery_seconds_per_mob": 1.248,
        "travel_seconds_per_mob": 2.2,
        "allocation": "feral(11)",
        "talent_ranks": {"ferocity": 5},
        "tree_points": {"balance": 0, "feral": 11, "restoration": 0},
        "talent_family": "feral",
        "gear": "canonical_sqlite_druid_feral",
        "gear_stats": {
            "strength": 56.0,
            "agility": 52.0,
            "stamina": 53.0,
            "armor": 530.0,
            "weapon_dps": 20.44,
            "weapon_speed": 3.4,
            "slots": {"weapon": {"name": "Hammerbone"}},
        },
        "rotation": "Claw to 5 CP → Rip",
        "rotation_steps": [
            {"label": "Claw to 5 CP", "icon": {"icon_verified": True}},
            {"label": "Rip", "icon": {"icon_verified": True}},
        ],
        "data_sources": ["endpoint_path", "spec_matrix"],
    }


def test_druid_cat_legacy_row_projects_to_generic_gameplay_collections():
    record = DecisionRecord.from_legacy_route_row(
        class_name="druid", target_level=20, route_name="unconstrained", row=_cat_row()
    )
    data = record.as_dict()

    assert [a["id"] for a in data["actors"]] == ["player"]
    actor = data["actors"][0]
    assert actor["kind"] == "player"
    assert actor["active_mode"] == "cat"
    assert actor["stats"]["weapon_dps"] == 20.44

    assert [r["id"] for r in data["resources"]] == ["energy", "combo_points"]
    assert data["resources"][0]["scope"] == "actor"
    assert data["resources"][1]["scope"] == "target"

    assert [m["id"] for m in data["modes"]] == ["cat"]
    assert data["modes"][0]["active"] is True

    assert [a["label"] for a in data["actions"]] == ["Claw to 5 CP", "Rip"]
    assert data["policy"]["kind"] == "priority_policy"
    assert [x["action_id"] for x in data["policy"]["priority"]] == [
        data["actions"][0]["id"], data["actions"][1]["id"]
    ]
    assert data["policy"]["structure_status"] == "projected_from_legacy_rotation"


def test_listener_compatibility_row_carries_same_generic_decision_content():
    record = DecisionRecord.from_legacy_route_row(
        class_name="druid", target_level=20, route_name="unconstrained", row=_cat_row()
    )
    compat = record.legacy_route_row()
    content = compat["decision_content"]
    assert content["actors"] == record.as_dict()["actors"]
    assert content["resources"] == record.as_dict()["resources"]
    assert content["actions"] == record.as_dict()["actions"]
    assert content["modes"] == record.as_dict()["modes"]
    assert content["policy"] == record.as_dict()["policy"]


def test_non_druid_projection_fails_closed_instead_of_guessing_collections():
    row = dict(_cat_row())
    row["combat_profile"] = "retribution"
    record = DecisionRecord.from_legacy_route_row(
        class_name="paladin", target_level=20, route_name="unconstrained", row=row
    )
    assert record.as_dict()["actors"] == []
    assert record.as_dict()["resources"] == []
    assert record.as_dict()["actions"] == []
    assert record.as_dict()["modes"] == []
    assert record.as_dict()["policy"]["structure_status"] == "not_projected"


def test_listener_renders_generic_decision_model_from_backend_neutral_content():
    from src import listener

    html = listener.DECISIONS_HTML
    assert "function genericDecisionModelHtml(row)" in html
    assert "row?.decision_content" in html
    assert "Generic gameplay model" in html
