from src.listener import DECISIONS_HTML
from src.v2.talentsforever_compare import talentsforever_allocation_at_level

KNOWN_URL = "https://talentsforever.com/druid/60/5032220115501351--505203-6"


def test_i24_talentsforever_link_resolves_exact_current_prefix():
    out = talentsforever_allocation_at_level(KNOWN_URL, expected_class="druid", selected_level=23)
    assert out["selected_level"] == 23
    assert out["points"] == 14
    assert sum(out["talent_ranks"].values()) == 14
    assert out["progression_source"] == "offline_source_leveling_order"
    assert out["source_url"] == KNOWN_URL


def test_i24_listener_accepts_talentsforever_and_queues_missing_corridor():
    html = DECISIONS_HTML
    assert "Paste your current allocation or a TalentsForever build URL" in html
    assert "isTalentsForeverUrl" in html
    assert "source_url:sourceUrl||undefined" in html
    assert "Queue required calculations" in html
    assert "queueContinuationCalculations" in html
    assert "continuation_constraint" in html
    assert "beam_width:128" in html
    assert "family_keep:16" in html
    assert "final_k:64" in html
    assert "Continuation remains fail-closed until the new publication contains this corridor" in html


def test_i24_constraint_api_resolves_url_server_side_not_in_javascript():
    import inspect
    import src.listener as listener
    source = inspect.getsource(listener.Handler.do_POST)
    assert "talentsforever_allocation_at_level" in source
    assert "constraint['at_level_talent_allocation_exact']" in source
    assert "result['current_talents_source']" in source


def test_i24_recovery_job_metadata_is_service_safe_and_deep_search_flags_survive():
    from src.service.models import JobRequest
    from src.service.executors import V2RunnerExecutor
    req = JobRequest(
        ruleset="forever", class_name="druid", start_level=10, end_level=23,
        objective="cumulative", endpoint_mode="smooth",
        config={
            "workers": 1, "beam_width": 128, "family_keep": 16, "final_k": 64,
            "stat_weight_top_k": 1,
            "continuation_constraint": {
                "at_level": 20,
                "at_level_talent_allocation_exact": {"improved_wrath": 5},
            },
        },
    )
    job = {"request": req.canonical_dict()}
    plan = V2RunnerExecutor().plan(job)
    joined = " ".join(plan.command)
    assert "--beam-width 128" in joined
    assert "--family-keep 16" in joined
    assert "--final-k 64" in joined
    assert "--stat-weight-top-k 1" in joined
