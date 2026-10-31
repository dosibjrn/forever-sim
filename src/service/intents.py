from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import JobRequest


INTENT_ACTIONS = {"recompute_range", "deepen_level", "investigate_level"}
DEPTHS = {"standard", "wide", "deep"}


@dataclass(frozen=True)
class CompiledIntent:
    action: str
    request: JobRequest
    priority: int = 0
    deduplicate: bool = True
    user_summary: str = ""


def _class_name(body: dict[str, Any]) -> str:
    value = str(body.get("class_name") or body.get("class") or "").strip().lower()
    if not value:
        raise ValueError("class_name is required")
    return value


def _level(value: Any, name: str) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if level < 1 or level > 60:
        raise ValueError(f"{name} must be between 1 and 60")
    return level




def _workers(value: Any) -> int:
    try:
        workers = int(value if value is not None else 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("workers must be an integer") from exc
    if workers < 1 or workers > 32:
        raise ValueError("workers must be between 1 and 32")
    return workers

def _depth_config(depth: str) -> dict[str, Any]:
    # User-facing depth controls search breadth. Backend names remain internal.
    # Keep these bounded: they are service budgets, not claims of exhaustiveness.
    if depth == "standard":
        return {"beam_width": 10, "family_keep": 1, "final_k": 8, "stat_weight_top_k": 1}
    if depth == "wide":
        return {"beam_width": 72, "family_keep": 10, "final_k": 40, "stat_weight_top_k": 3}
    if depth == "deep":
        return {"beam_width": 128, "family_keep": 16, "final_k": 64, "stat_weight_top_k": 5}
    raise ValueError("depth must be standard, wide or deep")


def compile_intent(body: dict[str, Any]) -> CompiledIntent:
    action = str(body.get("action") or "").strip().lower()
    if action not in INTENT_ACTIONS:
        raise ValueError("action must be recompute_range, deepen_level or investigate_level")
    class_name = _class_name(body)
    priority = int(body.get("priority", 0))
    deduplicate = bool(body.get("deduplicate", True))

    if action == "recompute_range":
        start = _level(body.get("from_level", body.get("start_level")), "from_level")
        end = _level(body.get("to_level", body.get("end_level")), "to_level")
        if end < start:
            raise ValueError("to_level must be >= from_level")
        depth = str(body.get("depth") or "standard").lower()
        if depth not in DEPTHS:
            raise ValueError("depth must be standard, wide or deep")
        config = _depth_config(depth)
        config["workers"] = _workers(body.get("workers"))
        config["service_intent"] = {"action": action, "depth": depth}
        request = JobRequest(
            ruleset="forever", class_name=class_name, start_level=start, end_level=end,
            objective="cumulative", endpoint_mode="smooth", config=config,
        )
        return CompiledIntent(action, request, priority, deduplicate, f"Recompute {class_name} L{start}–{end} ({depth})")

    level = _level(body.get("level"), "level")
    depth = str(body.get("depth") or ("wide" if action == "deepen_level" else "deep")).lower()
    if depth not in DEPTHS:
        raise ValueError("depth must be standard, wide or deep")
    config = _depth_config(depth)
    config["workers"] = _workers(body.get("workers"))
    config["service_intent"] = {
        "action": action,
        "depth": depth,
        "reason": str(body.get("reason") or "").strip(),
    }
    request = JobRequest(
        ruleset="forever", class_name=class_name, start_level=level, end_level=level,
        objective="endpoint", endpoint_mode="smooth", config=config,
    )
    verb = "Deepen" if action == "deepen_level" else "Investigate"
    return CompiledIntent(action, request, priority, deduplicate, f"{verb} {class_name} L{level} ({depth})")


def public_intent_from_job(job: dict[str, Any]) -> dict[str, Any]:
    request = dict(job.get("request") or {})
    cfg = dict(request.get("config") or {})
    meta = dict(cfg.get("service_intent") or {})
    action = str(meta.get("action") or "recompute_range")
    out = {
        "action": action,
        "class_name": request.get("class_name"),
        "depth": meta.get("depth", "standard"),
    }
    if action == "recompute_range":
        out.update({"from_level": request.get("start_level"), "to_level": request.get("end_level")})
    else:
        out.update({"level": request.get("start_level")})
        if meta.get("reason"):
            out["reason"] = meta["reason"]
    return out
