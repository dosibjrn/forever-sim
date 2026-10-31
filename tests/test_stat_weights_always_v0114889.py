import json
from copy import deepcopy

import pytest

from src import listener
from src.v2 import decision_dashboard
from src.v2.decision_stat_weights import (
    clear_cache,
    compute_row_stat_weights,
    ensure_row_stat_weights,
    scorer_state_fingerprint,
)


def _write_decision_shell(tmp_path, endpoint):
    root = tmp_path / "state/decisions/forever"
    root.mkdir(parents=True, exist_ok=True)
    (root / "endpoint_paths.json").write_text(json.dumps(endpoint), encoding="utf-8")
    for name in ("spec_matrix", "spec_regret", "dual_spec"):
        (root / f"{name}.json").write_text(json.dumps({"classes": {}}), encoding="utf-8")


def test_druid_l30_endpoint_only_route_rehydrates_real_stat_weights(tmp_path, monkeypatch):
    """Exact regression for the listener failure reported by the user.

    The preserved endpoint has no spec-matrix row at all. The Decisions payload
    must still expose canonical Druid sensitivities, never the historical
    `spec-matrix stat weights unavailable for this route step` placeholder.
    """
    from src.rulesets.forever.classes.druid import engine as druid

    monkeypatch.setattr(decision_dashboard, "CLASSES", ("druid",))
    t = druid.Talents(
        improved_wrath=5,
        moonglow=3,
        improved_moonfire=2,
        natures_majesty=2,
        natures_reach=2,
        natures_splendor=1,
        insect_swarm=1,
        vengeance=5,
    )
    score = druid.experimental_level_score(30, t, "balance")
    ranks = {k: int(getattr(t, k)) for k in t.__dataclass_fields__ if int(getattr(t, k))}
    step = {
        "level": 30,
        "allocation": druid.final_allocation(t),
        "talent_ranks": ranks,
        "tree_points": {name: druid.tree_points(t, name) for name in druid.TREE_NAMES},
        "talent_family": "balance",
        "combat_profile": "balance",
        "gear": score.get("gear"),
        "gear_stats": score.get("gear_stats"),
        "rotation": score.get("rotation"),
        "pull_size": score.get("pull_size"),
        "score_s_per_100": score["total_s"],
        "mobs_per_hour": score.get("mobs_per_hour"),
        # deliberately NO stat_weights / spec_matrix source
    }
    endpoint = {
        "classes": {
            "druid": {
                "targets": {
                    "30": {
                        "status": "available",
                        "routes": {
                            "unconstrained": {
                                "status": "available",
                                "path": {"steps": [step]},
                                "transitions": [],
                            }
                        },
                    }
                }
            }
        }
    }
    _write_decision_shell(tmp_path, endpoint)
    clear_cache()
    payload = decision_dashboard.build_decision_payload(tmp_path, selected_level=30)
    route = payload["route_rows"]["druid"]["30"]["routes"]["unconstrained"]
    assert route["status"] == "available"
    assert route["stat_weights_complete"] is True
    row = route["rows"][0]
    assert row["data_sources"] == ["endpoint_path"]
    assert row["stat_weights_contract_ok"] is True
    assert row["stat_weight_source"] == "canonical_fixed_state_rehydration"
    assert row["stat_weights"]["stats"]
    assert "stat_weights" not in row["missing"]
    assert "spec-matrix stat weights unavailable" not in json.dumps(payload)


def test_stat_weight_state_fingerprint_changes_with_talents_gear_or_policy():
    base = {
        "level": 20,
        "talent_ranks": {"deflection": 5},
        "combat_profile": "retribution",
        "policy": "policy-a",
        "gear_stats": {"slots": {"weapon": {"item_id": 1, "weapon_dps": 10.0}}},
    }
    fp = scorer_state_fingerprint("paladin", base)
    talent = deepcopy(base); talent["talent_ranks"] = {"deflection": 4, "benediction": 1}
    gear = deepcopy(base); gear["gear_stats"]["slots"]["weapon"]["item_id"] = 2
    policy = deepcopy(base); policy["policy"] = "policy-b"
    assert fp != scorer_state_fingerprint("paladin", talent)
    assert fp != scorer_state_fingerprint("paladin", gear)
    assert fp != scorer_state_fingerprint("paladin", policy)


