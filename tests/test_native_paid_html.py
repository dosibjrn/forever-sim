"""The HTML publisher describes verified native receipts, never invents BiS."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.wf_native_paid_html import (
    render_native_paid_html, write_native_paid_html_reports, main as html_main,
)


def _sample(*, level=20, seconds=35.525, pet="Succubus", label="a",
            item_name="Equipped Wand"):
    source = (label * 64) if label in "abcdef" else ("a" * 64)
    engine = "f" * 64
    gear = {"items": [{"id": 12345}]}
    apl = {"priorityList": [{"action": {"castSpell": {
        "spellId": {"spellId": 11711}}}}]}
    raw = {
        "status": "MEASURED_NATIVE_FULLY_RECOVERED",
        "candidate_id": "L" + str(level) + "_paid",
        "level": level,
        "mob_count": 2,
        "targets_killed": 2,
        "rng_mode": "balanced",
        "iterations": 1,
        "native_prepared": True,
        "native_world_ack": True,
        "native_full_recovery_paid": True,
        "recover_to_full": True,
        "terminal_hp": 600,
        "terminal_max_hp": 600,
        "terminal_mana": 1000,
        "terminal_max_mana": 1000,
        "elapsed_seconds": seconds,
        "terminal_recovery_seconds": 7.5,
        "source_request_sha256": source,
        "engine_binary_sha256": engine,
        "native_raw_receipt_sha256": "e" * 64,
        "native_raw_receipt_file": "runs/native/example.native.json",
        "talents": "210-0-0",
        "gear": gear,
        "apl": apl,
        "pet": pet,
        "native_named_build": {
            "talent_names": [
                {"tree": "Affliction", "name": "Improved Corruption",
                 "rank": 2, "max_rank": 5},
            ],
            "equipped_item_names_ids": [
                {"position": 16, "native_slot": "ranged",
                 "item_id": 12345, "name": item_name},
            ],
            "ordered_apl_spells": [
                {"priority": 1, "spell_id": 11711, "name": "Bane of Agony",
                 "rank": "5", "condition": {"if": "target"}},
            ],
        },
    }
    row = {
        "source_request_sha256": source,
        "engine_binary_sha256": engine,
        "native_elapsed_seconds": seconds,
        "terminal_recovery_seconds": 7.5,
        "talents": "210-0-0",
        "gear": gear,
        "apl": apl,
        "pet": pet,
        "receipt": raw,
    }
    return row


def _result(rows, level=20, class_name="warlock"):
    return {
        "status": "SAMPLED_COMPATIBLE_PATH_RANKED",
        "sampled_levels_requested": [level],
        "independent_level_rankings": {str(level): rows},
        "mob_count": 2,
        "rng_mode": "balanced",
        "iterations": 1,
        "class": class_name,
    }


def test_offline_html_contains_bis_style_gear_talents_apl_pet_provenance():
    result = _result([
        _sample(seconds=50, label="b", pet=None),
        _sample(seconds=35.525, label="a"),
    ])
    page = render_native_paid_html(result, level=20)
    assert page.startswith("<!doctype html>")
    assert "<style>" in page and "<html" in page
    assert "<script" not in page and "<link rel=" not in page
    assert page.index("35.525") < page.index("50.000")
    for expected in ("Equipped Wand", "Improved Corruption", "Bane of Agony",
                     "Succubus", "Native verification and traceability",
                     "Best tested, not guaranteed BiS.", "Native paid",
                     "7.500", "source"):
        assert expected.lower() in page.lower()
    assert "gear sets" in page and "pet choices" in page


def test_refused_and_tampered_receipts_never_become_html_winners():
    invalid = _sample(label="b", seconds=1.0)
    invalid["receipt"]["native_full_recovery_paid"] = False
    result = _result([_sample(label="a"), invalid])
    page = render_native_paid_html(result, level=20)
    assert "35.525" in page
    assert "1.000" not in page
    assert "1</strong><span>Measured" in page
    with pytest.raises(ValueError, match="NO_VERIFIED_NATIVE_PAID_WINNER"):
        render_native_paid_html(_result([invalid]), level=20)
    assert write_native_paid_html_reports(_result([invalid]), Path("/missing/path")) == []


def test_untrusted_native_labels_are_escaped():
    attack = "<img src=x onerror=alert(1)>"
    page = render_native_paid_html(
        _result([_sample(item_name=attack)]), level=20)
    assert attack not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page


def test_write_reuses_existing_paid_json_without_launching_engine(tmp_path):
    result = _result([_sample()])
    source = tmp_path / "existing-native.json"
    source.write_text(json.dumps(result))
    dest = tmp_path / "reports"
    assert html_main(["--in", str(source), "--out-dir", str(dest)]) == 0
    report = dest / "warlock-l20-best-tested.html"
    assert report.is_file()
    assert report.read_text() == render_native_paid_html(result, level=20)


def test_generic_optimizer_saves_html_automatically_with_paid_receipt(tmp_path):
    from src.v2.native_range_optimizer import main as optimize_main

    example = _sample()
    raw = example["receipt"]

    def evaluator(*, level, parent, mob_count, **kwargs):
        assert level == 20 and parent is None and mob_count == 2
        return [dict(raw, **{
            "native_world_policy": {"rest_when_health_below": 0.3},
        })]

    # A real production run uses native Rust; this is only the CLI output contract.
    # Build the fake receipt as a self-consistent native-transport-shaped row.
    result_file = tmp_path / "results.json"
    code = optimize_main([
        "--class", "warlock", "--start-level", "20", "--end-level", "20",
        "--budget", "2", "--beam-width", "1", "--n-mobs", "2",
        "--out", str(result_file),
    ], evaluate=evaluator)
    assert code == 0
    assert (tmp_path / "html" / "warlock-l20-best-tested.html").is_file()

def test_paid_html_class_label_and_filename_come_from_measured_result(tmp_path):
    # These are synthetic receipt-transport fixtures, not real Mage/Druid sims.
    for character_class in ("mage", "druid", "hunter", "priest"):
        result = _result([_sample(pet=None)], class_name=character_class)
        report = render_native_paid_html(result, level=20)
        assert f"<h1>{character_class.title()} · Level 20</h1>" in report
        assert f"WoW Forever {character_class.title()} L20" in report
        assert "<h1>Warlock" not in report
        pages = write_native_paid_html_reports(
            result, tmp_path / character_class)
        assert [p.name for p in pages] == [
            f"{character_class}-l20-best-tested.html"]
        assert pages[0].read_text() == report


def test_html_refuses_missing_or_unknown_class_instead_of_guessing_warlock(tmp_path):
    result = _result([_sample()])
    del result["class"]
    with pytest.raises(ValueError, match="native optimizer class"):
        render_native_paid_html(result, level=20)
    with pytest.raises(ValueError, match="native optimizer class"):
        write_native_paid_html_reports(result, tmp_path / "missing-class")


def test_shared_optimizer_accepts_injected_mage_evaluator_without_warlock_module(tmp_path):
    from src.v2.native_range_optimizer import main as optimize_main

    candidate = _sample(pet=None)
    def evaluator(*, level, parent, mob_count, **kwargs):
        assert level == 20 and parent is None and mob_count == 2
        return [candidate["receipt"]]

    result_file = tmp_path / "mage.json"
    code = optimize_main([
        "--class", "mage", "--start-level", "20", "--end-level", "20",
        "--budget", "2", "--beam-width", "1", "--n-mobs", "2",
        "--out", str(result_file),
    ], evaluate=evaluator)
    assert code == 0
    result = json.loads(result_file.read_text())
    assert result["class"] == "mage"
    html = (tmp_path / "html" / "mage-l20-best-tested.html").read_text()
    assert "<h1>Mage · Level 20</h1>" in html
    assert "<h1>Warlock" not in html
