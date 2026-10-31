from __future__ import annotations

"""Shared stat-weight contract for all class backends.

The optimizer's public gearing contract is class agnostic: a backend may expose
an analytic local surrogate gradient, a legacy finite-difference diagnostic, or
no stat model yet.  This module owns the common schema/normalization so callers
and the listener do not need Mage/Paladin/Druid branches.

Analytic providers return derivatives of the optimizer objective (seconds per
100 mobs; lower is better) with respect to native stat units.  This module turns
those derivatives into positive "seconds saved" weights and common relative
ratios.  The discrete/event simulator remains the validation authority; the
analytic gradient is intentionally a smooth local gearing model.
"""

from typing import Any, Iterable, Mapping

_EPS = 1e-12


def _status_row(value: Any) -> dict:
    if isinstance(value, Mapping):
        row=dict(value)
        row["status"]=str(row.get("status") or "not_probeable")
        return row
    return {"status":str(value)}


def normalize_objective_gradient(
    *,
    baseline_s_per_100: float,
    objective_gradient: Mapping[str, float],
    method: str,
    components: Mapping[str, Any] | None = None,
    reference_stat: str | None = None,
    note: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    stat_status: Mapping[str, Any] | None = None,
    declared_stats: Iterable[str] | None = None,
) -> dict:
    """Normalize d(objective)/d(stat) into the shared status-aware schema.

    ``objective_gradient`` uses the mathematical sign convention: a useful stat
    normally has a *negative* derivative because it lowers seconds/100 mobs.
    Player-facing weights use the opposite sign.  M44 makes availability
    explicit: a measured numerical zero is different from ``not_modeled`` or
    ``not_probeable``.
    """
    grads = {str(k): float(v) for k, v in objective_gradient.items()}
    values = {k: -v for k, v in grads.items()}
    statuses={str(k):_status_row(v) for k,v in (stat_status or {}).items()}
    all_stats=[]
    for k in list(grads)+list(declared_stats or ())+list(statuses):
        k=str(k)
        if k not in all_stats:
            all_stats.append(k)

    # Prefer a meaningful domain reference, but only among measured rows.
    measured_values={k:v for k,v in values.items() if statuses.get(k,{}).get("status","measured")=="measured"}
    ref = str(reference_stat) if reference_stat in measured_values else None
    if ref is None:
        for candidate in ("spell_power", "spell_damage", "strength", "agility", "weapon_dps", "intellect"):
            if candidate in measured_values and abs(measured_values[candidate]) > _EPS:
                ref = candidate
                break
    if ref is None and measured_values:
        ref = max(measured_values, key=lambda k: abs(measured_values[k]))

    ref_value = measured_values.get(ref, 0.0) if ref is not None else 0.0
    int_value = measured_values.get("intellect", 0.0)
    sp_value = measured_values.get("spell_power", 0.0)
    stats: dict[str, dict] = {}
    for stat in all_stats:
        status=dict(statuses.get(stat) or {"status":"measured" if stat in grads else "not_probeable"})
        state=str(status.get("status") or "not_probeable")
        if state not in {"measured","not_modeled","not_probeable"}:
            raise ValueError(f"invalid stat-weight status {state!r} for {stat}")
        row={**status,"status":state}
        if state == "measured":
            if stat not in grads:
                raise ValueError(f"measured stat {stat!r} requires objective_gradient")
            value=values[stat]
            row.update({
                "objective_derivative_s_per_100_per_point": grads[stat],
                "seconds_saved_per_100_per_point": value,
                "normalized_to_reference": (value / ref_value) if abs(ref_value) > _EPS else None,
                "reference_stat": ref,
                "normalized_to_spell_power": (value / sp_value) if abs(sp_value) > _EPS else None,
                "value_in_intellect": (value / int_value) if abs(int_value) > _EPS else None,
                "points_per_one_intellect": (int_value / value) if value > _EPS and int_value > _EPS else None,
            })
        else:
            row.setdefault("reference_stat",ref)
        if components and stat in components:
            row["components"] = components[stat]
        stats[stat] = row

    out = {
        "schema_version": 3,
        "method": str(method),
        "analytical": True,
        "baseline_s_per_100": float(baseline_s_per_100),
        "unit": "seconds_saved_per_100_mobs_per_stat_point",
        "reference_stat": ref,
        "stats": stats,
        "status_contract": {
            "measured":"modeled and marginal value measured; zero is a real measured zero",
            "not_modeled":"stat is intentionally outside this backend model",
            "not_probeable":"mechanic is modeled but this scorer cannot publish a reliable marginal probe",
        },
    }
    if note:
        out["note"] = str(note)
    if metadata:
        out["metadata"] = dict(metadata)
    return out


