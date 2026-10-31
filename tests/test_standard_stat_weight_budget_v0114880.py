from src.service.intents import compile_intent
from src.service.executors import V2RunnerExecutor


def _job(compiled):
    return {"request": compiled.request.canonical_dict()}


def test_standard_recompute_budgets_stat_weights_to_top_one():
    x=compile_intent({"action":"recompute_range","class_name":"druid","from_level":11,"to_level":20,"depth":"standard","workers":2})
    assert x.request.config["beam_width"] == 10
    assert x.request.config["family_keep"] == 1
    assert x.request.config["final_k"] == 8
    assert x.request.config["stat_weight_top_k"] == 1
    cmd=V2RunnerExecutor().plan(_job(x)).command
    assert cmd[cmd.index("--stat-weight-top-k")+1] == "1"


def test_wide_and_deep_have_bounded_presentation_derivative_budgets():
    wide=compile_intent({"action":"recompute_range","class_name":"druid","from_level":11,"to_level":20,"depth":"wide"})
    deep=compile_intent({"action":"recompute_range","class_name":"druid","from_level":11,"to_level":20,"depth":"deep"})
    assert wide.request.config["stat_weight_top_k"] == 3
    assert deep.request.config["stat_weight_top_k"] == 5
