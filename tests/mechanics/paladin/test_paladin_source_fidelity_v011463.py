from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from src.rulesets.forever.data.catalogue import (
    DEFAULT_SNAPSHOT_ID,
    FIXTURE_ROOT,
    ForeverSourceCatalogue,
)
from src.rulesets.forever.data.provenance import file_sha256
from src.rulesets.forever.data.rules import SourceRuleInterpreter, default_rules
from src.rulesets.forever.classes import paladin as pala
from src.rulesets.forever.classes.paladin import event_replay, mechanics, survival


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


def _gear(level: int, name: str):
    return next(g for g in pala.archetypes(level) if g.name == name)


def test_m46_paladin_refresh_is_the_default_snapshot_and_resolves_anticipation():
    assert DEFAULT_SNAPSHOT_ID == "forever_2026_09_26"
    cat = ForeverSourceCatalogue()
    talent = cat.talent("paladin", "anticipation")
    assert talent.canonical_spell_id == 20096
    assert [r.trait_id for r in talent.rank_records] == [135161] * 5
    rules = default_rules()
    assert [
        rules.talent_value("paladin", "anticipation", rank, "skill_bonus", target="defense")
        for rank in range(1, 6)
    ] == [4.0, 8.0, 12.0, 16.0, 20.0]


def test_mutating_anticipation_source_effect_changes_runtime_defense(tmp_path, monkeypatch):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "paladin" / "talents.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    talent = next(x for x in rows if x["local_key"] == "anticipation")
    rank2 = next(x for x in talent["rank_records"] if x["rank"] == 2)
    effect = next(x for x in rank2["effects"] if x["normalized_kind"] == "skill_bonus")
    effect["base_value"] = 40.0
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rehash(root)

    mutated = SourceRuleInterpreter(ForeverSourceCatalogue(fixture_root=root))
    monkeypatch.setattr(survival, "default_rules", lambda: mutated)

    gear = _gear(40, "1h_shield_normal")
    talents = pala.Talents(anticipation=2)
    focus = mechanics._base_damage(40, talents, gear, "protection")
    incoming = mechanics._incoming(40, talents, gear, 1, "devotion", focus)
    assert incoming["defense_skill_bonus"] == pytest.approx(40.0 + gear.defense_bonus)


def test_seal_of_command_rank_ladder_and_damage_facts_are_canonical():
    cat = ForeverSourceCatalogue()
    family = cat.spell_family("paladin", "seal_of_command")
    assert [r.spell_id for r in family] == [20375, 20915, 20918, 20919, 20920]
    assert [r.required_level for r in family] == [20, 30, 40, 50, 60]
    assert [int((r.resource_cost or {})["amount"]) for r in family] == [65, 110, 140, 180, 210]
    assert [row[:2] for row in pala.SEAL_COMMAND] == [
        (20, 65.0), (30, 110.0), (40, 140.0), (50, 180.0), (60, 210.0)
    ]

    rules = default_rules()
    assert rules.spell_value("paladin", "seal_of_command", 20, "judgement_base_damage", target="judgement") == 71.0
    assert rules.spell_value("paladin", "seal_of_command", 40, "judgement_base_damage", target="judgement") == 129.0
    assert rules.spell_value("paladin", "seal_of_command", 60, "judgement_base_damage", target="judgement") == 202.5
    assert rules.spell_value("paladin", "seal_of_command", 20, "target_state_damage_multiplier", target="judgement") == 2.0


def test_mutating_soc_judgement_base_changes_runtime_damage(tmp_path, monkeypatch):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "paladin" / "spells.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rank = next(x for x in rows if x["family_key"] == "seal_of_command" and x["required_level"] == 40)
    effect = next(x for x in rank["effects"] if x["normalized_kind"] == "judgement_base_damage")
    effect["base_value"] = 999.0
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rehash(root)

    mutated = SourceRuleInterpreter(ForeverSourceCatalogue(fixture_root=root))
    monkeypatch.setattr(mechanics, "default_rules", lambda: mutated)

    gear = _gear(40, "2h_normal")
    focus = mechanics._base_damage(40, pala.Talents(seal_of_command=1), gear, "retribution")
    expected = (999.0 + gear.spell_damage_bonus * 0.429) / focus["judgement_cd"]
    assert focus["judgement_dps"] == pytest.approx(expected)


def test_soc_judgement_target_state_multiplier_is_consumed_by_event_replay():
    state = event_replay.ReplayState(t=1.0, hp=1000.0, mana=1000.0, mana_pool=1000.0, mobs=[1000.0])
    focus = {"seal_name": "Seal of Command", "judgement_stunned_multiplier": 2.0}
    state.stunned_until[0] = 5.0
    damage, multiplier, target = event_replay._judgement_damage(state, focus, 100.0)
    assert (damage, multiplier, target) == (200.0, 2.0, 0)

    state.t = 5.0
    damage, multiplier, target = event_replay._judgement_damage(state, focus, 100.0)
    assert (damage, multiplier, target) == (100.0, 1.0, 0)


def test_closed_paladin_source_gaps_are_absent_from_fidelity_inventory():
    from src.rulesets.forever.fidelity import issues_for

    ids = {x.issue_id for x in issues_for("paladin")}
    assert "paladin.anticipation_defense_rank" not in ids
    assert "paladin.soc_stunned_judgement_bonus" not in ids
