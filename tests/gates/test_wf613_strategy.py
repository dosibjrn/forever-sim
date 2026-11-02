"""WF613 opt-in search policy: original structural repairs + real source generator.

Focused contracts cannot certify a 300s hybrid P7.5 gate. The separate
exact-HEAD Actions run executes the genuine selected Rust <-> 2D scorer.
"""
import copy
import importlib.util
from pathlib import Path
import random

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "integrations/mythicsim-rust"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, PATH / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request():
    return {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 100 + i} for i in range(16)]},
        "talentsString": "paid-legal-talent",
        "rotation": {"priorityList": [1, 2, 3]},
    }]}]}}


def test_wf613_starts_independently_and_accepts_only_finite_paid_scores():
    m = _load("wf613_strategy.py", "wf613_test1")
    c = m.WF613Controller()
    parent, axes, operator = c.propose(random.Random(1))
    assert parent is None and axes is None and operator == "fresh"
    assert c.paid == []
    with pytest.raises(ValueError, match="INVALID_SCORE"):
        c.observe(_request(), float("nan"), operator)
    assert not c.paid
    c.observe(_request(), 450.0, operator)
    assert len(c.paid) == 1 and c.best == 450.0


def test_wf613_six_original_structural_moves_and_same_paid_parent():
    m = _load("wf613_strategy.py", "wf613_test2")
    assert set(m.REPAIR_MOVES) == {
        ("talents",), ("talents", "rotation"), ("gear",),
        ("gear", "rotation"), ("rotation",), ("gear", "talents", "rotation")}
    c = m.WF613Controller()
    paid = _request()
    c.observe(paid, 500.0, "fresh")

    class ChooseRepair(random.Random):
        def choices(self, population, weights=None, k=1):
            if population == m.OPERATORS:
                return ["structural_repair"]
            return [population[0]]

    rng = ChooseRepair(10)
    proposals = [c.propose(rng) for _ in range(5)]
    assert len({axes for _, axes, _ in proposals}) == 5
    assert all(family == "structural_repair" for _, _, family in proposals)
    assert all(p == paid and p is not paid for p, _, _ in proposals)
    assert c.tries["structural_repair"] == 5
    # A mutation of one returned parent cannot contaminate siblings/paid archive.
    proposals[0][0]["raid"]["parties"][0]["players"][0]["talentsString"] = "changed"
    assert c.paid[0][1] == paid


def test_wf613_adaptive_operator_archive_and_rejection_safety():
    m = _load("wf613_strategy.py", "wf613_test3")
    c = m.WF613Controller()
    for i in range(100):
        q = _request()
        q["raid"]["parties"][0]["players"][0]["talentsString"] = "talent-" + str(i)
        c.observe(q, 100 + i, "fresh")
    assert len(c.paid) <= 48
    assert c.best == 199
    assert c.gains["fresh"] == 100
    assert c.diagnostics()["strategy"] == "wf613"
    assert set(c.tries) == set(m.OPERATORS)


def test_wf613_real_source_joint_adapter_keeps_unchanged_axes(monkeypatch):
    import sys
    monkeypatch.syspath_prepend(str(PATH))
    from p75_joint_search import make_candidate, player, validate, parse
    base = __import__("json").loads((
        ROOT / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json").read_text())
    paid = copy.deepcopy(base)
    pool = {i: [900000 + i * 100 + n for n in range(1, 10)] for i in range(16)}
    p = player(paid)
    original = copy.deepcopy(player(base))
    candidate = make_candidate(base, pool, random.Random(781),
                               elite=paid, repair_axes=("talents", "rotation"))
    c = player(candidate)
    assert c["equipment"] == original["equipment"]
    assert validate(parse(c["talentsString"]))
    assert candidate["encounter"] == base["encounter"]
    assert player(base) == original


def test_wf613_invalid_axes_are_rejected_and_default_stays_unchanged(monkeypatch):
    monkeypatch.syspath_prepend(str(PATH))
    from p75_joint_search import make_candidate, player
    import json
    base = json.loads((
        ROOT / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json").read_text())
    pool = {i: [900000 + i * 100 + n for n in range(1, 10)] for i in range(16)}
    with pytest.raises(ValueError, match="INVALID_REPAIR_AXES"):
        make_candidate(base, pool, random.Random(2), elite=base, repair_axes=("invented",))
    a = make_candidate(base, pool, random.Random(25), elite=base)
    b = make_candidate(base, pool, random.Random(25), elite=base, repair_axes=None)
    assert player(a) == player(b)
