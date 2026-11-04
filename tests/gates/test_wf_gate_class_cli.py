import importlib.util
import json
import pytest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'tools' / 'wf_gate.py'
spec = importlib.util.spec_from_file_location('wf_gate', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


@pytest.mark.parametrize('gate', ('P1', 'P2'))
def test_retired_gates_are_not_executable_through_acceptance_cli(gate):
    assert gate not in mod.GATES
    with pytest.raises(SystemExit) as error:
        mod.main(['--class', 'druid', '--level', '20', '--gate', gate])
    assert error.value.code == 2


def test_all_reports_real_gate_names_and_missing_live_providers(monkeypatch, capsys):
    # Do not run expensive real source probes when testing only group dispatch.
    monkeypatch.setattr(mod, '_run_live_gate',
        lambda root, cl, lv, sp, gate, scenario="": {
            'status': 'BLOCKED', 'reasons': ['LIVE_GATE_RUNNER_MISSING:' + gate]})
    assert mod.main(['--class', 'warlock', '--level', '20', '--gate', 'all']) == 1
    data = json.loads(capsys.readouterr().out)
    assert len(data['results']) == 9
    assert [x['gate'] for x in data['results']] == list(mod.GATES)
    assert data['status'] == 'BLOCKED'


def test_p74_cli_preserves_frozen_paid_gear_and_search_metadata_on_fail(monkeypatch, capsys):
    """A real provider FAIL must retain its winner receipt, not become PASS."""
    from tools import wf_gate_p7_4_live
    monkeypatch.setattr(wf_gate_p7_4_live, "run_live", lambda *a, **k: {
        "status": "FAIL",
        "reasons": ["P7_4_FROZEN_STOCHASTIC_DPS_BELOW_REFERENCE_FLOOR"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "cold_winner_gear": [
            {"slot": 0, "item_id": 112, "enchant_id": None},
            {"slot": 1, "item_id": 225, "enchant_id": 201}],
        "winner_live_dps": 717.5,
        "winner_screen_dps": 720.0,
        "winner_selection": "paid_4x3_balanced_native_world_confirmed",
        "paid_balanced_finalists": 4,
        "paid_balanced_confirmed": 1,
        "source_candidate_failure_count": 17,
        "pinned_rust_unique_item_options": 321,
        "pinned_rust_unique_enchant_options": 22,
        "pinned_rust_item_options_applied": True,
        "native_source_revision": "native-reference-revision",
        "item_candidate_admission": "pinned_rust_items_jsonl",
        "paid_stochastic_finalists": 0,
        "paid_stochastic_confirmed_finalists": 0,
        "source_candidate_failures": ["SOURCE_REJECT_" + "x" * 300] * 5,
        "balanced_finalist_failures": ["BALANCED_TIMEOUT_" + "y" * 300] * 6,
        "paid_stochastic_finalist_failures": [],
        "frozen_stochastic_world_dps": 717.5,
        "frozen_stochastic_iterations": 1000,
    })
    assert mod.main(["--class", "druid", "--level", "60",
                     "--spec", "balance", "--gate", "P7.4"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "FAIL"
    receipt = result["results"][0]
    assert receipt["cold_winner_gear"] == [
        {"slot": 0, "item_id": 112, "enchant_id": None},
        {"slot": 1, "item_id": 225, "enchant_id": 201}]
    assert receipt["winner_live_dps"] == 717.5
    assert receipt["winner_screen_dps"] == 720.0
    assert receipt["winner_selection"] == "paid_4x3_balanced_native_world_confirmed"
    assert receipt["paid_balanced_finalists"] == 4
    assert receipt["paid_balanced_confirmed"] == 1
    assert receipt["source_candidate_failure_count"] == 17
    assert receipt["pinned_rust_unique_item_options"] == 321
    assert receipt["pinned_rust_unique_enchant_options"] == 22
    assert receipt["pinned_rust_item_options_applied"] is True
    assert receipt["native_source_revision"] == "native-reference-revision"
    assert receipt["item_candidate_admission"] == "pinned_rust_items_jsonl"
    # Do not publish the P7.4 provider's hard-coded stochastic placeholders.
    assert "paid_stochastic_finalists" not in receipt
    assert "paid_stochastic_confirmed_finalists" not in receipt
    assert "paid_stochastic_finalist_failures" not in receipt
    assert len(receipt["source_candidate_failures"]) == 4
    assert len(receipt["balanced_finalist_failures"]) == 4
    assert all(len(message) == len("SOURCE_REJECT_") + 300 for message in receipt["source_candidate_failures"])
    assert all(len(message) == 180 for message in receipt["balanced_finalist_failures"])
    assert receipt["status"] == "FAIL"


def test_p3_cli_preserves_native_item_options_partial_metadata(monkeypatch, capsys):
    report = {
        "status": "FAIL",
        "reasons": ["NATIVE_ITEM_OPTIONS_PARTIAL_LEVEL_UNKNOWN:2267"],
        "item_options_source": "MYTHICSIM_NATIVE_ITEM_OPTIONS",
        "native_item_options_status": "partial_level_unknown",
        "native_unverified_candidate_count": 2267,
        "native_excluded_non_client_item_count": 3075,
        "native_item_options_source": "mythicsim:data/items.jsonl+client:ItemSparse.RequiredLevel",
        "native_spell_coefficients_source": "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS",
        "native_spell_coefficients_engine_revision": "native-engine-revision",
        "native_spell_coefficients_applied": [{
            "action_id": "fireball:8401",
            "spell_id": 8401,
            "spell_power_coefficient": 0.857,
        }],
        "native_paid_winner_spell_probe_enabled": True,
        "real_catalogue_legal_items": 1314,
        "real_catalogue_slots_scored": 16,
        "real_native_representative_items_scored": 20,
        "real_source_search_evaluated": 123,
        "native_equipped_paid_attempts": 72,
        "p3_shared_budget_attempts": 65,
        "p3_native_pair_reserved_attempts": 58,
        "reachability_count": 12,
        "pass_count": 0,
    }
    monkeypatch.setattr(mod, "_run_live_gate", lambda *args, **kwargs: report)
    assert mod.main(["--class", "priest", "--level", "20", "--spec", "unrestricted",
                     "--gate", "P3"]) == 1
    result = json.loads(capsys.readouterr().out)
    row = result["results"][0]
    assert result["status"] == "FAIL"
    assert row["item_options_source"] == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
    assert row["native_item_options_status"] == "partial_level_unknown"
    assert row["native_unverified_candidate_count"] == 2267
    assert row["native_excluded_non_client_item_count"] == 3075
    assert row["native_item_options_source"] == report["native_item_options_source"]
    assert row["native_spell_coefficients_source"] == "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS"
    assert row["native_spell_coefficients_engine_revision"] == "native-engine-revision"
    assert row["native_spell_coefficients_applied"] == report["native_spell_coefficients_applied"]
    assert row["native_paid_winner_spell_probe_enabled"] is True
    assert row["real_catalogue_legal_items"] == 1314
    assert row["real_native_representative_items_scored"] == 20
    assert row["real_source_search_evaluated"] == 123
    assert row["native_equipped_paid_attempts"] == 72
    assert row["p3_shared_budget_attempts"] == 65
    assert row["p3_native_pair_reserved_attempts"] == 58



def test_p3_cli_preserves_native_shaman_spell_coefficient_error(monkeypatch, capsys):
    report = {
        "status": "FAIL",
        "reasons": ["NONPOSITIVE_RELEVANT_WEIGHT:spell_power"],
        "item_options_source": "MYTHICSIM_NATIVE_ITEM_OPTIONS",
        "native_spell_coefficients_error": (
            "P3_NATIVE_SHAMAN_LIGHTNING_BOLT_915_COEFFICIENT_UNAVAILABLE"),
        "native_spell_coefficients_applied": [],
        "native_paid_winner_spell_probe_enabled": False,
        "reachability_count": 204,
        "pass_count": 66,
    }
    monkeypatch.setattr(mod, "_run_live_gate", lambda *args, **kwargs: report)
    assert mod.main(["--class", "shaman", "--level", "20", "--spec", "unrestricted",
                     "--gate", "P3"]) == 1
    result = json.loads(capsys.readouterr().out)
    row = result["results"][0]
    assert result["status"] == "FAIL"
    assert row["native_spell_coefficients_error"] == (
        "P3_NATIVE_SHAMAN_LIGHTNING_BOLT_915_COEFFICIENT_UNAVAILABLE")
    assert row["native_spell_coefficients_applied"] == []
    assert row["native_paid_winner_spell_probe_enabled"] is False
    assert row["reachability_count"] == 204
    assert row["pass_count"] == 66
