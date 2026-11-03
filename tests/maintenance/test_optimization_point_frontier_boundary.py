"""Source-free optimizer frontier and legacy traversal compatibility."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from src.optimization.point_frontier import generate_point_frontier
from src.optimization.talent_search import TalentAllocationOption

ROOT = Path(__file__).resolve().parents[2]


def _options():
    return (
        TalentAllocationOption("a", 2, frozenset({1, 2})),
        TalentAllocationOption("b", 1, frozenset({1})),
        TalentAllocationOption("unsupported", 1, frozenset()),
    )


def _validate(selection):
    if any(rank < 0 for rank in selection.values()):
        raise ValueError("negative rank")
    if sum(selection.values()) > 2:
        raise ValueError("over budget")
    if selection.get("b", 0) and not selection.get("a", 0):
        raise ValueError("b requires a")


def test_optimizer_frontier_import_does_not_load_gameir():
    code = """
import sys
from src.optimization.point_frontier import generate_point_frontier
assert callable(generate_point_frontier)
assert 'src.game' not in sys.modules
assert 'src.game.model.ir' not in sys.modules
"""
    run = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, text=True,
        capture_output=True, timeout=30, check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr


def test_one_point_order_unsupported_ranks_and_legal_rejection():
    assert generate_point_frontier(
        _options(), {"a": 1}, max_points=2, validate_selection=_validate
    ) == [{"a": 2}, {"a": 1, "b": 1}]
    assert generate_point_frontier(
        _options(), {}, max_points=2, validate_selection=_validate
    ) == [{"a": 1}]


def test_full_budget_transfers_deduplicate_and_preserve_order():
    assert generate_point_frontier(
        _options(), {"a": 2}, max_points=2, validate_selection=_validate
    ) == [{"a": 1, "b": 1}]
    assert generate_point_frontier(
        _options(), {"a": 2}, max_points=2,
        validate_selection=_validate, allow_transfers=False,
    ) == []


def test_invalid_start_fails_closed_and_only_valueerror_is_candidate_rejection():
    with pytest.raises(ValueError, match="negative"):
        generate_point_frontier(
            _options(), {"a": -1}, max_points=2, validate_selection=_validate
        )

    def runtime_failure(_selection):
        raise RuntimeError("native transport unavailable")

    with pytest.raises(RuntimeError, match="native transport"):
        generate_point_frontier(
            _options(), {}, max_points=2, validate_selection=runtime_failure
        )


def test_source_frontier_adapter_preserves_source_order_and_legality(monkeypatch):
    from types import SimpleNamespace
    import src.v2.source_legal_beam as adapter

    def definition(name, max_rank, supported):
        return SimpleNamespace(
            id=name, max_rank=max_rank,
            ranks=tuple(SimpleNamespace(rank=rank, modifiers=("effect",))
                        for rank in supported),
        )

    definitions = (
        definition("a", 2, (1, 2)),
        definition("b", 1, (1,)),
        definition("unsupported", 1, ()),
    )
    monkeypatch.setattr(adapter, "executable_talent_definitions", lambda _source: definitions)
    monkeypatch.setattr(
        adapter, "available_talent_points",
        lambda level, bonus_talent_points=0: 2,
    )
    monkeypatch.setattr(
        adapter, "validate_talent_selection",
        lambda source, selection, *, level, bonus_talent_points=0: _validate(selection),
    )
    source = object()
    assert adapter.legal_point_frontier(source, {"a": 1}, level=20) == [
        {"a": 2}, {"a": 1, "b": 1}
    ]
    assert adapter.legal_point_frontier(source, {"a": 2}, level=20) == [
        {"a": 1, "b": 1}
    ]
    assert adapter.legal_point_frontier(
        source, {"a": 2}, level=20, allow_transfers=False
    ) == []
