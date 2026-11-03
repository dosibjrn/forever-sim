"""Real source-backed P3 partials exercise the production implementation.

These are focused coverage regressions, NOT full gate PASS acceptance.
"""
from tools.wf_gate import _run_live_gate, ROOT
from tools.m1_progress import record_partial


def _assert_partial_source_execution(report, gate):
    assert report["status"] in {"PASS", "FAIL"}, (gate, report.get("reasons", [])[:4])
    n, d = report["pass_count"], report["reachability_count"]
    assert type(n) is int and type(d) is int
    assert 0 <= n <= d and d > 0
    assert report["behavior_probes_executed"] >= 0
    assert report["partial_scope"]
    return n, d


def test_druid_l60_balance_p3_actual_paid_item_stat_weight_fraction():
    report = _run_live_gate(ROOT, "druid", 60, "balance", "P3")
    n, d = _assert_partial_source_execution(report, "P3")
    assert report["production_engine"] == "gsim_CombatRuntime"
    assert report["behavior_probes_executed"] > 0
    assert report["real_source_search_evaluated"] > 0
    assert report["real_catalogue_top5_items_scored"] > 0
    assert report["real_measured_stat_weight_axes"]
    assert report["partial_scope"] == "CURRENT_SOURCE_TOP5_ITEM_STAT_WEIGHT_ASSERTIONS"
    assert report["coverage_scope_complete"] is False
