from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

from .catalogue import ItemCatalogue, RequiredLevelOrigin


@dataclass(frozen=True)
class RequiredLevelModelRow:
    item_level: int
    observed_sample_count: int
    median_required_level: float
    p25_required_level: float | None
    p75_required_level: float | None
    model_status: str
    computed_at: str
    source_catalogue_hash: str

    @property
    def inferred_required_level(self) -> int:
        # Avoid Python's bankers rounding: an x.5 median is rounded up deterministically.
        return max(1, int(math.floor(self.median_required_level + 0.5)))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _percentile(values: list[int], q: float) -> float:
    """Linear percentile equivalent to a small, dependency-free quantile helper."""
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(ordered[lo])
    frac = pos - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def _observed_source_hash(samples: dict[int, list[int]]) -> str:
    payload = [[ilvl, sorted(levels)] for ilvl, levels in sorted(samples.items())]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def build_required_level_model(
    catalogue: ItemCatalogue,
    *,
    computed_at: str | None = None,
) -> list[RequiredLevelModelRow]:
    """Rebuild the canonical ilvl -> required-level model from observed data only.

    Rows with inferred required levels are deliberately excluded from the training
    sample, preventing inferred values from recursively becoming evidence.
    Empty ilvl buckets between observed buckets are linearly interpolated.  Gaps at
    either edge are not invented; a future observed sample can extend the model.
    """
    samples: dict[int, list[int]] = {}
    for item in catalogue.list_items():
        if (
            item.item_level is not None
            and item.required_level is not None
            and item.required_level_origin == RequiredLevelOrigin.OBSERVED.value
        ):
            samples.setdefault(int(item.item_level), []).append(int(item.required_level))

    catalogue.clear_required_level_model()
    if not samples:
        return []

    stamp = computed_at or _iso_now()
    source_hash = _observed_source_hash(samples)
    observed_rows: dict[int, RequiredLevelModelRow] = {}
    for ilvl, values in sorted(samples.items()):
        observed_rows[ilvl] = RequiredLevelModelRow(
            item_level=ilvl,
            observed_sample_count=len(values),
            median_required_level=float(statistics.median(values)),
            p25_required_level=_percentile(values, 0.25),
            p75_required_level=_percentile(values, 0.75),
            model_status="observed_median",
            computed_at=stamp,
            source_catalogue_hash=source_hash,
        )

    rows: list[RequiredLevelModelRow] = []
    known = sorted(observed_rows)
    for ilvl in range(known[0], known[-1] + 1):
        direct = observed_rows.get(ilvl)
        if direct is not None:
            rows.append(direct)
            continue
        lower = max(x for x in known if x < ilvl)
        upper = min(x for x in known if x > ilvl)
        lo = observed_rows[lower].median_required_level
        hi = observed_rows[upper].median_required_level
        fraction = (ilvl - lower) / (upper - lower)
        rows.append(
            RequiredLevelModelRow(
                item_level=ilvl,
                observed_sample_count=0,
                median_required_level=float(lo + (hi - lo) * fraction),
                p25_required_level=None,
                p75_required_level=None,
                model_status="interpolated",
                computed_at=stamp,
                source_catalogue_hash=source_hash,
            )
        )

    catalogue.replace_required_level_model(rows)
    return rows


def apply_inferred_required_levels(catalogue: ItemCatalogue) -> int:
    """Fill missing required levels from the canonical model without touching observed rows."""
    model = {row.item_level: row for row in catalogue.list_required_level_model()}
    changed = 0
    for item in catalogue.list_items():
        if item.required_level is not None or item.item_level is None:
            continue
        row = model.get(int(item.item_level))
        if row is None:
            continue
        origin = (
            RequiredLevelOrigin.INFERRED_MEDIAN.value
            if row.model_status == "observed_median"
            else RequiredLevelOrigin.INFERRED_INTERPOLATED.value
        )
        catalogue.set_inferred_required_level(
            item.item_id,
            row.inferred_required_level,
            origin=origin,
        )
        changed += 1
    return changed

