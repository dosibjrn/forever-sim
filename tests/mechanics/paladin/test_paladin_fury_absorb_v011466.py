from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from src.rulesets.forever.data.catalogue import DEFAULT_SNAPSHOT_ID, FIXTURE_ROOT, ForeverSourceCatalogue
from src.rulesets.forever.data.provenance import file_sha256
from src.rulesets.forever.data.rules import SourceRuleInterpreter, default_rules
from src.rulesets.forever.classes import paladin as pala
from src.rulesets.forever.classes.paladin import mechanics
from src.rulesets.forever.classes.paladin.survival import replacing_absorb_dynamics


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


def test_fury_absorb_fraction_is_source_owned():
    assert default_rules().spell_family_value(
        "paladin", "seal_of_fury", "damage_absorb_fraction", target="shield"
    ) == pytest.approx(0.5)


def test_replacing_absorb_exactly_credits_partial_consumption_before_refresh():
    # g=h=1 => next event is grant/hit with equal probability. A=15 and hit=10
    # needs two hits to break. Steady states: fresh shield 0.5, 5 hp left 0.25,
    # broken 0.25. Incoming hits therefore absorb 10*.5 + 5*.25 = 6.25 / sec.
    row = replacing_absorb_dynamics(1.0, 1.0, 15.0, 10.0)
    assert row["hits_needed"] == 2
    assert row["full_break_probability"] == pytest.approx(0.25)
    assert row["break_rate"] == pytest.approx(0.25)
    assert row["absorb_per_s"] == pytest.approx(6.25)


def test_replacing_absorb_single_hit_shield_matches_competing_event_formula():
    row = replacing_absorb_dynamics(2.0, 3.0, 5.0, 10.0)
    # Shield exists with probability g/(g+h)=0.4; each incoming hit consumes all 5.
    assert row["hits_needed"] == 1
    assert row["break_rate"] == pytest.approx(1.2)
    assert row["absorb_per_s"] == pytest.approx(6.0)


def test_mutating_fury_absorb_fraction_changes_runtime_shield(tmp_path, monkeypatch):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "paladin" / "spells.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rank = next(x for x in rows if x["family_key"] == "seal_of_fury")
    effect = next(e for e in rank["effects"] if e["normalized_kind"] == "damage_absorb_fraction")
    effect["coefficient"] = 0.9
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rehash(root)

    mutated = SourceRuleInterpreter(ForeverSourceCatalogue(fixture_root=root))
    monkeypatch.setattr(mechanics, "default_rules", lambda: mutated)
    gear = _gear(60)
    focus = mechanics._base_damage(60, pala.Talents(), gear, "protection")
    incoming = mechanics._incoming(60, pala.Talents(), gear, 1, "devotion", focus)
    assert focus["seal_hit"] > 0
    assert incoming["fury_absorb_per_shield"] == pytest.approx(focus["seal_hit"] * 0.9)


def test_fury_semantic_uncertainty_is_explicitly_not_probeable_not_fast_event_drift():
    from src.rulesets.forever.fidelity import issues_for

    row = next(x for x in issues_for("paladin") if x.issue_id == "paladin.seal_of_fury_absorb_replacement")
    assert row.status == "not_probeable"
    assert row.severity == "low"
    assert "share one explicit replacement interpretation" in row.summary
