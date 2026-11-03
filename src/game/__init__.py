"""Generic WoW game model and runtime foundations.

Keep the transitional Python combat engine out of lightweight package imports.
Legacy Evaluation callers still resolve the same public names on demand.
"""

__all__ = ("Evaluation", "evaluation_from_combat_timeline")


def __getattr__(name: str):
    if name in __all__:
        from .evaluation import Evaluation, evaluation_from_combat_timeline
        return {
            "Evaluation": Evaluation,
            "evaluation_from_combat_timeline": evaluation_from_combat_timeline,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
