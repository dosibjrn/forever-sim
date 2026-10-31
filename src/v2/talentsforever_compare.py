from __future__ import annotations

"""TalentsForever build parsing and canonical challenger comparison.

This module is intentionally read-only with respect to optimizer authority.
A pasted/source-backed build is a *challenger*: it is decoded into the active
class talent schema and scored through that class backend, but it never enters
search/frontier pruning or route publication.

Runtime does not fetch TalentsForever.  A copied URL contains an exact allocation
for the level encoded in the URL.  Lower-level progression is used only when an
offline source-backed snapshot carries an exact leveling order for that exact
source URL; missing order is never invented.
"""

from dataclasses import dataclass
import importlib
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse

from src.class_registry import get_definition
from .class_model import Evaluation
from .reference_builds import reference_build_snapshot


class TalentsForeverBuildError(ValueError):
    pass


class TalentsForeverComparisonUnavailable(TalentsForeverBuildError):
    pass


def _normalized_source_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if scheme not in {"http", "https"} or host != "talentsforever.com":
        raise TalentsForeverBuildError("URL must be an http(s)://talentsforever.com build link")
    # Source/provenance identity ignores query/fragment/trailing slash.  Do not
    # otherwise rewrite the build token because empty '-' tree segments matter.
    path = parsed.path.rstrip("/")
    return urlunparse(("https", "talentsforever.com", path, "", "", ""))


def _talent_module(class_name: str):
    definition = get_definition("forever", class_name)
    module_name = definition.talent_module or definition.engine_module
    return importlib.import_module(module_name)


