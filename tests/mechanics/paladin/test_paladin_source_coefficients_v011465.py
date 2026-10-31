from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from src.rulesets.forever.data.catalogue import DEFAULT_SNAPSHOT_ID, FIXTURE_ROOT, ForeverSourceCatalogue
from src.rulesets.forever.data.provenance import file_sha256
from src.rulesets.forever.data.rules import SourceRuleError, SourceRuleInterpreter, default_rules
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
    manifest["file_sha256"] = {rel: file_sha256(snap / rel) for rel in manifest["file_sha256"]}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _gear(level: int, name: str = "1h_shield_normal"):
    return next(g for g in pala.archetypes(level) if g.name == name)


def test_paladin_public_spell_power_coefficients_are_canonical_family_rules():
    r = default_rules()
    assert r.spell_family_value("paladin", "holy_light", "spell_power_coefficient", target="heal", school="holy") == pytest.approx(.714)
    assert r.spell_family_value("paladin", "flash_of_light", "spell_power_coefficient", target="heal", school="holy") == pytest.approx(.429)
    assert r.spell_family_value("paladin", "holy_strike", "spell_power_coefficient", target="holy_damage", school="holy") == pytest.approx(.429)
    assert r.spell_family_value("paladin", "consecration", "spell_power_coefficient", target="first4_tick", school="holy") == pytest.approx(.095)
    assert r.spell_family_value("paladin", "seal_of_righteousness", "spell_power_coefficient", target="seal_proc", school="holy") == pytest.approx(.10)
    assert r.spell_family_value("paladin", "seal_of_righteousness", "spell_power_coefficient", target="judgement", school="holy") == pytest.approx(.50)
    assert r.spell_family_value("paladin", "seal_of_fury", "spell_power_coefficient", target="seal_proc", school="holy") == pytest.approx(.10)
    assert r.spell_family_value("paladin", "seal_of_fury", "spell_power_coefficient", target="judgement", school="holy") == pytest.approx(.45)


def test_mutating_holy_light_source_coefficient_changes_runtime_heal(tmp_path, monkeypatch):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "paladin" / "spells.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rank = next(x for x in rows if x["family_key"] == "holy_light")
    effect = next(e for e in rank["effects"] if e["normalized_kind"] == "spell_power_coefficient" and e["metadata"]["target"] == "heal")
    effect["coefficient"] = 10.0
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rehash(root)

    mutated = SourceRuleInterpreter(ForeverSourceCatalogue(fixture_root=root))
    monkeypatch.setattr(mechanics, "default_rules", lambda: mutated)
    gear = _gear(60)
    gear = gear.__class__(**{**gear.__dict__, "healing_bonus": 100.0})
    row = mechanics._heal_model(60, pala.Talents(), gear, 0.0)
    assert row["healing_coeff"] == pytest.approx(10.0)


def test_mutating_holy_strike_source_coefficient_changes_runtime_damage(tmp_path, monkeypatch):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "paladin" / "spells.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    for rank in (x for x in rows if x["family_key"] == "holy_strike"):
        effect = next(e for e in rank["effects"] if e["normalized_kind"] == "spell_power_coefficient")
        effect["coefficient"] = .900
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rehash(root)

    mutated = SourceRuleInterpreter(ForeverSourceCatalogue(fixture_root=root))
    monkeypatch.setattr(mechanics, "default_rules", lambda: mutated)
    gear = _gear(60, "2h_normal")
    base = mechanics._base_damage(60, pala.Talents(), gear, "retribution")
    assert base["hs_dps"] > 0
    assert mechanics._family_sp_coeff("holy_strike", "holy_damage") == pytest.approx(.900)


def test_family_rule_fails_closed_when_captured_rank_coefficients_disagree(tmp_path):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "paladin" / "spells.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rank = next(x for x in rows if x["family_key"] == "holy_strike" and x["required_level"] == 44)
    effect = next(e for e in rank["effects"] if e["normalized_kind"] == "spell_power_coefficient")
    effect["coefficient"] = .500
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rehash(root)

    rules = SourceRuleInterpreter(ForeverSourceCatalogue(fixture_root=root))
    with pytest.raises(SourceRuleError, match="inconsistent"):
        rules.spell_family_value("paladin", "holy_strike", "spell_power_coefficient", target="holy_damage", school="holy")


def test_closed_paladin_coefficient_gap_is_absent_from_fidelity_inventory():
    from src.rulesets.forever.fidelity import issues_for

    ids = {x.issue_id for x in issues_for("paladin")}
    assert "paladin.spell_healing_coefficients" not in ids
