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
        "winner_selection": "paid_2x24_stochastic_live_native_finalist",
        "paid_stochastic_finalists": 4,
        "source_candidate_failures": ["SOURCE_REJECT_" + "x" * 300] * 5,
        "paid_stochastic_finalist_failures": ["NATIVE_TIMEOUT_" + "y" * 300] * 6,
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
    assert receipt["winner_selection"] == "paid_2x24_stochastic_live_native_finalist"
    assert receipt["paid_stochastic_finalists"] == 4
    assert len(receipt["source_candidate_failures"]) == 4
    assert len(receipt["paid_stochastic_finalist_failures"]) == 4
    assert all(len(message) == 180 for name in
               ("source_candidate_failures", "paid_stochastic_finalist_failures")
               for message in receipt[name])
    assert receipt["status"] == "FAIL"
