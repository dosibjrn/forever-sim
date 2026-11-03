"""P1 source-index level hints are not proof of acquisition.

A missing or partial source-legality ledger must fail closed even if a source
action happens to be implemented by GameIR. No real P1 gate is certified here:
these are focused inventory contract tests independent of a class fixture.
"""
from types import SimpleNamespace as N

from tools.wf_gate_p1_live import audit_inventory


def _row(sid):
    return {
        "spell_id":sid,"name":f"Source Ability {sid}",
        "rank_hint":1,"level_hint":20,"source_url":"https://example.invalid/source",
        "raw_listview_json":'{"envChange":{"after":{"text":"Deals damage"}}}',
    }


def _audit(rows, legality):
    actions=tuple(
        N(id=f"source_spell:{r['spell_id']}",owner_actor_id="me",
          effects=(object(),),requirements=(),
          provenance={"source_spell_id":r["spell_id"]},metadata={})
        for r in rows
    )
    ir=N(actor=N(id="me"),actions=actions,modes=(),resources=())
    def policy(action_id):
        return N(rules=(N(action_id=action_id),))
    return audit_inventory(
        rows,ir,parser=lambda a:{int(a.id.split(":")[-1])},
        source_classifier=lambda row,raw:{"role":"ABILITY"},
        policy_builder=lambda ir,rules:policy(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[policy(a.id) for a in actions],
        executor=lambda ir,action:{"status":"executed","effect_observed":True},
        effect_checker=lambda effect:"direct_damage",source_statuses=legality,
    )


def test_empty_explicit_acquisition_ledger_never_falls_back_to_level_hint():
    report=_audit([_row(467)],{})
    assert report["status"]=="FAIL"
    assert report["production_runtime_exercises"]==0
    assert any(p["code"]=="SOURCE_ACTION_LEGALITY_UNRESOLVED"
               and p["ability"].startswith("467:") for p in report["problems"])
    assert any(p["detail"]=="SOURCE_ROW_NOT_IN_LEGALITY_FRONTIER"
               for p in report["problems"])


def test_partial_ledger_does_not_grant_uncovered_source_rank():
    report=_audit([_row(467),_row(740)],{467:("LEGAL","verified source")})
    assert report["status"]=="FAIL"
    assert report["checked_source_abilities"]==1
    assert report["production_runtime_exercises"]==1
    assert any(p["code"]=="SOURCE_ACTION_LEGALITY_UNRESOLVED"
               and p["ability"].startswith("740:") for p in report["problems"])


def test_explicit_illegal_acquisition_rejects_optimizer_reachable_cast():
    report=_audit([_row(769)],{769:("ILLEGAL","not acquired in this snapshot")})
    assert report["status"]=="FAIL"
    assert report["production_runtime_exercises"]==0
    assert "ILLEGAL_SOURCE_ACTION_ENTERED_GAME_IR" in {
        p["code"] for p in report["problems"]
    }


def test_explicit_legal_rank_still_uses_real_executor_and_optimizer_path():
    report=_audit([_row(467)],{467:("LEGAL","verified acquisition source")})
    assert report["status"]=="PASS",report["problems"]
    assert report["production_runtime_exercises"]==1
    assert report["checked_source_abilities"]==1


def test_legacy_audit_without_any_ledger_is_not_silently_changed():
    # Unit-only callers that explicitly OMIT the ledger preserve their old
    # behavior; real run_live always supplies an explicit source ledger.
    report=_audit([_row(467)],None)
    assert report["status"]=="PASS"


def test_unindexed_learned_spellbook_row_surfaces_in_gate_reasons():
    from tools.wf_gate_p1_live import _complete_spellbook_problem_reporting
    report={
        "status":"PASS","problem_count":0,"problems":[],
        "spellbook_missing_learned_rows":[{"name":"Missing sourced ability","learned_level":60}],
    }
    _complete_spellbook_problem_reporting(report)
    assert report["status"]=="FAIL"
    assert report["problem_count"]==1
    assert report["problems"][0]["code"]=="SOURCE_SPELLBOOK_LEARNED_ROW_NOT_IN_INDEX"
    assert "SOURCE_SPELLBOOK_LEARNED_ROW_NOT_IN_INDEX" in report["reasons"][0]


def test_no_spellbook_gap_preserves_prior_gate_problem_and_reason():
    from tools.wf_gate_p1_live import _complete_spellbook_problem_reporting
    report={
        "status":"FAIL","problem_count":1,
        "problems":[{"code":"SOURCE_ACTION_LEGALITY_UNRESOLVED",
                     "ability":"740:Tranquility:rank=1:level=30",
                     "detail":"INDEX_LEVEL_HINT_IS_NOT_ACQUISITION"}],
        "spellbook_missing_learned_rows":[],
    }
    _complete_spellbook_problem_reporting(report)
    assert report["status"]=="FAIL"
    assert report["problem_count"]==1
    assert len(report["reasons"])==1
    assert report["reasons"][0].startswith("SOURCE_ACTION_LEGALITY_UNRESOLVED:740:Tranquility")
