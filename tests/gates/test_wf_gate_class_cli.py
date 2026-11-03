import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'tools' / 'wf_gate.py'
spec = importlib.util.spec_from_file_location('wf_gate', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def write(tmp, cl, lv, gate, **kw):
    p = tmp / cl / f'L{lv}' / 'unrestricted' / f'{gate}.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    obj = {'class':cl,'level':lv,'spec':'unrestricted','gate':gate,
           'source_id':'canonical-db-sha', 'engine_id':'engine-sha','scenario_id':'encounter-sha', **kw}
    p.write_text(json.dumps(obj))
    return p


def test_json_can_be_diagnosed_but_never_certifies_live_p4_p5_p6(tmp_path,capsys):
    common=dict(unlock_coverage_pass=True,talent_gear_apl_jointly_searched=True,
                full_legal_builds=True,complete_100mob_replays=4,mob_count=100)
    write(tmp_path,'druid',30,'P4', search_wall_s=29.8, unique_full_builds=100,
          best_full_s_per_mob=12.6,**common)
    write(tmp_path,'druid',30,'P5', search_wall_s=299.8, unique_full_builds=1200,
          best_full_s_per_mob=12.5,**common)
    write(tmp_path,'druid',30,'P6', s_per_mob_30=12.6, s_per_mob_300=12.5,
          independent_replays_same_scenario=True)
    # Historical validator tests schema consistency, not provenance/execution.
    p4=mod.evaluate(tmp_path,'druid',30,'unrestricted','P4',{})
    p5=mod.evaluate(tmp_path,'druid',30,'unrestricted','P5',{'P4':p4})
    assert p4['status']=='PASS' and p5['status']=='PASS'
    # Critically: the public acceptance CLI refuses to accept these JSONs.
    assert mod.main(['--class','druid','--level','30','--gate','P6',
                     '--evidence-dir',str(tmp_path)]) == 1
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='BLOCKED'
    assert result['results'][0]['reasons'][0].startswith('LIVE_GATE_RUNNER_MISSING')


def test_all_reports_only_active_gate_names_and_missing_live_providers(tmp_path,monkeypatch,capsys):
    # Do not run expensive real source probes when testing only group dispatch.
    monkeypatch.setattr(mod,'_run_live_gate',
        lambda root,cl,lv,sp,g: {
            'status':'BLOCKED','reasons':['LIVE_GATE_RUNNER_MISSING:'+g]})
    assert mod.main(['--class','warlock','--level','20','--gate','all',
                     '--evidence-dir',str(tmp_path)]) == 1
    data=json.loads(capsys.readouterr().out)
    assert len(data['results'])==9
    assert [x['gate'] for x in data['results']]==list(mod.GATES)
    assert data['status']=='BLOCKED'



def test_retired_p1_p2_gate_names_are_rejected():
    import pytest
    for retired in ("P1", "P2"):
        with pytest.raises(SystemExit):
            mod.main(["--class", "druid", "--level", "20", "--gate", retired])

def test_legacy_p7_json_is_never_current_p7_acceptance(tmp_path,capsys):
    common=dict(legacy_winner_full_configuration_replayed_in_new_engine=True,
                both_configurations_same_100mob_scenario=True,
                legacy_winner_on_new_engine_s_per_mob=17.2)
    write(tmp_path,'mage',20,'P7',new_winner_on_new_engine_s_per_mob=16.8,**common)
    assert mod.evaluate(tmp_path,'mage',20,'unrestricted','P7',{})['status']=='PASS'
    assert mod.main(['--class','mage','--level','20','--gate','P7',
                     '--evidence-dir',str(tmp_path)]) == 1
    output=json.loads(capsys.readouterr().out)
    assert output['status']=='BLOCKED'
    assert [r['gate'] for r in output['results']]==[f'P7.{i}' for i in range(1,6)]


def test_p74_cli_preserves_frozen_paid_gear_and_search_metadata_on_fail(
        monkeypatch, capsys):
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
