from src.class_registry import get_definition
from src.v2.endpoint_paths import analyze_frontier
from src.v2.spec_matrix import build_matrix
from src.rulesets.forever.classes.druid import engine as druid


def _feral_candidate():
    ranks = {name: 0 for name in druid.Talents.__dataclass_fields__}
    # Use a real reachable low-level Feral allocation if available in this build.
    for name in ("ferocity", "feral_aggression", "thick_hide", "feral_instinct"):
        if name in ranks:
            ranks[name] = min(5, getattr(druid, "TALENT_RULES", {}).get(name, {}).get("max_rank", 5) if isinstance(getattr(druid, "TALENT_RULES", {}).get(name), dict) else 5)
            break
    t = druid.Talents(**ranks)
    return {
        "allocation": druid.final_allocation(t),
        "talent_ranks": ranks,
        "tree_points": {tree: druid.tree_points(t, tree) for tree in ("balance","feral","restoration")},
        "talent_family": "feral",
        "combat_profile": "cat",
        "cumulative_objective_s": 1000.0,
        "score_s_per_100": 1000.0,
        "mobs_per_hour": 180.0,
        "steps": [{
            "level": 20,
            "allocation": druid.final_allocation(t),
            "talent_ranks": ranks,
            "tree_points": {tree: druid.tree_points(t, tree) for tree in ("balance","feral","restoration")},
            "talent_family": "feral",
            "combat_profile": "cat",
            "mobs_per_hour": 180.0,
        }],
    }


def test_druid_registry_publishes_separate_cat_and_bear_routes():
    routes = get_definition("forever", "druid").route_definitions
    assert "feral" not in routes
    assert routes["feral_cat"]["label"] == "Feral · Cat"
    assert routes["feral_cat"]["score_profile"] == "feral"
    assert routes["feral_bear"]["label"] == "Feral · Bear"
    assert routes["feral_bear"]["score_profile"] == "bear"


def test_same_preserved_feral_talent_path_makes_both_routes_available():
    candidate = _feral_candidate()
    # Force enough tree points for the endpoint constraint without requiring the
    # frontier to preserve both combat-profile variants separately.
    candidate["tree_points"] = {"balance": 0, "feral": 11, "restoration": 0}
    candidate["steps"][0]["tree_points"] = dict(candidate["tree_points"])
    frontier = {"class": "druid", "verified_level_cap": 60, "levels": [{"level": 20, "candidates": [candidate]}]}
    routes, _ = analyze_frontier(frontier, targets=[20])
    rows = routes["targets"]["20"]["routes"]
    assert rows["feral_cat"]["status"] == "available"
    assert rows["feral_bear"]["status"] == "available"
    assert rows["feral_cat"]["path"]["allocation"] == rows["feral_bear"]["path"]["allocation"]


def test_matrix_forces_cat_vs_bear_profile_on_same_talents(monkeypatch):
    ranks = {name: 0 for name in druid.Talents.__dataclass_fields__}
    route_path = {"steps": [{"level": 20, "talent_ranks": ranks, "talent_family": "feral"}]}
    calls = []
    def fake_score(level, talents, profile="all"):
        calls.append(profile)
        return {"total_s": 2000.0 if profile == "bear" else 1000.0, "mobs_per_hour": 180.0 if profile == "bear" else 360.0,
                "profile": "bear" if profile == "bear" else "cat", "combat_profile": "bear" if profile == "bear" else "cat",
                "gear": "g", "gear_stats": {}, "pull_size": 1, "rotation": profile, "policy": profile,
                "kill_s": 800.0, "recovery_s": 100.0, "travel_s": 100.0}
    monkeypatch.setattr(druid, "experimental_level_score", fake_score)
    monkeypatch.setattr(druid, "marginal_stat_weights", lambda *a, **k: {"strength": 1.0})
    cat = build_matrix(druid, route_path, class_name="druid", route="feral_cat", target=20, cache={}, score_profile="feral", publication_profile="cat")
    bear = build_matrix(druid, route_path, class_name="druid", route="feral_bear", target=20, cache={}, score_profile="bear", publication_profile="bear")
    assert cat["rows"][0]["combat_profile"] == "cat"
    assert bear["rows"][0]["combat_profile"] == "bear"
    assert cat["rows"][0]["mobs_per_hour"] != bear["rows"][0]["mobs_per_hour"]
    assert calls == ["feral", "bear"]


def test_dashboard_exposes_human_route_labels_and_listener_hides_stale_declared_artifacts(tmp_path):
    from src.v2 import decision_dashboard as dd
    payload = dd.build_decision_payload(project_root=tmp_path, selected_level=20)
    meta = payload["class_metadata"]["druid"]
    assert meta["declared_routes"] == ["balance", "feral_cat", "feral_bear", "restoration"]
    assert meta["route_labels"]["feral_cat"] == "Feral · Cat"
    assert meta["route_labels"]["feral_bear"] == "Feral · Bear"
    html = __import__("src.listener", fromlist=["DECISIONS_HTML"]).DECISIONS_HTML
    assert "...(declared.length?declared:[...artifact,...matrix])" in html
    assert "routeLabel(state.cls,x)" in html
