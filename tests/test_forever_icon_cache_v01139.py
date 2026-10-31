import json
from pathlib import Path
import subprocess
import sys

from src.v2.icon_provenance import item_icon, rotation_icon, talent_icon


def test_refresh_script_extracts_icons_without_downloading_images(tmp_path):
    raw = {
        "generated": "fixture-date",
        "license": "CC BY 4.0",
        "talents": {
            "Paladin": {"trees": [{"talents": [
                {"name": "Guardian's Favor", "icon": "spell_holy_sealofprotection"},
                {"name": "Deflection", "icon": "ability_parry"},
            ]}]}
        },
        "spellbooks": {
            "Paladin": {"icons": {
                "Holy Strike": "classicon_paladin",
                "Judgement": "spell_holy_righteousfury",
            }}
        },
    }
    source = tmp_path / "data.json"
    output = tmp_path / "icons.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "tools" / "refresh_forever_icon_cache.py"
    subprocess.run([sys.executable, str(script), "--source", str(source), "--output", str(output)], check=True)
    got = json.loads(output.read_text(encoding="utf-8"))
    pal = got["classes"]["paladin"]
    assert pal["talents"]["guardians_favor"]["icon_key"] == "spell_holy_sealofprotection"
    assert pal["talents"]["deflection"]["icon_key"] == "ability_parry"
    assert pal["spells"]["holy_strike"]["icon_key"] == "classicon_paladin"
    assert "image" not in json.dumps(got).lower()  # cache is names + icon keys, never image bytes


def test_runtime_cache_covers_paladin_talents_rotation_and_more_real_l20_items():
    t = talent_icon("paladin", "precision")
    assert t["icon_provider"] == "talentsforever_data"
    assert t["icon_key"] == "ability_rogue_ambush"
    assert t["icon_url"].endswith("/ability_rogue_ambush.jpg")

    hs = rotation_icon("paladin", "Holy Strike on CD", level=20)
    assert hs["icon_provider"] == "talentsforever_data"
    assert hs["icon_key"] == "classicon_paladin"
    assert hs["entity_id"] == 1866

    assert item_icon("Crusader's Chain Shirt")["entity_id"] == 250492
    assert item_icon("Crusader's Gloves")["entity_id"] == 250512
    assert item_icon("Modeled Mail Gloves") is None


def test_shipped_paladin_cache_covers_every_modeled_talent_key():
    from src.rulesets.forever.classes.paladin.talents import TALENT_RULES
    missing = [key for key in TALENT_RULES if talent_icon('paladin', key) is None]
    assert missing == []
