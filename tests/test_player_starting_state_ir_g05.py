from __future__ import annotations

import json
from pathlib import Path
import shutil

from src.game.data.forever import build_game_ir_slice
from src.rulesets.forever.data.catalogue import DEFAULT_SNAPSHOT_ID, FIXTURE_ROOT, ForeverSourceCatalogue
from src.rulesets.forever.data.provenance import file_sha256
from src.rulesets.forever.shared.base_stats import base_primary_stats
from src.v2.generic_backend import build_partial_generic_records


def _copy_snapshot(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    shutil.copytree(FIXTURE_ROOT / DEFAULT_SNAPSHOT_ID, root / DEFAULT_SNAPSHOT_ID)
    return root


def _rehash(root: Path) -> None:
    snap = root / DEFAULT_SNAPSHOT_ID
    manifest_path = snap / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["file_sha256"] = {rel: file_sha256(snap / rel) for rel in manifest["file_sha256"]}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_druid_base_mana_is_pinned_source_data():
    cat = ForeverSourceCatalogue()
    assert cat.class_level_stat("druid", 1)["base_mana"] == 17
    assert cat.class_level_stat("druid", 20)["base_mana"] == 354
    assert cat.class_level_stat("druid", 30)["base_mana"] == 614
    assert cat.class_level_stat("druid", 60)["base_mana"] == 1244
    source = cat.class_level_stats_source()
    assert source["provider"] == "cmangos"
    assert source["source"]["commit"] == "8ec338a1704e7dcb1c0213eb7ed58f9231ade40f"


def test_l20_tauren_druid_primary_stats_and_mana_starting_state_are_ir_authority():
    assert base_primary_stats("druid", 20, race="tauren") == {
        "strength": 30,
        "agility": 24,
        "stamina": 38,
        "intellect": 36,
        "spirit": 37,
    }
    ir = build_game_ir_slice(class_key="druid", level=20)
    assert ir is not None
    assert ir.actor.state_status == "source_backed_starting_state"
    assert ir.actor.base_stats == {
        "strength": 30,
        "agility": 24,
        "stamina": 38,
        "intellect": 36,
        "spirit": 37,
    }
    mana = ir.resources[0]
    assert mana.id == "mana"
    assert mana.state_status == "source_backed_starting_state"
    assert mana.metadata["base_mana"] == 354.0
    assert mana.metadata["base_intellect"] == 36.0
    assert mana.metadata["intellect_mana_bonus"] == 260.0
    assert mana.initial_amount == 614.0
    assert mana.capacity == 614.0
    assert mana.metadata["gear_included"] is False
    assert mana.metadata["talents_included"] is False


def test_mutating_pinned_druid_base_mana_changes_generic_ir_capacity(tmp_path, monkeypatch):
    from src.game.data.forever import druid as provider

    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "shared" / "class_level_stats.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    row = next(x for x in payload["classes"]["druid"]["rows"] if x["level"] == 20)
    row["base_mana"] = 1000
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rehash(root)

    mutated = ForeverSourceCatalogue(fixture_root=root)
    monkeypatch.setattr(provider, "default_catalogue", lambda: mutated)
    ir = provider.build_source_slice(20)
    assert ir.resources[0].metadata["base_mana"] == 1000.0
    assert ir.resources[0].capacity == 1260.0


def test_generic_backend_consumes_ir_starting_state_without_legacy_fallback():
    druid, mage = build_partial_generic_records(class_names=("druid", "mage"), selected_level=20)
    assert druid.capability["actor_starting_state"] is True
    assert druid.capability["resource_starting_state"] is True
    assert druid.capability["status"] == "combat_recovery_evaluation"
    assert druid.capability["recovery_evaluation"] is True
    assert druid.capability["combat_evaluation"] is True
    assert druid.capability["optimization_ready"] is False
    assert druid.capability["event_runtime"] is True
    source_ir = druid.provenance["source_game_ir"]
    assert source_ir["actor"]["base_stats"]["intellect"] == 36.0
    assert source_ir["resources"][0]["capacity"] == 614.0
    assert source_ir["resources"][0]["initial_amount"] == 614.0
    assert druid.actors[0]["base_stats"]["intellect"] == 64.0
    assert druid.resources[0]["capacity"] == 1034.0
    assert druid.provenance["legacy_fallback"] is False
    assert druid.objective["mobs_per_hour"] is None

    assert mage.capability["actor_starting_state"] is False
    assert mage.capability["resource_starting_state"] is False
    assert mage.actors == ()
    assert mage.resources == ()


def test_listener_renders_ir_starting_state_without_class_specific_renderer():
    from src import listener

    html = listener.DECISIONS_HTML
    assert "function genericActorStateSummary(a)" in html
    assert "function genericResourceStateSummary(r)" in html
    assert "IR starting state" in html
    start = html.index("function genericActorStateSummary(a)")
    end = html.index("function genericModeSummary", start)
    renderer = html[start:end]
    assert "druid" not in renderer.lower()
    assert "tauren" not in renderer.lower()
    assert "wrath" not in renderer.lower()