@dataclass(frozen=True)
class AvailabilityFloorModel:
    degree: int
    quadratic_a: float
    linear_b: float
    intercept_c: float
    rmse: float
    lower_sigma: float
    observed_sample_count: int
    retained_sample_count: int
    excluded_low_outliers: int
    computed_at: str
    source_catalogue_hash: str
    model_id: int = 1

    def predict(self, item_level: int | float) -> float:
        x = float(item_level)
        return self.quadratic_a * x * x + self.linear_b * x + self.intercept_c

    def floor_for_item_level(self, item_level: int | float) -> int:
        return max(1, int(math.ceil(self.predict(item_level) - self.lower_sigma * self.rmse)))


def _solve3(m: list[list[float]], v: list[float]) -> tuple[float, float, float]:
    a = [row[:] + [float(rhs)] for row, rhs in zip(m, v)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("singular quadratic fit")
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [x / scale for x in a[col]]
        for r in range(3):
            if r == col:
                continue
            factor = a[r][col]
            a[r] = [x - factor * y for x, y in zip(a[r], a[col])]
    return a[0][3], a[1][3], a[2][3]


def _quadratic_fit(samples: list[tuple[float, float]]) -> tuple[float, float, float]:
    n = float(len(samples))
    sx = sum(x for x, _ in samples); sx2 = sum(x*x for x, _ in samples)
    sx3 = sum(x*x*x for x, _ in samples); sx4 = sum(x*x*x*x for x, _ in samples)
    sy = sum(y for _, y in samples); sxy = sum(x*y for x, y in samples); sx2y = sum(x*x*y for x, y in samples)
    return _solve3([[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, n]], [sx2y, sxy, sy])


def build_availability_floor_model(
    catalogue: ItemCatalogue,
    *,
    lower_sigma: float = 2.5,
    outlier_sigma: float = 2.5,
    computed_at: str | None = None,
) -> AvailabilityFloorModel:
    """Fit a robust quadratic lower availability bound from observed reqlevels.

    Only anomalously *low* reqlevel observations are iteratively excluded. High
    requirements remain evidence because they are conservative for availability.
    Runtime requires both source reqlevel and this lower bound.
    """
    raw = [
        (float(x.item_level), float(x.required_level))
        for x in catalogue.list_items()
        if x.item_level is not None and x.required_level is not None
        and x.required_level_origin == RequiredLevelOrigin.OBSERVED.value
    ]
    if len(raw) < 3:
        raise ValueError("availability floor requires at least three observed samples")
    kept = list(raw)
    for _ in range(20):
        qa, lb, ic = _quadratic_fit(kept)
        residuals = [y - (qa*x*x + lb*x + ic) for x, y in kept]
        rmse = math.sqrt(sum(r*r for r in residuals) / len(residuals))
        if rmse <= 0:
            break
        new_kept = [sample for sample, residual in zip(kept, residuals) if residual >= -outlier_sigma * rmse]
        if len(new_kept) == len(kept):
            break
        if len(new_kept) < 3:
            raise ValueError("availability outlier rejection removed too many samples")
        kept = new_kept
    qa, lb, ic = _quadratic_fit(kept)
    residuals = [y - (qa*x*x + lb*x + ic) for x, y in kept]
    rmse = math.sqrt(sum(r*r for r in residuals) / len(residuals))
    source_hash = hashlib.sha256(json.dumps(sorted(raw), separators=(",", ":")).encode()).hexdigest()
    model = AvailabilityFloorModel(
        degree=2, quadratic_a=qa, linear_b=lb, intercept_c=ic, rmse=rmse,
        lower_sigma=float(lower_sigma), observed_sample_count=len(raw), retained_sample_count=len(kept),
        excluded_low_outliers=len(raw)-len(kept), computed_at=computed_at or _iso_now(),
        source_catalogue_hash=source_hash,
    )
    catalogue.replace_availability_floor_model(model)
    return model
