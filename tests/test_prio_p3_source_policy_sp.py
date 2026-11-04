"""Regression for source-backed P3 stat relevance across legal policies.

Production IR, canonical Forever SQLite, real gsim CombatRuntime/recovery,
and the unchanged gear stat applicator: no mock scores or fabricated epsilon.
"""
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_budgeted_gear import paid_source_policy_stat_witness
from tools.wf_gate_p3_live import _source_profile_build_ir, run_live


ROOT = Path(__file__).resolve().parents[1]


def test_real_balance_caster_source_policy_proves_sp_positive():
    original = build_game_ir_slice(class_key="druid", level=60)
    selected, context = _source_profile_build_ir(
        ROOT, original, "druid", 60, "balance")
    assert sum(context["full_point_source_allocation"].values()) == 51

    witness = paid_source_policy_stat_witness(
        selected, stat="spell_power", level=60, probe_deltas=(5., 20.),
        max_evaluations=4, schedule_incoming_attacks=True)
    assert witness["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
    assert witness["weight_s_saved_per_mob_per_unit"] > 0
    assert witness["baseline_seconds_per_mob"] > witness["perturbed_seconds_per_mob"]
    assert witness["paid_evaluations"] <= 4
    assert witness["policy_id"] in {p.id for p in selected.policies}


def test_real_p3_balance_uses_paid_sp_witness_not_epsilon():
    result = run_live(ROOT, "druid", 60, spec="balance")
    assert result["status"] == "PASS", result
    assert result["pass_count"] == result["reachability_count"], result
    witnesses = result["source_policy_stat_witnesses"]
    assert any(w["stat"] == "spell_power"
               and w["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
               and w["weight_s_saved_per_mob_per_unit"] > 0
               for w in witnesses), result
    assert result["real_measured_stat_weights"]["spell_power"] > 0
    assert result["behavior_probes_executed"] <= 44


def test_real_unrestricted_l40_p3_reuses_baseline_to_measure_spirit():
    result = run_live(ROOT, "druid", 40, spec="unrestricted")
    assert result["status"] == "PASS", result
    assert result["real_measured_stat_weights"]["spirit"] > 0, result
    spirit = next(
        witness for witness in result["source_policy_stat_witnesses"]
        if witness["stat"] == "spirit"
    )
    assert spirit["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", result
    assert spirit["baseline_reused"] is True, result
    assert result["behavior_probes_executed"] <= 44, result

def test_real_mage_and_priest_l20_p3_ignore_qualified_wand_proxy_for_equipped_weapon_weights():
    """Run both real P3 providers; a scenario wand proxy is not an equipped item."""
    for class_key in ("mage", "priest"):
        result = run_live(ROOT, class_key, 20, spec="unrestricted")
        reasons = set(result.get("reasons", ()))
        print(
            f"P3 qualified-wand diagnostic {class_key}: "
            f"status={result.get('status')} reasons={sorted(reasons)} "
            f"weights={result.get('real_measured_stat_weights')} "
            f"assertions={result.get('pass_count')}/{result.get('reachability_count')} "
            f"probes={result.get('behavior_probes_executed')} "
            f"slots={result.get('real_catalogue_slots_scored')}"
        )
        assert result.get("production_engine") == "gsim_CombatRuntime", result
        assert result.get("behavior_probes_executed", 0) > 0, result
        assert "MISSING_APPLICABLE_DPS_WEIGHT" not in reasons, result
        assert "MISSING_WEIGHT:mean_weapon_hit_damage" not in reasons, result
