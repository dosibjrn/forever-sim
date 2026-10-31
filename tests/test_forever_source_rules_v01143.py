from __future__ import annotations

import json
from pathlib import Path
import shutil

from src.rulesets.forever.data.catalogue import DEFAULT_SNAPSHOT_ID, FIXTURE_ROOT, ForeverSourceCatalogue
from src.rulesets.forever.data.provenance import file_sha256
from src.rulesets.forever.data.rules import SourceRuleInterpreter, default_rules
from src.rulesets.forever.classes.mage import engine as mage


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


def test_normalized_source_rules_have_expected_rank_values():
    r = default_rules()
    assert r.talent_value("mage", "piercing_ice", 1, "school_damage_pct", target="frost_spells", school="frost") == 0.02
    assert r.talent_value("mage", "piercing_ice", 3, "school_damage_pct", target="frost_spells", school="frost") == 0.06
    assert r.talent_value("paladin", "divine_strength", 5, "stat_pct", target="strength") == 0.10
    assert r.talent_value("paladin", "toughness", 5, "item_armor_pct", target="item_armor") == 0.10
    assert r.talent_value("druid", "improved_wrath", 5, "cast_time_delta_s", target="wrath") == -0.5
    assert r.talent_value("druid", "improved_wrath", 5, "resource_cost_pct", target="wrath") == -0.5
    assert r.spell_value("mage", "arcane_blast", 40, "spell_power_coefficient", target="arcane_blast") == 0.714


def test_mutating_pinned_piercing_ice_effect_changes_runtime_without_class_local_number(tmp_path, monkeypatch):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "mage" / "talents.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    row = next(x for x in rows if x["local_key"] == "piercing_ice")
    rank3 = next(x for x in row["rank_records"] if x["rank"] == 3)
    effect = next(x for x in rank3["effects"] if x["normalized_kind"] == "school_damage_pct")
    effect["base_value"] = 0.33
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rehash(root)

    mutated = SourceRuleInterpreter(ForeverSourceCatalogue(fixture_root=root))
    monkeypatch.setattr(mage, "default_rules", lambda: mutated)

    rank = mage.latest(mage.FROSTBOLT, 40)
    state = mage.State(t=0.0, hp=1000.0, mana=1000.0, max_mana=1000.0, distance=30.0)
    mod = mage.direct_mod(rank, mage.Talents(piercing_ice=3), state)
    assert abs(mod - 1.33) < 1e-12
