"""Source-derived ability universe for fast P1 toy probes.

Policy declares applicability only. Every effect verdict is computed by running
the real production executor. The legal denominator is never inferred from
currently implemented GameIR actions: missing actions remain visible.
"""
from __future__ import annotations

from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice, registered_class_keys
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
from tools.wf_gate_p1_live import (
    P1_DEFAULT_SCENARIO, _highest_usable_ranks, _source_ids,
    _source_rows, _source_legality, _source_disabled_rune_ids,
    _load_p1_scenario_nonimpact, run_live,
)


def source_inventory(root: Path, class_key: str, level: int, *,
                     spec: str = "unrestricted",
                     scenario: str = P1_DEFAULT_SCENARIO):
    """Return (IR, eligible source rows, matched IR actions, live P1, nonimpact).

    Spec selects the checkpoint name, not an invented spell whitelist.
    At an unspecified talent allocation, source-legal reachable talent-grants
    are included if indexed; no single guessed Feral/Mage/etc allocation.
    """
    class_key = str(class_key).strip().lower()
    level = int(level)
    if class_key not in registered_class_keys():
        raise ValueError("UNKNOWN_CLASS:" + class_key)
    if not 1 <= level <= 60:
        raise ValueError("LEVEL_OUT_OF_RANGE:" + str(level))
    if not str(spec).strip():
        raise ValueError("EMPTY_SPEC")
    source = DEFAULT_DB
    if not source.is_file() or source.stat().st_size < 1024:
        raise ValueError("HYDRATED_SOURCE_SQLITE_REQUIRED")
    ir = build_game_ir_slice(class_key=class_key, level=level,
                             ability_db_path=source)
    if ir is None:
        raise ValueError("PRODUCTION_CLASS_LEVEL_IR_UNAVAILABLE:"
                         + class_key + ":" + str(level))
    source_p1 = run_live(root, class_key, level, spec=spec, scenario_id=scenario)
    legality, _ = _source_legality(root, ir, class_key, level, source)
    inactive = _source_disabled_rune_ids(source, class_key, level)
    waivers = _load_p1_scenario_nonimpact(root, class_key, level, scenario)

    rows = _highest_usable_ranks([
        row for row in _source_rows(source, class_key, level)
        if legality.get(int(row["spell_id"]), ("UNRESOLVED",))[0]
           in ("LEGAL", "CONDITIONAL")
        and int(row["spell_id"]) not in inactive
    ])
    selected = {}
    not_relevant = []
    for row in rows:
        sid = int(row["spell_id"])
        waiver = waivers.get(sid)
        if waiver:
            if waiver["name"] != row["name"]:
                # A stale/mis-bound waiver cannot remove a legal spell.
                raise ValueError("P1_NONIMPACT_ID_NAME_MISMATCH:" + str(sid))
            not_relevant.append({
                "spell_id": sid, "name": row["name"],
                "status": "NOT_RELEVANT_TO_SIMULATION",
                "scenario_id": scenario, "reason": waiver["reason"],
            })
        else:
            selected[sid] = row

    if not selected and not not_relevant:
        raise ValueError("EMPTY_SOURCE_LEGAL_ABILITY_UNIVERSE")
    matched = {}
    for action in ir.actions:
        if action.owner_actor_id != ir.actor.id:
            continue
        for sid in _source_ids(action, _source_spell_ids):
            if sid not in selected:
                continue
            if sid in matched:
                raise ValueError("DUPLICATE_P1_ACTION_ID:" + str(sid))
            matched[sid] = action
    return ir, selected, matched, source_p1, not_relevant
