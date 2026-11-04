"""Forever-owned P3 native CLI/response tests, not Warcraft-legality audits."""
import json
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from src.game.native_p3_item_options import (
    NativeItemOptionsError, native_p3_item_records, query_native_p3_item_options,
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
            class_key="priest", level=20, weights={"stamina": 1.0},
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
