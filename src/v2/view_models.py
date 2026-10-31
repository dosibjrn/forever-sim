from __future__ import annotations

"""Pure JSON/view-model construction for Fast analytic results."""

import importlib

from src import presentation
from .class_model import Evaluation


def _node_engine(node):
    """Use the engine that created the talent object, not global CLI state.

    Tests, persisted paths and listener reads can outlive a later ruleset/class
    selection in the same process.  Resolving from the dataclass module keeps a
    Classic node from being interpreted with Forever talent fields (and vice
    versa).
    """
    try:
        return importlib.import_module(type(node.talents).__module__)
    except Exception:
        return None


def _tree_points(engine, talents):
    names = tuple(getattr(engine, 'TREE_NAMES', ('frost', 'arcane', 'fire')))
    return {name: int(engine.tree_points(talents, name)) for name in names}


def _family(engine, talents):
    points = _tree_points(engine, talents)
    if not points:
        return 'mixed'
    ordered = sorted(points.items(), key=lambda item: (-item[1], item[0]))
    top = ordered[0][1]
    tied = [name for name, value in ordered if value == top and value > 0]
    school = ordered[0][0]
    if len(tied) >= 2:
        return '+'.join(sorted(tied))
    secondary = ordered[1][0] if len(ordered) > 1 and ordered[1][1] >= 5 else 'none'
    return f'{school}+{secondary}'


def node_json(node) -> dict:
    level = int(node.level)
    engine = _node_engine(node)
    engine = engine or presentation
    score = float(node.score_s_per_100)
    details = node.details or {}
    # One normalized throughput field keeps the browser surface comparable with
    # the experimental class publishers.  The mature Mage scorer's objective is
    # seconds per 100 mobs, so this conversion is exact for the displayed unit.
    mph = (360000.0 / score) if score > 0 else None
    policy = engine.policy_desc(node.policy, level) if node.policy is not None and hasattr(engine, 'policy_desc') else presentation.policy(node.policy, level)
    family = _family(engine, node.talents) if hasattr(engine, 'tree_points') else presentation.school_family(node.talents)[1]
    trees = _tree_points(engine, node.talents) if hasattr(engine, 'tree_points') else presentation.tree_points(node.talents)
    gear_snapshot = engine.real_gear_snapshot(level) if hasattr(engine, 'real_gear_snapshot') else None
    ev = Evaluation.from_raw({**details, 'total_s': score})
    timing = ev.published_fields()
    kill_s = float(ev.kill_s_per_100 or 0.0)
    recovery_s = float(ev.recovery_s_per_100 or 0.0)
    return {
        'level': level,
        **timing,
        'min_per_100': score / 60.0,
        'kill_share': (kill_s / score) if score > 0 and ev.kill_s_per_100 is not None else None,
        'recovery_share': (recovery_s / score) if score > 0 and ev.recovery_s_per_100 is not None else None,
        'allocation': engine.final_allocation(node.talents) if hasattr(engine, 'final_allocation') else presentation.allocation(node.talents),
        'policy': policy,
        'rotation': policy,
        'family': family,
        'talent_family': family,
        'combat_profile': 'single_target',
        'gear': 'real_items' if gear_snapshot else None,
        'gear_stats': gear_snapshot,
        'pull_size': 1,
        'stat_weights': details.get('stat_weights'),
        'model_fidelity': dict(getattr(engine, 'MODEL_FIDELITY', {}) or {}),
        'tree_points': trees,
        'source': node.source,
        'details': details,
    }


def path_json(path) -> dict:
    steps = []
    respec_levels = []
    for step in path.steps:
        node = step.node
        level = int(node.level)
        engine = _node_engine(node) or presentation
        policy = engine.policy_desc(node.policy, level) if node.policy is not None and hasattr(engine, 'policy_desc') else presentation.policy(node.policy, level)
        family = _family(engine, node.talents) if hasattr(engine, 'tree_points') else presentation.school_family(node.talents)[1]
        if step.kind == 'respec':
            respec_levels.append(level)
        steps.append({
            'level': level,
            'kind': step.kind,
            'talent_added': step.talent_added,
            'respecs_used': int(step.respecs_used),
            'allocation': engine.final_allocation(node.talents) if hasattr(engine, 'final_allocation') else presentation.allocation(node.talents),
            'policy': policy,
            'rotation': policy,
            'score_s_per_100': float(node.score_s_per_100),
            'min_per_100': float(node.score_s_per_100) / 60.0,
            'family': family,
            'talent_family': family,
            'tree_points': _tree_points(engine, node.talents) if hasattr(engine, 'tree_points') else presentation.tree_points(node.talents),
            'source': node.source,
        })
    return {
        'hours': float(path.hours),
        'respecs_used': int(path.respecs_used),
        'respec_levels': respec_levels,
        'resolved_through_level': int(path.resolved_through_level),
        'steps': steps,
        'final_allocation': steps[-1]['allocation'] if steps else '',
        'final_policy': steps[-1]['policy'] if steps else '',
    }