def _ranks_from_tree_codes(class_name: str, tree_codes: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    definition = get_definition("forever", class_name)
    module = _talent_module(class_name)
    rules = dict(getattr(module, "TALENT_RULES", {}) or {})
    if not rules:
        raise TalentsForeverBuildError(f"{class_name} has no machine-readable talent schema")
    ranks: dict[str, int] = {}
    tree_points: dict[str, int] = {}
    for tree, code in zip(definition.tree_names, tree_codes):
        names = [name for name, rule in rules.items() if str(rule[0]) == str(tree)]
        if len(code) > len(names):
            raise TalentsForeverBuildError(
                f"{tree} URL segment has {len(code)} ranks but current schema has {len(names)} talents"
            )
        if any(ch < "0" or ch > "9" for ch in code):
            raise TalentsForeverBuildError(f"{tree} URL segment contains non-numeric talent ranks")
        points = 0
        for idx, ch in enumerate(code):
            rank = int(ch)
            name = names[idx]
            max_rank = int(rules[name][1])
            if rank > max_rank:
                raise TalentsForeverBuildError(f"{name} rank {rank} exceeds current max rank {max_rank}")
            if rank:
                ranks[name] = rank
                points += rank
        tree_points[str(tree)] = points
    return ranks, tree_points


def _expected_points(module: Any, level: int) -> int:
    fn = getattr(module, "expected_points_for_level", None)
    return int(fn(level)) if callable(fn) else max(0, min(51, int(level) - 9))


def _validate_ranks(class_name: str, level: int, ranks: Mapping[str, int]) -> tuple[Any, dict[str, int], str]:
    module = _talent_module(class_name)
    talents_type = getattr(module, "Talents", None)
    if talents_type is None:
        raise TalentsForeverBuildError(f"{class_name} has no Talents type")
    try:
        talents = talents_type(**{str(k): int(v) for k, v in ranks.items()})
    except Exception as exc:
        raise TalentsForeverBuildError(f"cannot decode build in current {class_name} schema: {exc}") from exc

    errors_fn = getattr(module, "allocation_schema_errors", None)
    errors = tuple(errors_fn(talents)) if callable(errors_fn) else ()
    if errors:
        raise TalentsForeverBuildError("build is invalid in current talent schema: " + ", ".join(map(str, errors)))
    points_fn = getattr(talents, "points", None)
    points = int(points_fn()) if callable(points_fn) else sum(int(v) for v in ranks.values())
    expected = _expected_points(module, int(level))
    if points != expected:
        raise TalentsForeverBuildError(f"talent point budget is {points}, expected {expected} at level {level}")

    definition = get_definition("forever", class_name)
    tree_fn = getattr(module, "tree_points", None)
    tree_points = {
        str(tree): int(tree_fn(talents, tree)) if callable(tree_fn) else 0
        for tree in definition.tree_names
    }
    allocation_fn = getattr(module, "final_allocation", None)
    allocation = str(allocation_fn(talents)) if callable(allocation_fn) else repr(talents)
    return talents, tree_points, allocation


def _stored_progression(class_name: str, source_url: str) -> tuple[list[str] | None, dict | None]:
    """Return exact offline progression only for the exact source URL."""
    try:
        snap = reference_build_snapshot(class_name)
    except Exception:
        return None, None
    if not snap:
        return None, None
    wanted = _normalized_source_url(source_url)
    for build in snap.get("builds") or ():
        url = build.get("source_url")
        if not url:
            continue
        try:
            same = _normalized_source_url(str(url)) == wanted
        except Exception:
            same = False
        if not same:
            continue
        order = [str(x) for x in (build.get("leveling_order") or ())]
        if order:
            return order, dict(build)
    return None, None


def parse_talentsforever_url(source_url: str, *, expected_class: str | None = None) -> dict:
    """Decode a copied TalentsForever URL into the active talent schema.

    TalentsForever encodes one rank digit per talent in each tree, trimming
    trailing zeroes. Empty tree segments remain empty (``--``). Any trailing
    share/layout token after the class' tree segments is preserved as opaque
    provenance and never interpreted as a leveling order.
    """
    canonical_url = _normalized_source_url(source_url)
    parsed = urlparse(canonical_url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 3:
        raise TalentsForeverBuildError("build URL must look like /<class>/<level>/<talent-code>")
    class_name = str(parts[0]).lower()
    if expected_class and class_name != str(expected_class).lower():
        raise TalentsForeverBuildError(f"build is for {class_name}, but listener selected {expected_class}")
    try:
        level = int(parts[1])
    except ValueError as exc:
        raise TalentsForeverBuildError("build URL level is not an integer") from exc
    if level < 10 or level > 60:
        raise TalentsForeverBuildError("TalentsForever build level must be 10..60")

    definition = get_definition("forever", class_name)
    encoded = parts[2]
    fields = encoded.split("-")
    tree_count = len(definition.tree_names)
    if len(fields) < tree_count:
        raise TalentsForeverBuildError(
            f"build URL has {len(fields)} tree segments, expected {tree_count} for {class_name}"
        )
    tree_codes = fields[:tree_count]
    opaque_suffix = "-".join(fields[tree_count:]) or None
    ranks, encoded_tree_points = _ranks_from_tree_codes(class_name, tree_codes)
    _talents, actual_tree_points, allocation = _validate_ranks(class_name, level, ranks)
    if encoded_tree_points != actual_tree_points:
        raise TalentsForeverBuildError(
            f"decoded tree points disagree with current schema: {encoded_tree_points} != {actual_tree_points}"
        )

    leveling_order, stored = _stored_progression(class_name, canonical_url)
    return {
        "schema_version": 1,
        "provider": "Talents Forever",
        "source_url": canonical_url,
        "class": class_name,
        "encoded_level": level,
        "tree_codes": dict(zip(definition.tree_names, tree_codes)),
        "opaque_source_suffix": opaque_suffix,
        "talent_ranks": ranks,
        "tree_points": actual_tree_points,
        "allocation": allocation,
        "points": sum(ranks.values()),
        "allocation_detail_status": "exact",
        "progression_status": "exact_offline_source" if leveling_order else "final_allocation_only",
        "leveling_order": leveling_order or [],
        "stored_reference_id": (stored or {}).get("id"),
        "runtime_schema_build": getattr(_talent_module(class_name), "TALENT_SCHEMA_BUILD", None),
    }


def _allocation_at_level(challenge: Mapping[str, Any], selected_level: int) -> dict:
    class_name = str(challenge["class"])
    encoded_level = int(challenge["encoded_level"])
    selected_level = int(selected_level)
    if selected_level == encoded_level:
        ranks = dict(challenge["talent_ranks"])
        talents, tree_points, allocation = _validate_ranks(class_name, selected_level, ranks)
        return {
            "level": selected_level,
            "talents": talents,
            "talent_ranks": ranks,
            "tree_points": tree_points,
            "allocation": allocation,
            "progression_source": "url_exact_level",
        }
    if selected_level > encoded_level:
        raise TalentsForeverComparisonUnavailable(
            f"pasted build is exact only through L{encoded_level}; it cannot define L{selected_level}"
        )

    order = [str(x) for x in (challenge.get("leveling_order") or ())]
    if not order:
        raise TalentsForeverComparisonUnavailable(
            f"this copied URL encodes the exact L{encoded_level} allocation but not lower-level point order; "
            f"paste a TalentsForever L{selected_level} link or use a stored reference with source-backed leveling order"
        )
    module = _talent_module(class_name)
    talents_type = getattr(module, "Talents")
    talents = talents_type()
    need = _expected_points(module, selected_level)
    legal_add = getattr(module, "legal_add", None)
    add_point = getattr(module, "add_point", None)
    if not callable(legal_add) or not callable(add_point):
        raise TalentsForeverComparisonUnavailable(f"{class_name} cannot reconstruct source-backed leveling order")
    for name in order[:need]:
        if not legal_add(talents, name):
            raise TalentsForeverBuildError(f"stored leveling order is illegal at {name}")
        talents = add_point(talents, name)
    ranks = {
        name: int(getattr(talents, name))
        for name in getattr(module, "TALENT_RULES", {})
        if int(getattr(talents, name)) > 0
    }
    talents, tree_points, allocation = _validate_ranks(class_name, selected_level, ranks)
    return {
        "level": selected_level,
        "talents": talents,
        "talent_ranks": ranks,
        "tree_points": tree_points,
        "allocation": allocation,
        "progression_source": "offline_source_leveling_order",
    }


def _select_optimizer_row(decisions: Mapping[str, Any], class_name: str, target_level: int, route: str, level: int) -> dict:
    if route == "per_level_best":
        rows = list((decisions.get("per_level_rows") or {}).get(class_name) or ())
    else:
        # ``route_rows`` is the canonical listener authority: it has already
        # merged scorer detail and enforced named-route identity.  Do not bypass
        # it by preferring a raw spec-matrix row.
        canonical_routes = (
            (((decisions.get("route_rows") or {}).get(class_name) or {}).get(str(int(target_level))) or {})
            .get("routes", {})
        )
        canonical_route = canonical_routes.get(route)
        if canonical_route is not None:
            if canonical_route.get("status") != "available":
                raise TalentsForeverComparisonUnavailable(
                    f"optimizer route {class_name} {route} is not selectable: {canonical_route.get('status') or 'unavailable'}"
                )
            rows = list(canonical_route.get("rows") or ())
        else:
            matrices = (((decisions.get("spec_matrix") or {}).get(class_name) or {}).get("matrices") or {})
            matrix = matrices.get(f"{int(target_level)}:{route}") or {}
            rows = list(matrix.get("rows") or ()) if matrix.get("status") == "available" else []
    row = next((dict(r) for r in rows if int(r.get("level", -1)) == int(level)), None)
    if not row:
        raise TalentsForeverComparisonUnavailable(
            f"no current selectable optimizer row for {class_name} {route} at L{level} (target L{target_level})"
        )
    if row.get("route_identity_contract_ok") is False:
        raise TalentsForeverComparisonUnavailable("optimizer row violates the named route identity contract")
    if not row.get("stat_weights_contract_ok") or not row.get("stat_weights"):
        raise TalentsForeverComparisonUnavailable("optimizer row violates the required stat-weight contract")
    return row


def _comparison_profile(class_name: str, route: str, optimizer_row: Mapping[str, Any]) -> str:
    definition = get_definition("forever", class_name)
    route_def = dict(definition.route_definitions.get(route) or {})
    profile = str(route_def.get("score_profile") or optimizer_row.get("score_profile") or optimizer_row.get("combat_profile") or optimizer_row.get("profile") or "all")
    if class_name == "druid" and profile == "cat":
        profile = "feral"
    if profile in {"", "auto"}:
        profile = "all"
    return profile


def _published_external_row(class_name: str, allocation: Mapping[str, Any], raw: Mapping[str, Any], *, challenge: Mapping[str, Any], mode: str) -> dict:
    row = dict(raw or {})
    ev = Evaluation.from_raw(row)
    row.update(ev.published_fields())
    row.setdefault("combat_profile", row.get("profile"))
    row.update({
        "level": int(allocation["level"]),
        "talent_ranks": dict(allocation["talent_ranks"]),
        "tree_points": dict(allocation["tree_points"]),
        "allocation": allocation["allocation"],
        "stat_weights_contract_ok": bool(row.get("stat_weights")),
        "source": "talentsforever_challenger",
        "data_sources": ["Talents Forever URL", "canonical class scorer"],
        "source_url": challenge["source_url"],
        "comparison_mode": mode,
        "progression_source": allocation["progression_source"],
        "search_authority": False,
        "route_authority": False,
    })
    return row


def _talent_divergence(optimizer: Mapping[str, Any], challenger: Mapping[str, Any]) -> list[dict]:
    a = {str(k): int(v) for k, v in dict(optimizer.get("talent_ranks") or {}).items()}
    b = {str(k): int(v) for k, v in dict(challenger.get("talent_ranks") or {}).items()}
    return [
        {"talent": key, "optimizer": a.get(key, 0), "challenger": b.get(key, 0), "delta": b.get(key, 0) - a.get(key, 0)}
        for key in sorted(set(a) | set(b))
        if a.get(key, 0) != b.get(key, 0)
    ]


def talentsforever_allocation_at_level(source_url: str, *, expected_class: str, selected_level: int) -> dict:
    """Resolve a TalentsForever link to an exact allocation at ``selected_level``.

    The URL itself is authoritative at its encoded level.  Earlier levels are
    accepted only when the exact source URL has a captured TalentsForever
    leveling order; no left-to-right or tree-order progression is invented.
    """
    challenge = parse_talentsforever_url(source_url, expected_class=expected_class)
    resolved = _allocation_at_level(challenge, int(selected_level))
    return {
        "provider": challenge["provider"],
        "source_url": challenge["source_url"],
        "class": challenge["class"],
        "encoded_level": int(challenge["encoded_level"]),
        "selected_level": int(selected_level),
        "talent_ranks": dict(resolved["talent_ranks"]),
        "tree_points": dict(resolved["tree_points"]),
        "allocation": str(resolved["allocation"]),
        "progression_source": str(resolved["progression_source"]),
        "points": sum(int(v) for v in resolved["talent_ranks"].values()),
    }


def compare_to_talentsforever_build(
    decisions: Mapping[str, Any], *, class_name: str, target_level: int, route: str,
    selected_level: int, source_url: str, mode: str = "same_gear",
) -> dict:
    """Score a pasted build against one current listener-selectable decision row."""
    class_name = str(class_name).lower()
    mode = str(mode or "same_gear")
    if mode not in {"same_gear", "full_decision"}:
        raise TalentsForeverBuildError("comparison mode must be same_gear or full_decision")
    optimizer = _select_optimizer_row(decisions, class_name, int(target_level), str(route), int(selected_level))
    challenge = parse_talentsforever_url(source_url, expected_class=class_name)
    allocation = _allocation_at_level(challenge, int(selected_level))

    definition = get_definition("forever", class_name)
    engine = definition.engine()
    scorer = getattr(engine, "score_external_build", None)
    if not callable(scorer):
        raise TalentsForeverComparisonUnavailable(
            f"{definition.display_name} does not yet expose the canonical external-build comparison adapter"
        )
    profile = _comparison_profile(class_name, str(route), optimizer)
    gear_stats = optimizer.get("gear_stats") if mode == "same_gear" else None
    if mode == "same_gear" and not isinstance(gear_stats, Mapping):
        raise TalentsForeverComparisonUnavailable("same-gear comparison requires the optimizer's exact published gear snapshot")

    raw = scorer(
        int(selected_level), allocation["talents"], profile,
        gear_stats=(dict(gear_stats) if isinstance(gear_stats, Mapping) else None),
    )
    challenger = _published_external_row(class_name, allocation, raw, challenge=challenge, mode=mode)
    if not challenger.get("stat_weights"):
        raise TalentsForeverComparisonUnavailable("challenger scorer returned no stat weights")

    opt_mph = float(optimizer.get("mobs_per_hour") or 0.0)
    ch_mph = float(challenger.get("mobs_per_hour") or 0.0)
    mph_delta = ch_mph - opt_mph
    pct = (100.0 * mph_delta / opt_mph) if opt_mph > 0 else None
    timing_delta = {
        key: (float(challenger.get(key)) - float(optimizer.get(key)))
        if challenger.get(key) is not None and optimizer.get(key) is not None else None
        for key in ("seconds_per_mob", "kill_seconds_per_mob", "recovery_seconds_per_mob", "travel_seconds_per_mob")
    }
    challenger_faster = bool(ch_mph > opt_mph + 1e-9)
    note = None
    if challenger_faster:
        note = (
            "Challenger is faster under this controlled scorer comparison. "
            "Treat this as a possible search/model coverage gap; the challenger remains comparison-only authority."
        )

    return {
        "schema_version": 1,
        "status": "available",
        "class": class_name,
        "target_level": int(target_level),
        "route": str(route),
        "level": int(selected_level),
        "mode": mode,
        "mode_label": "same published gear; talents/policy compared" if mode == "same_gear" else "independent optimized gear; same route/profile contract",
        "profile": profile,
        "source": {
            "provider": "Talents Forever",
            "url": challenge["source_url"],
            "encoded_level": challenge["encoded_level"],
            "progression_status": challenge["progression_status"],
            "stored_reference_id": challenge.get("stored_reference_id"),
            "runtime_schema_build": challenge.get("runtime_schema_build"),
        },
        "comparison_horizon": {
            "through_level": int(selected_level),
            "reference_points_used": int(sum(allocation["talent_ranks"].values())),
            "reference_endpoint_level": int(challenge["encoded_level"]),
            "reference_endpoint_points": int(challenge.get("points") or 0),
            "progression_source": allocation["progression_source"],
        },
        "optimizer": optimizer,
        "challenger": challenger,
        "delta": {
            "challenger_minus_optimizer_mobs_per_hour": mph_delta,
            "challenger_minus_optimizer_percent": pct,
            "timing": timing_delta,
        },
        "talent_divergence": _talent_divergence(optimizer, challenger),
        "challenger_faster": challenger_faster,
        "search_gap_note": note,
        "authority": {
            "optimizer_search_authority": True,
            "challenger_search_authority": False,
            "challenger_route_authority": False,
        },
    }
