from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from src.rulesets.forever.data.catalogue import DEFAULT_SNAPSHOT_ID, FIXTURE_ROOT, ForeverSourceCatalogue
from src.rulesets.forever.data.provenance import file_sha256
from src.rulesets.forever.classes import paladin as pala
from src.rulesets.forever.classes.paladin import mechanics


def _copy_snapshot(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    shutil.copytree(FIXTURE_ROOT / DEFAULT_SNAPSHOT_ID, root / DEFAULT_SNAPSHOT_ID)
    return root


def _rehash(root: Path) -> None:
    snap = root / DEFAULT_SNAPSHOT_ID
    manifest_path = snap / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["file_sha256"] = {
        rel: file_sha256(snap / rel) for rel in manifest["file_sha256"]
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _gear(level: int):
    return next(g for g in pala.archetypes(level) if g.name == "1h_shield_normal")


def test_paladin_base_mana_is_pinned_source_data_not_class_local_fallback():
    cat = ForeverSourceCatalogue()
    assert cat.class_level_stat("paladin", 1)["base_mana"] == 59
    assert cat.class_level_stat("paladin", 20)["base_mana"] == 412
    assert cat.class_level_stat("paladin", 60)["base_mana"] == 1512
    source = cat.class_level_stats_source()
    assert source["provider"] == "cmangos"
    assert source["source"]["commit"] == "8ec338a1704e7dcb1c0213eb7ed58f9231ade40f"
    assert source["source"]["blob_sha"] == "bc3573839e6134f38211420ee75ade1fe09f4d9d"


def test_judgement_percentage_cost_consumes_pinned_base_mana():
    focus = mechanics._base_damage(20, pala.Talents(), _gear(20), "protection")
    assert focus["judgement_cost"] == pytest.approx(0.06 * 412.0)


def test_mutating_pinned_base_mana_changes_runtime_judgement_cost(tmp_path, monkeypatch):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "shared" / "class_level_stats.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    row = next(x for x in payload["classes"]["paladin"]["rows"] if x["level"] == 20)
    row["base_mana"] = 1000
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rehash(root)

    mutated = ForeverSourceCatalogue(fixture_root=root)
    monkeypatch.setattr(mechanics, "default_catalogue", lambda: mutated)
    focus = mechanics._base_damage(20, pala.Talents(), _gear(20), "protection")
    assert focus["judgement_cost"] == pytest.approx(60.0)


def test_closed_paladin_base_mana_fallback_gap_is_absent_from_fidelity_inventory():
    from src.rulesets.forever.fidelity import issues_for

    ids = {x.issue_id for x in issues_for("paladin")}
    assert "paladin.base_mana_fallback" not in ids
