from __future__ import annotations

"""Single Forever execution entrypoint.

The top-level runner dispatches only by ruleset.  Search-strategy differences
are declared by ClassModel, so adding a class does not add another class-name
branch to runner.py.  Both strategies publish canonical DecisionResult routes.
"""

from typing import Any, Callable

from .class_model import ClassModel, active_class_model


AnalyticRunner = Callable[[Any, ClassModel], Any]


def run(args: Any, *, analytic_runner: AnalyticRunner) -> Any:
    model = active_class_model()
    strategy = str(model.runner_strategy())
    if strategy == "analytic_views":
        return analytic_runner(args, model)
    if strategy == "continuity_beam":
        from .experimental_classes import run as run_continuity_beam
        return run_continuity_beam(args, model=model)
    raise ValueError(f"unsupported Forever runner strategy {strategy!r} for {model.name}")