def test_same_fixed_state_uses_deterministic_weight_cache():
    from src.rulesets.forever.classes.hunter import engine as hunter
    talents = hunter.Talents(deadly_aspects=5, focused_fire=2, improved_revive_pet=2, improved_tracking=2)
    score = hunter.experimental_level_score(20, talents, "beast_mastery")
    row = {
        "level": 20,
        "talent_ranks": {k:int(getattr(talents,k)) for k in talents.__dataclass_fields__ if int(getattr(talents,k))},
        "combat_profile": "beast_mastery",
        "gear": score.get("gear"), "gear_stats": score.get("gear_stats"),
        "rotation": score.get("rotation"), "policy": score.get("policy"),
        "pull_size": score.get("pull_size"), "score_s_per_100": score.get("total_s"),
    }
    clear_cache()
    first, fp1, source1 = compute_row_stat_weights("hunter", row)
    second, fp2, source2 = compute_row_stat_weights("hunter", row)
    assert fp1 == fp2
    assert first == second
    assert source1 == "canonical_fixed_state_rehydration"
    assert source2 == "cache"


def test_representative_supported_classes_can_rehydrate_nonempty_weights():
    from src.rulesets.forever.classes.paladin import engine as paladin
    from src.rulesets.forever.classes.druid import engine as druid
    from src.rulesets.forever.classes.hunter import engine as hunter

    cases = []
    pt = paladin.Talents(deflection=5,benediction=3,conviction=2,seal_of_command=1)
    ps = paladin.experimental_level_score(20, pt, "retribution")
    cases.append(("paladin", pt, ps, "retribution"))
    dt = druid.Talents(improved_wrath=5,genesis=2,improved_moonfire=2,natures_majesty=2)
    ds = druid.experimental_level_score(20, dt, "balance")
    cases.append(("druid", dt, ds, "balance"))
    ht = hunter.Talents(deadly_aspects=5,focused_fire=2,improved_revive_pet=2,improved_tracking=2)
    hs = hunter.experimental_level_score(20, ht, "beast_mastery")
    cases.append(("hunter", ht, hs, "beast_mastery"))

    clear_cache()
    for class_name, talents, score, profile in cases:
        row={
            "level":20,
            "talent_ranks":{k:int(getattr(talents,k)) for k in talents.__dataclass_fields__ if int(getattr(talents,k))},
            "combat_profile":profile,
            "gear":score.get("gear"), "gear_stats":score.get("gear_stats"),
            "rotation":score.get("rotation"), "policy":score.get("policy"),
            "pull_size":score.get("pull_size"), "score_s_per_100":score.get("total_s"),
        }
        out=ensure_row_stat_weights(class_name,row)
        assert out["stat_weights_contract_ok"] is True
        assert out["stat_weights"]["stats"]
        assert out["stat_weight_fingerprint"]

    # Mature Mage is the one legacy scorer that reconstructs its fixed-state cast
    # mix during rehydration; it must satisfy the same public contract.
    mage_row={"level":20,"talent_ranks":{"imp_frostbolt":5,"elemental_precision":3,"ice_shards":3},"combat_profile":"frost"}
    mout=ensure_row_stat_weights("mage",mage_row)
    assert mout["stat_weights_contract_ok"] is True
    assert mout["stat_weights"]["stats"]


def test_constrained_or_reference_challenger_uses_same_weight_authority():
    from src.rulesets.forever.classes.druid import engine as druid
    talents=druid.Talents(improved_wrath=5,genesis=2,improved_moonfire=2,natures_majesty=2)
    score=druid.experimental_level_score(20,talents,"balance")
    row = {
        "level": 20,
        "talent_ranks": {k:int(getattr(talents,k)) for k in talents.__dataclass_fields__ if int(getattr(talents,k))},
        "combat_profile": "balance",
        "gear":score.get("gear"), "gear_stats":score.get("gear_stats"),
        "rotation":score.get("rotation"), "score_s_per_100":score.get("total_s"),
    }
    clear_cache()
    a, fpa, _ = compute_row_stat_weights("druid", row, route_name="balance")
    b, fpb, _ = compute_row_stat_weights("druid", row, route_name="reference_challenger")
    assert fpa == fpb
    assert a == b


def test_listener_only_offers_routes_that_have_weights_and_old_placeholder_is_gone():
    html = listener.DECISIONS_HTML
    assert "function hasStatWeights(row)" in html
    assert "route?.status==='available'&&rows.length&&rows.every(hasStatWeights)" in html
    assert "per.length&&per.every(hasStatWeights)" in html
    assert "spec-matrix stat weights unavailable for this route step" not in html
