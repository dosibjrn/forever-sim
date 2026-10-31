from __future__ import annotations

"""Explicit Forever class-plugin registry.

The shared optimizer should not grow class-name branches in orchestration code.
Each supported Forever class therefore has an explicit ClassModel type, even
while Hunter/Druid/Paladin still delegate their bundled scorer fixed points to
legacy engine functions.  Mechanics stay in the engine modules; these adapters
are the stable seam through which those backends can be peeled apart later.
"""

from typing import Any

from .class_model import EngineClassModel, ClassModel
from .mage_class_model import MageClassModel


class ForeverBundledClassModel(EngineClassModel):
    """Compatibility seam for scorer backends whose fixed point is still bundled."""

    def runner_strategy(self) -> str:
        return "continuity_beam"


class HunterClassModel(ForeverBundledClassModel):
    pass


class DruidClassModel(ForeverBundledClassModel):
    pass


class PaladinClassModel(ForeverBundledClassModel):
    pass


class WarriorClassModel(ForeverBundledClassModel):
    pass


_MODELS: dict[str, type[ClassModel]] = {
    "mage": MageClassModel,
    "hunter": HunterClassModel,
    "druid": DruidClassModel,
    "paladin": PaladinClassModel,
    "warrior": WarriorClassModel,
}


def create_forever_class_model(engine: Any) -> ClassModel:
    name = str(getattr(engine, "CLASS_NAME", "")).strip().lower()
    try:
        cls = _MODELS[name]
    except KeyError as exc:
        raise ValueError(f"no Forever ClassModel registered for {name or '<unknown>'}") from exc
    return cls(engine)
