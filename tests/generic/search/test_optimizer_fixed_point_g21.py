from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.listener import DECISIONS_HTML

from src.v2.generic_backend import build_partial_generic_records

CANONICAL_DB_SHA = "d7d5a8519b227a761312bf4d1da56955b58184239a5a2ed7a06f84eb134dc854"

def _record():
    return build_partial_generic_records(class_names=("Druid",), selected_level=20)[0]

def test_g21_explicit_fixed_point_moves_then_converges():
    r = _record()
    fp = r.gear["fixed_point"]
    assert fp["method"] == "explicit_bounded_optimizer_fixed_point"
    assert fp["dimensions"] == ["gear", "stat_weights", "talents", "policy"]
    assert fp["converged"] is True
    assert fp["stop_reason"] == "exact_state_repeat"
    assert fp["iteration_count"] == 3
    rows = fp["iterations"]
    assert rows[0]["gear_candidate_id"] == "none"
    assert rows[0]["policy_candidate_id"] != rows[1]["policy_candidate_id"]
    assert rows[0]["stat_weights"] != rows[1]["stat_weights"]
    assert rows[1]["gear_candidate_id"] == rows[2]["gear_candidate_id"]
    assert rows[1]["state_identity"] == rows[2]["state_identity"]
    assert fp["selected_state_identity"] == rows[2]["state_identity"]

def test_g21_exact_state_identity_explicitly_covers_every_optimized_dimension():
    r = _record(); selected = r.gear["fixed_point"]["iterations"][-1]
    dims = selected["state_dimensions"]
    assert set(dims) == {"source_game_ir_sha256", "gear_candidate_id", "stat_weights", "talent_candidate_id", "policy_candidate_id"}
    assert dims["talent_candidate_id"] == "talents:improved_wrath=5"
    assert "direct_filler" in dims["policy_candidate_id"]
    assert dims["gear_candidate_id"].startswith("gear:")
    assert r.stat_weights["fixed_point_state_identity"] == selected["state_identity"]

def test_g21_selected_result_and_named_gear_preserve_g20_quality():
    r = _record()
    assert r.timing["seconds_per_mob"] == pytest.approx(11.5)
    assert r.gear["item_count"] == 15
    assert r.gear["aggregate_stats"]["spell_power"] == pytest.approx(76.0)
    assert r.talents["ranks"] == {"improved_wrath": 5}
    assert r.gear["fixed_point_complete"] is True
    assert r.capability["gear_optimization_scope"] == "explicit_bounded_optimizer_fixed_point"

def test_g21_active_build_keeps_canonical_catalogue_byte_stable():
    db=Path("data/forever/catalogue/items_2026-09-29.sqlite")
    before=hashlib.sha256(db.read_bytes()).hexdigest(); assert before==CANONICAL_DB_SHA
    _record()
    assert hashlib.sha256(db.read_bytes()).hexdigest()==before


def test_g21_listener_surfaces_fixed_point_trace_and_current_version():
    r=_record()
    assert r.capability["optimizer_fixed_point"] is True
    assert r.capability["optimizer_fixed_point_dimensions"] == ["gear", "stat_weights", "talents", "policy"]
    assert "fixed-point trace" in DECISIONS_HTML
    assert "const CURRENT_SOFTWARE_VERSION='0.11.48.153';" in DECISIONS_HTML
