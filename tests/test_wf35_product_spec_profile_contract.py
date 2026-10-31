"""#35: product-defined spec constraints are not invented Forever game rules.

These focused tests exercise the real P2 provider helpers. They do not assert
that the entire rank denominator or the live P2 gate has passed.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import wf_gate_p2_live as p2


ROOT = Path(__file__).resolve().parents[1]


def _ir():
    def talent(name, tree, row):
        return SimpleNamespace(id=name, tree_key=tree, metadata={"row": row})
    return SimpleNamespace(
        talents=(talent("balance_capstone", "balance", 6),
                 talent("restoration_filler", "restoration", 0)),
        actor=SimpleNamespace(metadata={"class_key": "druid"}),
        provenance={},
    )


def test_committed_druid_profile_is_explicit_product_contract():
    rule = p2._load_product_spec_profile(ROOT, "druid", 60, "balance",
                                         source_sha256="a" * 64)
    assert rule["authority_kind"] == "PRODUCT_PROFILE_CONSTRAINT"
    assert rule["constraint_kind"] == "minimum_tree_points"
    assert rule["minimum_points"] == 31
    assert rule["source_db_sha256"] == "a" * 64
    assert rule["tree_key"] == "balance"
    assert "source_url" not in rule
    assert p2._load_product_spec_profile(ROOT, "mage", 60, "balance",
                                         source_sha256="a" * 64) is None


def test_product_profile_is_legal_full_point_frontier_not_external_url(monkeypatch):
    monkeypatch.setattr(p2, "available_talent_points",
                        lambda level, bonus_talent_points: 51)
    observed = []
    monkeypatch.setattr(p2, "validate_talent_selection",
                        lambda ir, allocation, **kwargs: observed.append(dict(allocation)))
    rule = p2._load_product_spec_profile(ROOT, "druid", 60, "balance",
                                         source_sha256="a" * 64)
    def frontier(ir, starts, *, tree_key, minimum_points, level,
                 bonus_talent_points, max_frontier):
        assert (tree_key, minimum_points, level) == ("balance", 31, 60)
        return ([{"balance_capstone": 31, "restoration_filler": 20}],
                {"kind": "test_frontier"})
    builds, evidence = p2._source_spec_profile(
        _ir(), "balance", level=60, bonus=0, step=5,
        source_sha256="a" * 64, frontier_builder=frontier, profile_rule=rule)
    assert len(builds) == len(observed) == 1
    assert evidence["source_spec_profile_verified"] is True
    assert evidence["source_spec_profile_kind"] == "PRODUCT_PROFILE_CONSTRAINT"
    assert evidence["source_spec_profile_authority"].endswith("p2_spec_profiles.json")
    assert evidence["source_spec_required_points"] == 31


@pytest.mark.parametrize("field,value", [
    ("schema_version", 99),
    ("authority", "FOREVER_GAME_MECHANIC"),
])
def test_wrong_contract_schema_fails_closed(tmp_path, field, value):
    config = ROOT / "config/validation/p2_spec_profiles.json"
    data = json.loads(config.read_text())
    data[field] = value
    target = tmp_path / "config/validation/p2_spec_profiles.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="P2_PRODUCT_PROFILE_"):
        p2._load_product_spec_profile(tmp_path, "druid", 60, "balance",
                                      source_sha256="a" * 64)


def test_duplicate_product_profile_fails_closed(tmp_path):
    data = json.loads((ROOT / "config/validation/p2_spec_profiles.json").read_text())
    data["profiles"].append(dict(data["profiles"][0]))
    target = tmp_path / "config/validation/p2_spec_profiles.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="P2_PRODUCT_PROFILE_DUPLICATE"):
        p2._load_product_spec_profile(tmp_path, "druid", 60, "balance",
                                      source_sha256="a" * 64)


def test_source_hash_is_required_not_invented():
    with pytest.raises(ValueError, match="P2_PRODUCT_PROFILE_SOURCE_SHA"):
        p2._load_product_spec_profile(ROOT, "druid", 60, "balance",
                                      source_sha256="not-a-hash")


def test_product_constraint_cannot_bypass_canonical_prerequisites(monkeypatch):
    monkeypatch.setattr(p2, "available_talent_points",
                        lambda level, bonus_talent_points: 51)
    def illegal_allocation(ir, allocation, **kwargs):
        raise ValueError("missing_canonical_prerequisite")
    monkeypatch.setattr(p2, "validate_talent_selection", illegal_allocation)
    rule = p2._load_product_spec_profile(ROOT, "druid", 60, "balance",
                                         source_sha256="a" * 64)
    def frontier(ir, starts, **kwargs):
        return ([{"balance_capstone": 31, "restoration_filler": 20}], {})
    with pytest.raises(ValueError, match="SOURCE_SPEC_FRONTIER_ILLEGAL_ALLOCATION:missing_canonical_prerequisite"):
        p2._source_spec_profile(
            _ir(), "balance", level=60, bonus=0, step=5,
            source_sha256="a" * 64, frontier_builder=frontier, profile_rule=rule)