def apply_equal_item_budget_projection(weights: Mapping[str, Any], budget_model: Mapping[str, Any] | None) -> dict:
    """Attach empirical equal-item-budget values while preserving native gradients.

    ``budget_model['units_per_budget']`` says how many native points of a stat
    correspond to one observed peer-item exchange chunk.  Multiplying the
    native derivative by that amount answers the practical gearing question:
    which stat direction buys the most objective improvement for a comparable
    itemization chunk?  Missing stats remain raw-only rather than being guessed.
    """
    out = dict(weights or {})
    stats = {str(k): dict(v or {}) for k, v in (out.get("stats") or {}).items()}
    out["stats"] = stats
    if not budget_model:
        return out
    units = {str(k): float(v) for k, v in (budget_model.get("units_per_budget") or {}).items() if float(v) > 0.0}
    if not units:
        return out

    budget_values: dict[str, float] = {}
    for stat, row in stats.items():
        amount = units.get(stat)
        if amount is None:
            continue
        if row.get("status","measured") != "measured" or row.get("seconds_saved_per_100_per_point") is None:
            continue
        native = float(row["seconds_saved_per_100_per_point"])
        value = native * amount
        row["empirical_units_per_equal_budget"] = amount
        row["seconds_saved_per_100_per_equal_budget"] = value
        budget_values[stat] = value

    positive = {k: v for k, v in budget_values.items() if v > _EPS}
    ref = out.get("reference_stat") if out.get("reference_stat") in positive else None
    if ref is None and positive:
        ref = max(positive, key=positive.get)
    ref_value = positive.get(ref, 0.0) if ref is not None else 0.0
    best_value = max(positive.values()) if positive else 0.0
    for stat, value in budget_values.items():
        row = stats[stat]
        row["equal_budget_normalized_to_reference"] = (value / ref_value) if ref_value > _EPS else None
        row["equal_budget_normalized_to_best"] = (value / best_value) if best_value > _EPS else None

    rank = sorted(positive, key=lambda k: (-positive[k], k))
    out["equal_item_budget"] = {
        "method": str(budget_model.get("method", "empirical_equal_budget")),
        "unit": str(budget_model.get("unit", "empirical_stat_units_per_equal_budget")),
        "reference_stat": ref,
        "units_per_budget": units,
        "rank": rank,
        "confidence": dict(budget_model.get("confidence") or {}),
        "peer_group_count": budget_model.get("peer_group_count"),
        "note": budget_model.get("note"),
    }
    # This is the player-facing *body/general* gear-mix rank. Raw/native rank
    # remains recoverable from seconds_saved_per_100_per_point. Domain-specific
    # models (notably weapon-slot DPS exchanges) are kept separate below so a
    # weapon DPS point is never assigned the body-slot exchange scale.
    out["stat_mix_guidance_rank"] = rank

    domains_out={}
    for domain, model in (budget_model.get("domains") or {}).items():
        if not isinstance(model, Mapping):
            continue
        dunits={str(k):float(v) for k,v in (model.get("units_per_budget") or {}).items() if float(v)>0.0}
        vals={}
        for stat, amount in dunits.items():
            row=stats.get(stat)
            if not row or row.get("status","measured") != "measured" or row.get("seconds_saved_per_100_per_point") is None:
                continue
            native=float(row["seconds_saved_per_100_per_point"])
            value=native*amount
            vals[stat]=value
            per_domain=row.setdefault("equal_budget_domains",{})
            per_domain[str(domain)]={
                "empirical_units_per_equal_budget":amount,
                "seconds_saved_per_100_per_equal_budget":value,
            }
        dpos={k:v for k,v in vals.items() if v>_EPS}
        dref=model.get("reference_stat") if model.get("reference_stat") in dpos else None
        if dref is None and dpos:
            dref=max(dpos,key=dpos.get)
        drefv=dpos.get(dref,0.0) if dref else 0.0
        dbest=max(dpos.values()) if dpos else 0.0
        for stat,value in vals.items():
            drow=stats[stat]["equal_budget_domains"][str(domain)]
            drow["equal_budget_normalized_to_reference"]=(value/drefv) if drefv>_EPS else None
            drow["equal_budget_normalized_to_best"]=(value/dbest) if dbest>_EPS else None
        drank=sorted(dpos,key=lambda k:(-dpos[k],k))
        domains_out[str(domain)]={
            "method":str(model.get("method","empirical_equal_budget_domain")),
            "unit":str(model.get("unit","empirical_stat_units_per_equal_budget")),
            "reference_stat":dref,
            "units_per_budget":dunits,
            "rank":drank,
            "confidence":dict(model.get("confidence") or {}),
            "peer_group_count":model.get("peer_group_count"),
            "note":model.get("note"),
            **({"weapon_hands":model.get("weapon_hands")} if model.get("weapon_hands") is not None else {}),
        }
    if domains_out:
        out["equal_item_budget_domains"]=domains_out
    return out

