from __future__ import annotations

from pathlib import Path

import pytest

from src.class_registry import (
    ClassRegistryError,
    adapter,
    class_names,
    get_definition,
    validate_registry,
)
from src.rulesets.forever.data.audit import audit_catalogue
from src.rulesets.forever.data.catalogue import ForeverSourceCatalogue
from src.v2.decision_dashboard import build_decision_payload
from src.v2.endpoint_paths import route_definitions


def test_registry_validates_and_preserves_existing_default_comparison_set():
    validate_registry()
    assert class_names("forever") == ("druid", "hunter", "mage", "paladin", "warrior")
    assert set(class_names("forever", comparison_default=True)) == {"mage", "paladin", "druid"}
    warrior = get_definition("forever", "warrior")
    assert warrior.proof_only is True
    assert warrior.tree_names == ("arms", "fury", "protection")
    assert warrior.capabilities.decision_artifacts is True
    assert warrior.capabilities.replay is False


def test_missing_capability_fails_clearly_instead_of_silent_fallback():
    with pytest.raises(ClassRegistryError, match=r"forever-warrior lacks required capability: replay"):
        adapter("forever", "warrior").replay(20, [])


def test_warrior_source_snapshot_is_canonical_and_audited():
    ad = adapter("forever", "warrior")
    hs = ad.source_spell("heroic_strike", level=20)
    assert hs.spell_id == 78
    assert hs.resource_type == "rage"
    assert hs.resource_cost["flat"] == 15
    assert hs.source_ref.provider == "wowhead"
    assert ad.source_talent("deflection").source_refs[0].entity_id == 16462
    assert ad.source_talent("improved_heroic_strike").source_refs[0].entity_id == 12664

    report = audit_catalogue(ForeverSourceCatalogue())
    assert report["ok"], report["issues"]
    assert report["classes"]["warrior"]["coverage"]["talent_status_pct"] == 100.0
    assert report["classes"]["warrior"]["coverage"]["spell_status_pct"] == 100.0


def test_warrior_legality_score_and_stat_contract_use_standard_adapter():
    ad = adapter("forever", "warrior")
    engine = ad.engine()
    t = engine.Talents()
    assert engine.legal_add(t, "improved_heroic_strike")
    for _ in range(3):
        t = engine.add_point(t, "improved_heroic_strike")
    assert not engine.legal_add(t, "improved_heroic_strike")
    for _ in range(5):
        t = engine.add_point(t, "deflection")
    for _ in range(3):
        t = engine.add_point(t, "improved_rend")
    assert t.points() == 11
    assert engine.tree_points(t, "arms") == 11
    assert "arms(11)" in engine.final_allocation(t)

    base = ad.score(20, engine.Talents(), profile="arms")
    hs = ad.score(20, engine.Talents(improved_heroic_strike=3), profile="arms")
    defensive = ad.score(20, engine.Talents(deflection=5), profile="arms")
    identity_only = ad.score(20, engine.Talents(improved_rend=3), profile="arms")
    assert base["proof_inputs"]["heroic_strike_spell_id"] == 78
    assert hs["proof_inputs"]["heroic_strike_rage_cost"] == 12.0
    assert hs["total_s"] < base["total_s"]
    assert defensive["total_s"] < base["total_s"]
    # M45 imports Improved Rend identity/legality only; no fabricated effect.
    assert identity_only["total_s"] == pytest.approx(base["total_s"])

    weights = ad.stat_weights(20, engine.Talents(), baseline=base, profile="arms")
    assert weights["schema_version"] == 3
    assert weights["stats"]["weapon_dps"]["status"] == "measured"
    assert weights["stats"]["stamina"]["status"] == "measured"
    assert weights["stats"]["defense"]["status"] == "not_modeled"


def test_registry_drives_routes_and_decision_metadata_without_proof_class_branch(tmp_path):
    routes = route_definitions("warrior")
    assert set(routes) == {"arms"}
    assert routes["arms"]["kind"] == "tree_points"
    payload = build_decision_payload(tmp_path, selected_level=20)
    meta = payload["class_metadata"]["warrior"]
    assert meta["display_name"] == "Warrior"
    assert meta["tree_names"] == ["arms", "fury", "protection"]
    assert meta["proof_only"] is True
    assert payload["coverage"]["warrior"]["levels"] == []

    # The thin proof must not require another class-name branch in shared paths.
    shared = [
        "src/game_context.py",
        "src/engine_registry.py",
        "src/listener.py",
        "src/v2/runner.py",
        "src/v2/endpoint_paths.py",
        "src/v2/decision_dashboard.py",
        "src/v2/class_comparison.py",
        "src/v2/spec_matrix.py",
        "src/v2/dual_spec.py",
        "src/v2/constrained_routes.py",
    ]
    for rel in shared:
        assert "warrior" not in Path(rel).read_text(encoding="utf-8").lower(), rel
