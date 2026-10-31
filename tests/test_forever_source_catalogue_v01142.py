from __future__ import annotations

import inspect
import json
from pathlib import Path
import shutil

import pytest

from src.rulesets.forever.data.catalogue import (
    DEFAULT_SNAPSHOT_ID,
    ForeverSourceCatalogue,
    SourceCatalogueError,
)
from src.rulesets.forever.data.provenance import file_sha256, wowhead_id_from_url
from src.rulesets.forever.data.schema import PARSER_VERSION, SCHEMA_VERSION, SourceRef


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "src" / "rulesets" / "forever" / "data" / "fixtures"


def _copy_snapshot(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    shutil.copytree(FIXTURE_ROOT / DEFAULT_SNAPSHOT_ID, root / DEFAULT_SNAPSHOT_ID)
    return root


def _rehash(root: Path) -> None:
    snap = root / DEFAULT_SNAPSHOT_ID
    manifest_path = snap / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["file_sha256"] = {
        rel: file_sha256(snap / rel)
        for rel in manifest["file_sha256"]
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_source_schema_round_trip_preserves_integer_spell_id():
    raw = {
        "provider": "wowhead",
        "ruleset": "forever",
        "entity_kind": "spell",
        "entity_id": 400588,
        "url": "https://www.wowhead.com/forever/spell=400588/missile-barrage",
        "retrieved_at": "2026-09-25",
        "content_fingerprint": "abc",
        "parser_version": PARSER_VERSION,
        "notes": ["talent entity"],
    }
    ref = SourceRef.from_dict(raw)
    assert isinstance(ref.entity_id, int)
    assert ref.entity_id == 400588
    assert SourceRef.from_dict(ref.to_dict()) == ref


def test_source_catalogue_identity_and_helper_separation():
    cat = ForeverSourceCatalogue()
    talent = cat.talent("mage", "missile_barrage")
    assert talent.canonical_spell_id == 400588
    assert cat.source_entity(400588)["name"] == "Missile Barrage"
    with pytest.raises(KeyError):
        cat.source_entity(401736)
    helper = [u for u in cat.unresolved("mage") if u.local_key == "missile_barrage_grant"]
    assert helper and helper[0].details["wowhead_spell_id"] == 401736
    assert helper[0].details["canonical_talent_spell_id"] == 400588


def test_source_rank_resolution_uses_canonical_rank_ids():
    cat = ForeverSourceCatalogue()
    assert cat.spell_rank("mage", "arcane_blast", level=20).spell_id == 400574
    assert cat.spell_rank("mage", "arcane_blast", level=39).spell_id == 1239696
    assert cat.spell_rank("mage", "arcane_blast", level=40).spell_id == 1239697
    assert cat.spell_rank("mage", "arcane_blast", level=60).spell_id == 1239700


def test_source_talent_identity_is_exact_wowhead_forever_url():
    cat = ForeverSourceCatalogue()
    for cls, key, entity_id in [
        ("mage", "missile_barrage", 400588),
        ("paladin", "sacred_duty", 1224697),
        ("druid", "eclipse", 408248),
    ]:
        talent = cat.talent(cls, key)
        ref = next(r for r in talent.source_refs if r.provider == "wowhead")
        assert int(ref.entity_id) == entity_id
        assert wowhead_id_from_url(ref.url) == entity_id
        assert "/forever/" in ref.url


def test_source_alias_compatibility():
    # Local compatibility keys remain the durable lookup in M42; source roster
    # aliases are normalized while the mechanics migration is still gradual.
    cat = ForeverSourceCatalogue()
    assert cat.talent("mage", "imp_frost_nova").name == "Improved Frost Nova"
    assert cat.talent("mage", "master_elements").name == "Master of Elements"


def test_unknown_source_semantics_survive_normalization():
    cat = ForeverSourceCatalogue()
    ice_lance = cat.spell_rank("mage", "ice_lance", level=20)
    assert ice_lance.effects
    effect = ice_lance.effects[0]
    assert effect.server_side_script is True
    assert effect.normalization_status == "ambiguous"
    assert "server" in (effect.raw_text_summary or "").lower()


def test_unresolved_ambiguity_is_not_auto_resolved():
    cat = ForeverSourceCatalogue()
    assert any(u.local_key == "berserk" for u in cat.unresolved("druid"))
    with pytest.raises(KeyError):
        cat.talent("druid", "berserk")


def test_duplicate_conflicting_source_id_is_rejected(tmp_path: Path):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "druid" / "spells.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0]["spell_id"] = 400574
    rows[0]["source_ref"]["entity_id"] = 400574
    rows[0]["source_ref"]["url"] = "https://www.wowhead.com/forever/spell=400574/cat-form"
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rehash(root)
    with pytest.raises(SourceCatalogueError, match="conflicting canonical ownership"):
        ForeverSourceCatalogue(fixture_root=root)


def test_snapshot_file_mutation_is_rejected_before_load(tmp_path: Path):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "mage" / "spells.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0]["spell_id"] += 1
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(SourceCatalogueError, match="fingerprint mismatch"):
        ForeverSourceCatalogue(fixture_root=root)


def test_parser_version_participates_in_snapshot_identity(tmp_path: Path):
    root = _copy_snapshot(tmp_path)
    path = root / DEFAULT_SNAPSHOT_ID / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["parser_version"] = "wrong-parser"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(SourceCatalogueError, match="parser version mismatch"):
        ForeverSourceCatalogue(fixture_root=root)


def test_runtime_catalogue_has_no_network_dependency():
    import src.rulesets.forever.data.catalogue as catalogue
    source = inspect.getsource(catalogue)
    assert "urllib" not in source
    assert "requests" not in source
    assert "httpx" not in source


def test_snapshot_schema_and_parser_versions_are_pinned():
    cat = ForeverSourceCatalogue()
    assert cat.manifest["schema_version"] == SCHEMA_VERSION
    assert cat.manifest["parser_version"] == PARSER_VERSION