def compute_for_engine(
    engine,
    level: int,
    talents,
    *,
    baseline: dict,
    policy=None,
    cfg=None,
    profile: str = "all",
    options=None,
    legacy_probe=None,
) -> dict | None:
    """Return stat weights through one common backend contract.

    Priority:
      1. ``engine.analytic_stat_gradient`` -- smooth local surrogate derivative.
      2. ``engine.marginal_stat_weights`` -- legacy backend diagnostic, preserved
         but explicitly tagged as non-analytic.
      3. caller-provided ``legacy_probe`` -- mature historical fallback.

    This dispatcher is intentionally class agnostic.  Class modules own only the
    mechanics-specific continuous surrogate/gradient.
    """
    provider = getattr(engine, "analytic_stat_gradient", None)
    if callable(provider):
        raw = provider(
            int(level), talents, baseline=baseline, policy=policy, cfg=cfg,
            profile=profile, options=options,
        )
        if raw is None:
            return None
        if isinstance(raw, dict) and raw.get("stats") and raw.get("method"):
            # Provider already emitted the shared schema.
            return raw
        if not isinstance(raw, Mapping) or "objective_gradient" not in raw:
            raise ValueError("analytic_stat_gradient must return objective_gradient or shared stat-weight schema")
        normalized = normalize_objective_gradient(
            baseline_s_per_100=float(raw.get("baseline_s_per_100", baseline.get("total_s", 0.0))),
            objective_gradient=raw["objective_gradient"],
            method=str(raw.get("method", "analytic_surrogate_gradient")),
            components=raw.get("components"),
            reference_stat=raw.get("reference_stat"),
            note=raw.get("note"),
            metadata=raw.get("metadata"),
            stat_status=raw.get("stat_status"),
            declared_stats=raw.get("declared_stats"),
        )
        budget_provider = getattr(engine, "item_budget_units", None)
        if callable(budget_provider):
            budget = budget_provider(
                int(level), baseline=baseline, profile=profile,
                stats=tuple(normalized.get("stats", {}).keys()),
            )
            normalized = apply_equal_item_budget_projection(normalized, budget)
        return normalized

    legacy = getattr(engine, "marginal_stat_weights", None)
    if callable(legacy):
        out = legacy(int(level), talents, profile, baseline=baseline)
        if isinstance(out, dict):
            out = dict(out)
            out.setdefault("schema_version", 1)
            out.setdefault("method", "legacy_finite_difference_gameplay_reoptimized")
            out.setdefault("analytical", False)
        return out

    if legacy_probe is not None:
        out = legacy_probe()
        if isinstance(out, dict):
            out = dict(out)
            out.setdefault("analytical", False)
        return out
    return None
