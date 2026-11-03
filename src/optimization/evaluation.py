from __future__ import annotations

"""Canonical backend-neutral Evaluation value type for the optimizer.

This immutable score/result contract is independent of game facts and runtime.
Runtime-specific conversion and recovery adapters remain in src.game.evaluation.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.scenarios.timing import TIMING_CONTRACT_VERSION


@dataclass(frozen=True)
class Evaluation:
    score_s_per_100: float
    kill_s_per_100: float | None = None
    recovery_s_per_100: float | None = None
    travel_s_per_100: float | None = None
    mobs_per_hour: float | None = None
    resource_metrics: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    timing_contract: str = TIMING_CONTRACT_VERSION
    evaluation_scope: str = "solo_leveling"
    optimization_ready: bool = True
    provenance: Mapping[str, Any] = field(default_factory=dict)
    fidelity: Mapping[str, Any] = field(default_factory=dict)

    @property
    def seconds_per_mob(self) -> float:
        return float(self.score_s_per_100) / 100.0

    @property
    def timing_complete(self) -> bool:
        return all(v is not None for v in (self.kill_s_per_100, self.recovery_s_per_100, self.travel_s_per_100))

    @property
    def timing_residual_s_per_100(self) -> float | None:
        if not self.timing_complete:
            return None
        return float(self.score_s_per_100) - (
            float(self.kill_s_per_100) + float(self.recovery_s_per_100) + float(self.travel_s_per_100)
        )

    @property
    def timing_consistent(self) -> bool:
        residual = self.timing_residual_s_per_100
        if residual is None:
            return False
        return abs(residual) <= max(0.01, 1e-6 * max(1.0, abs(float(self.score_s_per_100))))

    @classmethod
    def from_published_row(cls, row: Mapping[str, Any]) -> "Evaluation":
        details = dict(row.get("details") or {})
        total = _float_or_none(row.get("score_s_per_100"))
        if total is None:
            spm = _float_or_none(row.get("seconds_per_mob"))
            total = (spm * 100.0) if spm is not None else (_float_or_none(details.get("total_s")) or 0.0)

        def per100(top_key: str, detail_key: str) -> float | None:
            top = _float_or_none(row.get(top_key))
            if top is not None:
                return 100.0 * top
            return _float_or_none(details.get(detail_key))

        mph = _float_or_none(row.get("mobs_per_hour"))
        if mph is None and total > 0:
            mph = 360000.0 / total
        return cls(
            score_s_per_100=float(total),
            kill_s_per_100=per100("kill_seconds_per_mob", "kill_s"),
            recovery_s_per_100=per100("recovery_seconds_per_mob", "recovery_s"),
            travel_s_per_100=per100("travel_seconds_per_mob", "travel_s"),
            mobs_per_hour=mph,
            diagnostics=details,
        )

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any], *, total_key: str = "total_s") -> "Evaluation":
        total = _float_or_none(raw.get(total_key))
        if total is None:
            total = _float_or_none(raw.get("score_s_per_100")) or 0.0
        mph = _float_or_none(raw.get("mobs_per_hour"))
        if mph is None and total > 0:
            mph = 360000.0 / total
        return cls(
            score_s_per_100=float(total),
            kill_s_per_100=_float_or_none(raw.get("kill_s")),
            recovery_s_per_100=_float_or_none(raw.get("recovery_s")),
            travel_s_per_100=_float_or_none(raw.get("travel_s")),
            mobs_per_hour=mph,
            resource_metrics={k: raw[k] for k in ("mana_spent", "mana_spent_per_mob", "rage_spent", "end_mana", "end_hp") if k in raw},
            diagnostics=raw,
        )

    def published_fields(self) -> dict[str, Any]:
        mph = self.mobs_per_hour
        if mph is None and self.optimization_ready and self.score_s_per_100 > 0:
            mph = 360000.0 / self.score_s_per_100
        return {
            "score_s_per_100": float(self.score_s_per_100),
            "mobs_per_hour": mph,
            "seconds_per_mob": self.seconds_per_mob if self.score_s_per_100 > 0 else None,
            "kill_seconds_per_mob": (float(self.kill_s_per_100) / 100.0 if self.kill_s_per_100 is not None else None),
            "recovery_seconds_per_mob": (float(self.recovery_s_per_100) / 100.0 if self.recovery_s_per_100 is not None else None),
            "travel_seconds_per_mob": (float(self.travel_s_per_100) / 100.0 if self.travel_s_per_100 is not None else None),
            "timing_contract": self.timing_contract,
            "timing_complete": self.timing_complete,
            "timing_consistent": self.timing_consistent,
            "timing_residual_seconds_per_mob": (self.timing_residual_s_per_100 / 100.0 if self.timing_residual_s_per_100 is not None else None),
            "evaluation_scope": self.evaluation_scope,
            "optimization_ready": bool(self.optimization_ready),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.published_fields(),
            "resource_metrics": dict(self.resource_metrics),
            "diagnostics": dict(self.diagnostics),
            "provenance": dict(self.provenance),
            "fidelity": dict(self.fidelity),
        }


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
