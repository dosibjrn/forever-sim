from pathlib import Path

from src.service.intents import compile_intent
from src.service.executors import V2RunnerExecutor
from src.v2 import runtime_progress


def test_service_intent_defaults_to_two_workers_for_local_stack_budget():
    x = compile_intent({
        'action':'recompute_range','class_name':'druid',
        'from_level':11,'to_level':20,'depth':'standard',
    })
    assert x.request.config['workers'] == 2


def test_service_intent_accepts_explicit_worker_count():
    x = compile_intent({
        'action':'recompute_range','class_name':'paladin',
        'from_level':11,'to_level':20,'depth':'standard','workers':4,
    })
    assert x.request.config['workers'] == 4


def test_v2_execution_plan_forwards_candidate_worker_budget():
    x = compile_intent({
        'action':'recompute_range','class_name':'druid',
        'from_level':11,'to_level':20,'depth':'standard','workers':3,
    })
    job={'request':x.request.canonical_dict()}
    plan=V2RunnerExecutor().plan(job)
    i=plan.command.index('--workers')
    assert plan.command[i+1] == '3'


def test_candidate_worker_can_suppress_shared_runtime_progress(monkeypatch, tmp_path):
    monkeypatch.setenv('WOW_SIM_SUPPRESS_RUNTIME_PROGRESS','1')
    called=[]
    monkeypatch.setattr(runtime_progress, 'atomic_write_json', lambda *a, **k: called.append((a,k)))
    assert runtime_progress.emit_runtime_progress(force=True, phase='searching') is None
    assert called == []
