from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import game_context, listener
from src.v2 import decision_dashboard as dd, spec_matrix
from src.v2.talentsforever_compare import (
    TalentsForeverComparisonUnavailable,
    _select_optimizer_row,
)


FERAL_RANKS = {
    "ferocity": 5,
    "heart_of_the_wild": 5,
    "feral_swiftness": 2,
    "thick_hide": 1,
    "sharpened_claws": 2,
    "predatory_strikes": 3,
    "blood_frenzy": 2,
    "leader_of_the_pack": 1,
}
FERAL_ALLOCATION = (
    "balance(0) / feral(21)[ferocity:5,heart_of_the_wild:5,feral_swiftness:2,"
    "thick_hide:1,sharpened_claws:2,predatory_strikes:3,blood_frenzy:2,leader_of_the_pack:1] / restoration(0)"
)


def _matrix_row(profile: str, mph: float):
    return {
        "level": 30,
        "talent_ranks": dict(FERAL_RANKS),
        "tree_points": {"balance": 0, "feral": 21, "restoration": 0},
        "allocation": FERAL_ALLOCATION,
        "talent_family": "feral",
        "combat_profile": profile,
        "gear": f"canonical_sqlite_druid_{profile if profile != 'cat' else 'feral'}",
        "gear_stats": {"slots": {"weapon": {"item_id": 1}}},
        "pull_size": 1 if profile == "cat" else 3,
        "mobs_per_hour": mph,
        "score_s_per_100": 360000.0 / mph,
        "stat_weights_contract_ok": True,
        "stat_weights": {"stats": {"strength": {"status": "measured", "seconds_saved_per_100_per_point": 1.0}}},
    }


def _endpoint(profile: str = "bear") -> dict:
    row = _matrix_row(profile, 249.5 if profile == "bear" else 203.8)
    return {
        "targets": {
            "30": {
                "status": "available",
                "routes": {
                    "feral_cat": {
                        "status": "available",
                        "path": {"steps": [row]},
                    }
                },
            }
        }
    }


def test_endpoint_only_bear_state_cannot_be_published_as_feral_cat():
    routes = dd._canonical_route_rows("druid", _endpoint("bear"), {})
    cat = routes["30"]["routes"]["feral_cat"]
    assert cat["status"] == "route_identity_invalid"
    assert cat["route_identity_complete"] is False
    row = cat["rows"][0]
    assert row["combat_profile"] == "bear"
    assert row["route_identity_contract_ok"] is False
    assert row["route_identity"]["expected_publication_profile"] == "cat"
    assert "requires combat_profile=cat" in row["route_identity"]["reason"]
    assert not row.get("stat_weights")
    assert row["stat_weights_contract_ok"] is False


def test_route_specific_cat_matrix_makes_feral_cat_canonical_and_selectable():
    matrix = {
        "matrices": {
            "30:feral_cat": {
                "status": "available",
                "rows": [_matrix_row("cat", 203.8)],
            }
        }
    }
    routes = dd._canonical_route_rows("druid", _endpoint("bear"), matrix)
    cat = routes["30"]["routes"]["feral_cat"]
    assert cat["status"] == "available"
    assert cat["route_identity_complete"] is True
    row = cat["rows"][0]
    assert row["combat_profile"] == "cat"
    assert row["gear"] == "canonical_sqlite_druid_feral"
    assert row["pull_size"] == 1
    assert row["mobs_per_hour"] == 203.8
    assert row["score_s_per_100"] == 360000.0 / 203.8
    assert row["route_identity_contract_ok"] is True


def test_compare_to_build_uses_validated_canonical_route_row_not_raw_matrix():
    canonical = _matrix_row("cat", 203.8)
    canonical["route_identity_contract_ok"] = True
    raw_matrix = _matrix_row("bear", 249.5)
    decisions = {
        "route_rows": {"druid": {"30": {"routes": {"feral_cat": {"status": "available", "rows": [canonical]}}}}},
        "spec_matrix": {"druid": {"matrices": {"30:feral_cat": {"status": "available", "rows": [raw_matrix]}}}},
    }
    row = _select_optimizer_row(decisions, "druid", 30, "feral_cat", 30)
    assert row["combat_profile"] == "cat"
    assert row["gear"] == "canonical_sqlite_druid_feral"
    assert row["mobs_per_hour"] == 203.8


def test_compare_to_build_refuses_invalid_canonical_route_even_if_matrix_exists():
    invalid = _matrix_row("bear", 249.5)
    decisions = {
        "route_rows": {"druid": {"30": {"routes": {"feral_cat": {"status": "route_identity_invalid", "rows": [invalid]}}}}},
        "spec_matrix": {"druid": {"matrices": {"30:feral_cat": {"status": "available", "rows": [_matrix_row("cat", 203.8)]}}}},
    }
    with pytest.raises(TalentsForeverComparisonUnavailable, match="not selectable: route_identity_invalid"):
        _select_optimizer_row(decisions, "druid", 30, "feral_cat", 30)


def test_listener_prefers_validated_canonical_rows_and_labels_regret_honestly():
    html = listener.DECISIONS_HTML
    assert "function routeRowsFor(cls,target,route)" in html
    assert "if(canonicalRoute)return canonicalRoute.status==='available'?(canonicalRoute.rows||[]):[]" in html
    assert "Constrained regret" in html
    assert "route-specific scorer at L${target}" in html
    assert "Terminal throughput/profile uses the route-specific fixed-route scorer when available." in html


def test_spec_matrix_generate_honors_service_state_base(tmp_path, monkeypatch):
    # Regression: service attempts set WOW_SIM_STATE_BASE=<attempt>/state.  The
    # old spec-matrix generator ignored that and wrote/read repo-root state,
    # yielding zero matrices in otherwise successful Druid jobs.
    project_root = tmp_path / "repo"
    project_root.mkdir()
    state_base = tmp_path / "attempt" / "state"
    decision_root = state_base / "decisions" / "forever"
    decision_root.mkdir(parents=True)
    endpoint = {
        "schema_version": 2,
        "ruleset": "forever",
        "classes": {
            "druid": {
                "definitions": {},
                "targets": {},
            }
        },
    }
    (decision_root / "endpoint_paths.json").write_text(json.dumps(endpoint), encoding="utf-8")
    monkeypatch.setenv(game_context.STATE_BASE_ENV, str(state_base))

    # Empty targets are enough to prove path resolution: output must be written
    # into the attempt state base rather than <project_root>/state.
    path, payload = spec_matrix.generate_all("druid", [], project_root=project_root)
    assert path == decision_root / "spec_matrix.json"
    assert path.exists()
    assert not (project_root / "state" / "decisions" / "forever" / "spec_matrix.json").exists()
    assert payload["class"] == "druid"


def test_stored_reference_defaults_to_current_route_family_instead_of_unrelated_build():
    html = listener.DECISIONS_HTML
    assert "function referenceBuildTypeForSelection()" in html
    assert "state.route==='feral_cat'||state.route==='feral_bear'" in html
    assert "refs.find(r=>String(r.build_type||'').toLowerCase()===wantedType)" in html
    assert "Cross-family reference:" in html
