"""Forever-owned P3 native CLI/response tests, not Warcraft-legality audits."""
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from src.game.native_p3_item_options import (
    NativeItemOptionsError, apply_native_mage_spell_coefficients,
    native_p3_item_records, query_native_mage_spell_coefficients,
    query_native_p3_item_options,
)
from src.game.checkpoint_p3_smoke import fast_p3_smoke
from src.rulesets.forever.items.catalogue import ItemRecord


def _response(*, status="ok", items=None, **overrides):
    if items is None:
        items = [{"item_id": 25, "item_level": 3, "required_level": 1,
                  "slot": "chest", "stats": {"Stamina": 2.0}}]
    return {"status": status, "class": "priest", "level": 20,
            "spec": "unrestricted", "slot": "all",
            "required_level_supported": True, "unverified_candidate_count": 0,
            "excluded_non_client_item_count": 0,
            "source": "mythicsim:data/items.jsonl+client:ItemSparse.RequiredLevel",
            "items": items, "refusal": None} | overrides


def _runner(payload, *, returncode=0, stderr=""):
    def run(_command, **_kwargs):
        return SimpleNamespace(returncode=returncode,
                               stdout=json.dumps(payload), stderr=stderr)
    return run


def test_native_p3_forwards_request_and_preserves_source_candidates():
    seen = []
    payload = _response()
    def runner(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
    actual = query_native_p3_item_options("/tmp/native", "priest", 20, runner=runner)
    assert actual == payload
    assert seen[0][0] == ["/tmp/native", "item-options", "--class", "priest",
                          "--level", "20", "--spec", "unrestricted", "--slot", "all"]
    assert seen[0][1]["timeout"] == 60

def test_native_p3_forwards_shaman_request_and_preserves_source_candidates():
    item = {
        "item_id": 25, "name": "Sourced Shaman chest", "item_level": 3,
        "required_level": 1, "slot": "chest", "stats": {"Stamina": 4.0},
    }
    payload = _response(
        items=[item], **{
            "class": "shaman",
            "source": "mythicsim:data/items.jsonl+client:ItemSparse.RequiredLevel+SkillLine+SkillRaceClassInfo",
            "excluded_non_client_item_count": 3075,
        })
    seen = []

    def runner(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    records, unmapped, metadata = native_p3_item_records(
        "native", "shaman", 20, runner=runner)

    assert seen == [[
        "native", "item-options", "--class", "shaman", "--level", "20",
        "--spec", "unrestricted", "--slot", "all",
    ]]
    assert len(records) == 1
    assert records[0].item_id == 25
    assert records[0].stamina == 4.0
    assert unmapped == {}
    assert metadata["status"] == "ok"
    assert metadata["unverified_candidate_count"] == 0
    assert metadata["excluded_non_client_item_count"] == 3075
    assert metadata["source"] == (
        "mythicsim:data/items.jsonl+client:ItemSparse.RequiredLevel+SkillLine+SkillRaceClassInfo"
    )



def test_native_p3_shaman_requires_client_exclusion_accounting():
    payload = _response(**{"class": "shaman"})
    del payload["excluded_non_client_item_count"]
    with pytest.raises(
        NativeItemOptionsError,
        match="EXCLUDED_NON_CLIENT_COUNT_UNAVAILABLE",
    ):
        query_native_p3_item_options("native", "shaman", 20, runner=_runner(payload))


def test_native_p3_empty_is_distinct_from_refusal():
    assert query_native_p3_item_options("native", "priest", 20, runner=_runner(
        _response(status="empty", items=[])))["items"] == []
    with pytest.raises(NativeItemOptionsError, match="REFUSED:NATIVE_UNSUPPORTED"):
        query_native_p3_item_options("native", "priest", 20, runner=_runner(
            _response(status="refused", items=[],
                      refusal={"code": "NATIVE_UNSUPPORTED"})))


def test_native_p3_preserves_partial_level_unknown_status_and_count():
    payload = _response(status="partial_level_unknown", unverified_candidate_count=2267)
    actual = query_native_p3_item_options("native", "priest", 20, runner=_runner(payload))
    assert actual["status"] == "partial_level_unknown"
    assert actual["unverified_candidate_count"] == 2267


@pytest.mark.parametrize("payload,reason", [
    (_response(required_level_supported=False), "LEVEL_SOURCE_UNAVAILABLE"),
    (_response(level=60), "REQUEST_MISMATCH"),
    (_response(status="empty"), "STATUS_COUNT_MISMATCH"),
    (_response(status="partial_level_unknown", unverified_candidate_count=0), "STATUS_COUNT_MISMATCH"),
    (_response(unverified_candidate_count=1), "STATUS_COUNT_MISMATCH"),
    (_response(items=[{"item_id": 25, "slot": "head"}]), "INVALID_ITEM_SHAPE"),
])
def test_native_p3_refuses_unusable_responses(payload, reason):
    with pytest.raises(NativeItemOptionsError, match=reason):
        query_native_p3_item_options("native", "priest", 20, runner=_runner(payload))


def test_native_p3_execution_failure_does_not_fall_back_to_sqlite():
    with pytest.raises(NativeItemOptionsError, match="EXECUTION_FAILED"):
        query_native_p3_item_options("native", "priest", 20,
            runner=_runner(_response(), returncode=1, stderr="no native binary"))
    def timeout(_command, **_kwargs):
        raise subprocess.TimeoutExpired("native", 60)
    with pytest.raises(NativeItemOptionsError, match="EXECUTION_FAILED"):
        query_native_p3_item_options("native", "priest", 20, runner=timeout)


def test_native_p3_projects_unit_preserving_fields_and_marks_unmapped_ratings():
    item = {"item_id": 25, "item_level": 12, "required_level": 7,
            "required_level_origin": "client_ItemSparse.RequiredLevel",
            "slot": "ranged", "name": "Sourced wand",
            "ranged_weapon_type": "RangedWeaponTypeWand",
            "weapon_type": "WeaponTypeUnknown", "hand_type": "HandTypeUnknown",
            "weapon_damage_min": 8.0, "weapon_damage_max": 12.0,
            "weapon_speed": 2.0,
            "stats": {"Stamina": 4.0, "SpellDamage": 6.0,
                      "SpellHitRating": 10.0}}
    records, unmapped, metadata = native_p3_item_records(
        "native", "priest", 20, runner=_runner(_response(
            status="partial_level_unknown", unverified_candidate_count=2267, items=[item])))
    assert len(records) == 1
    assert metadata == {
        "status": "partial_level_unknown",
        "unverified_candidate_count": 2267,
        "excluded_non_client_item_count": 0,
        "source": "mythicsim:data/items.jsonl+client:ItemSparse.RequiredLevel",
    }
    assert records[0].weapon_type == "wand"
    assert records[0].weapon_dps == 5.0
    assert records[0].stamina == 4.0
    assert records[0].spell_power == 6.0
    assert unmapped == {25: ("SpellHitRating",)}


def test_native_p3_never_rechecks_native_item_level_legality():
    items = [{"item_id": 700, "item_level": 8, "required_level": 60,
              "slot": "chest", "stats": {}},
             {"item_id": 2, "item_level": 3, "required_level": 1,
              "slot": "head", "stats": {}}]
    result = query_native_p3_item_options(
        "native", "priest", 20, runner=_runner(_response(items=items)))
    assert result["items"] == items


def test_native_p3_partial_unknown_is_measured_but_not_certified():
    item = ItemRecord(
        item_id=25, name="Sourced chest", slot="chest", item_level=3,
        required_level=1, stamina=2.0, identity_origin="mythicsim_native",
        source_type="mythicsim_native")
    metadata = {
        "status": "partial_level_unknown",
        "unverified_candidate_count": 2267,
        "source": "mythicsim:data/items.jsonl+client:ItemSparse.RequiredLevel",
    }
    with patch(
        "src.game.native_p3_item_options.native_p3_item_records",
        return_value=((item,), {}, metadata),
    ):
        report = fast_p3_smoke(
            class_key=class_key, level=20, weights={"stamina": 1.0},
            weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
            weapon_damage_dependent=False, equipped_weapon_dps_relevant=False,
            defensive_positive_required=False, native_options_binary="native")
    assert report["native_item_options_status"] == "partial_level_unknown"
    assert report["native_unverified_candidate_count"] == 2267
    assert report["native_item_options_source"] == metadata["source"]
    assert report["tested_item_count"] == 1
    assert report["verified_stat_assertions"] == 1
    assert "NATIVE_ITEM_OPTIONS_PARTIAL_LEVEL_UNKNOWN:2267" in report["blockers"]
    assert report["p3_pass"] is False



@pytest.mark.parametrize(("class_key", "level", "spec"), [
    ("priest", 20, "unrestricted"),
    ("mage", 20, "unrestricted"),
    ("mage", 30, "unrestricted"),
    ("shaman", 20, "unrestricted"),
])
def test_native_p3_live_gate_fails_closed_without_binary(
        monkeypatch, class_key, level, spec):
    from tools.wf_gate_p3_live import run_live

    monkeypatch.delenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", raising=False)
    report = run_live(Path("."), class_key, level, spec=spec)
    assert report == {
        "status": "BLOCKED",
        "reasons": ["P3_NATIVE_ITEM_OPTIONS_BINARY_REQUIRED"],
        "production_component": "src.game.native_p3_item_options",
    }


def test_m1_recorder_builds_exact_native_binary_for_verified_option_consumers():
    workflow = Path(".github/workflows/m1-on-demand-record.yml").read_text()
    assert "native_options_needed=false" in workflow
    assert 'IFS=: read -r class level spec gate <<< "$entry"' in workflow
    assert 'if [[ "$gate" == P3 ]]; then' in workflow
    assert 'if [[ "$level" == 20 && ( "$class" == priest || "$class" == mage ) ]] ||' in workflow
    assert '[[ "$level" == 20 && "$class" == shaman && "$spec" == unrestricted ]] ||' in workflow
    assert '[[ "$level" == 30 && "$class" == mage && "$spec" == unrestricted ]]; then' in workflow
    assert 'elif [[ ( "$gate" == P4 || "$gate" == P5 ) && "$class" == priest && "$level" == 20 ]]; then' in workflow
    assert "native_options_needed=true" in workflow
    assert "if: steps.targets.outputs.invalidate != 'true' && steps.targets.outputs.native_options_needed == 'true' && steps.targets.outputs.p7_needed != 'true'" in workflow
    assert 'git submodule update --init --depth 1 "$engine"' in workflow
    assert 'git ls-tree HEAD -- "$engine"' in workflow
    assert "RUST_FORK_SUBMODULE_PIN_MISMATCH" in workflow
    assert 'cargo build --release --locked --manifest-path "$engine/Cargo.toml" --bin forever-engine' in workflow
    assert "FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN: ${{ github.workspace }}/upstream/target/release/forever-engine" in workflow



@pytest.mark.parametrize(("status", "unverified_count"), [
    ("empty", 0),
    ("partial_level_unknown", 2267),
])
def test_native_p3_empty_result_keeps_native_status_without_sqlite_fallback(
        status, unverified_count):
    metadata = {
        "status": status,
        "unverified_candidate_count": unverified_count,
        "source": "mythicsim:data/items.jsonl+client:ItemSparse.RequiredLevel",
    }
    with patch(
        "src.game.native_p3_item_options.native_p3_item_records",
        return_value=((), {}, metadata),
    ):
        report = fast_p3_smoke(
            class_key=class_key, level=20, weights={"stamina": 1.0},
            weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
            weapon_damage_dependent=False, equipped_weapon_dps_relevant=False,
            defensive_positive_required=False, native_options_binary="native")
    assert report["source"] == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
    assert report["legal_item_count"] == 0
    assert report["native_item_options_status"] == status
    assert report["native_unverified_candidate_count"] == unverified_count
    assert report["native_item_options_source"] == metadata["source"]
    assert "NATIVE_ITEM_OPTIONS_NO_VERIFIED_CANDIDATES" in report["blockers"]
    if status == "partial_level_unknown":
        assert (
            f"NATIVE_ITEM_OPTIONS_PARTIAL_LEVEL_UNKNOWN:{unverified_count}"
            in report["blockers"]
        )
    assert report["p3_pass"] is False


@pytest.mark.parametrize(("class_key", "excluded_count"), [
    ("priest", 0),
    ("shaman", 3075),
])
def test_native_p3_scores_native_candidates_only_and_selects_ilvl_top_five(
        class_key, excluded_count):
    levels = [3, 12, 7, 11, 9, 10, 8]
    items = tuple(ItemRecord(
        item_id=100 + index, name=f"Native chest {index}", slot="chest",
        item_level=item_level, required_level=1, stamina=2.0,
        identity_origin="mythicsim_native", source_type="mythicsim_native")
        for index, item_level in enumerate(levels))
    source = "mythicsim:data/items.jsonl+client:ItemSparse.RequiredLevel"
    if class_key == "shaman":
        source += "+SkillLine+SkillRaceClassInfo"
    metadata = {
        "status": "ok",
        "unverified_candidate_count": 0,
        "excluded_non_client_item_count": excluded_count,
        "source": source,
    }
    with patch(
        "src.game.native_p3_item_options.native_p3_item_records",
        return_value=(items, {}, metadata),
    ), patch(
        "src.game.checkpoint_p3_smoke.available_items",
        side_effect=AssertionError("native P3 must not call SQLite availability"),
    ):
        report = fast_p3_smoke(
            class_key="priest", level=20, weights={"stamina": 1.0},
            weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
            weapon_damage_dependent=False, equipped_weapon_dps_relevant=False,
            defensive_positive_required=False, native_options_binary="native")
    assert report["source"] == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
    assert report["legal_item_count"] == 7
    assert report["native_excluded_non_client_item_count"] == excluded_count
    assert report["tested_item_count"] == 5
    assert report["slots"]["chest"]["selected_ids"] == [101, 103, 105, 104, 106]
    assert report["slots"]["chest"]["selection"] == "HIGHEST_ITEM_LEVEL_NOT_SCORE"



def test_native_p3_activation_is_limited_to_verified_unrestricted_targets():
    from tools.wf_gate_p3_live import native_item_options_required

    assert native_item_options_required("priest", 20, "unrestricted")
    assert native_item_options_required("priest", 20, "shadow")
    assert native_item_options_required("mage", 20, "unrestricted")
    assert native_item_options_required("mage", 20, "arcane")
    assert native_item_options_required("mage", 30, "unrestricted")
    assert native_item_options_required("shaman", 20, "unrestricted")
    assert native_item_options_required("SHAMAN", 20, "UNRESTRICTED")
    assert not native_item_options_required("shaman", 20, "enhancement")
    assert not native_item_options_required("shaman", 30, "unrestricted")
    assert not native_item_options_required("mage", 30, "feral-cat")
    assert not native_item_options_required("priest", 30, "unrestricted")
    assert not native_item_options_required("mage", 40, "unrestricted")
    assert not native_item_options_required("warrior", 20, "unrestricted")

def test_selected_engine_workflow_runs_shaman_l20_native_p3_without_record():
    workflow = Path(".github/workflows/rust-submodule-verify.yml").read_text()
    assert "Run no-record Shaman L20 P3 with native item options" in workflow
    shaman = workflow.split(
        "Run no-record Shaman L20 P3 with native item options", 1
    )[1].split("Run no-record Mage L30 P3 with native item options", 1)[0]
    assert "--class shaman --level 20" in shaman
    assert '--spec unrestricted --gate P3 --out "$report"' in shaman
    assert 'row["item_options_source"] == "MYTHICSIM_NATIVE_ITEM_OPTIONS"' in shaman
    assert 'row["real_source_search_evaluated"] <= 44' in shaman
    assert 'row["native_excluded_non_client_item_count"] > 0' in shaman
    assert "--record-pass" not in shaman

def test_selected_engine_workflow_runs_mage_l30_native_p3_without_record():
    workflow = Path(".github/workflows/rust-submodule-verify.yml").read_text()
    assert "Run no-record Mage L30 P3 with native item options" in workflow
    mage30 = workflow.split(
        "Run no-record Mage L30 P3 with native item options", 1
    )[1].split("Upload no-record native P3 reports", 1)[0]
    assert "--class mage --level 30" in mage30
    assert '--spec unrestricted --gate P3 --out "$report"' in mage30
    assert 'row["item_options_source"] == "MYTHICSIM_NATIVE_ITEM_OPTIONS"' in mage30
    assert 'row["native_item_options_status"]' in mage30
    assert 'row["native_unverified_candidate_count"]' in mage30
    assert 'row["real_catalogue_legal_items"]' in mage30
    assert "--record-pass" not in mage30

def test_native_mage_spell_coefficients_are_read_from_prepared_v2(tmp_path):
    import json
    from types import SimpleNamespace

    prepared = {
        "contract": "forever-prepared",
        "schema_version": 2,
        "reference": {"engine_revision": "native-engine-test-revision"},
        "player": {
            "class": "Mage",
            "spells": [
                {"action_id": {"spell_id": 8401}, "bonus_coefficient": 0.857},
                {"action_id": {"spell_id": 8406}, "bonus_coefficient": 0.714},
            ],
        },
    }
    observed = {}

    def runner(command, **kwargs):
        assert command[1:3] == ["prepare", "--request"]
        request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        player = request["raid"]["parties"][0]["players"][0]
        observed["class"] = player["class"]
        observed["talents"] = player["talentsString"]
        observed["mage_options"] = player["mage"]["options"]["classOptions"]
        observed["fireball_action"] = player["rotation"]["priorityList"][0]["action"]
        observed["equipment"] = player["equipment"]
        return SimpleNamespace(
            returncode=0, stdout=json.dumps(prepared), stderr="")

    result = query_native_mage_spell_coefficients(
        "native-engine", runner=runner)

    assert observed["class"] == "ClassMage"
    assert observed["talents"] == "0-0-0"
    assert observed["mage_options"]["defaultMageArmor"] == "MageArmorMageArmor"
    assert observed["fireball_action"]["castSpell"]["spellId"]["spellId"] == 8401
    assert observed["equipment"] == {"items": []}
    assert result["source"] == "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS"
    assert result["engine_revision"] == "native-engine-test-revision"
    assert result["spell_power_coefficients"] == {8401: 0.857, 8406: 0.714}


def test_native_mage_spell_prepare_refusal_includes_native_reason():
    refusal = {
        "prepared": False,
        "refusal": {
            "code": "class_option",
            "reason": "a mage without its class options",
        },
    }

    with pytest.raises(
        NativeItemOptionsError,
        match="P3_NATIVE_SPELLBOOK_PREPARE_FAILED:class_option:a mage without its class options",
    ):
        query_native_mage_spell_coefficients(
            "native-engine",
            runner=_runner(refusal, returncode=5),
        )


def test_native_mage_spell_coefficients_enrich_only_exact_source_rank_actions():
    from dataclasses import replace
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.model.ir import DamageEffect

    ir = build_game_ir_slice(class_key="mage", level=30)
    fireball = next(action for action in ir.actions if action.id == "fireball:8401")
    reset_effects = tuple(
        replace(effect, spell_power_coefficient=0.0)
        if isinstance(effect, DamageEffect) else effect
        for effect in fireball.effects
    )
    reset_fireball = replace(fireball, effects=reset_effects)
    ir = replace(
        ir,
        actions=tuple(reset_fireball if action.id == fireball.id else action
                      for action in ir.actions),
    )
    native = {
        "source": "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS",
        "engine_revision": "native-engine-test-revision",
        "spell_power_coefficients": {8401: 0.857},
    }

    enriched, applied = apply_native_mage_spell_coefficients(ir, native)
    updated = next(action for action in enriched.actions if action.id == "fireball:8401")
    direct = next(effect for effect in updated.effects if isinstance(effect, DamageEffect))

    assert direct.spell_power_coefficient == 0.857
    assert updated.metadata["native_spell_power_coefficient_verified"] is True
    assert applied == [{
        "action_id": "fireball:8401",
        "spell_id": 8401,
        "spell_power_coefficient": 0.857,
    }]
    assert any(
        fact.get("authority") == "mythicsim_rust_prepared_v2"
        and fact.get("spell_id") == 8401
        for fact in enriched.source_facts
    )
    assert not any(
        blocker.get("code") == "source_rank_spell_power_coefficient_unverified"
        and blocker.get("spell_id") == 8401
        for blocker in enriched.unsupported_semantics
    )

