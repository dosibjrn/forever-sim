"""One class-independent execution-coverage contract for sourced talent builds.

P2's source catalogue, rows and rank curves are NOT executable proof. This
module makes the distinction queryable for every class/level, with stable
machine-readable blockers. It does not interpret any class-specific talent.
"""
from __future__ import annotations

from src.game.data.forever.source_rank_promotion import promote_atomic_source_talent_effects
from src.game.talents import apply_talent_selection


def compile_talent_runtime(ir):
    """Compile versioned typed L0 clauses where complete; keep untouched IR L2.

    Returns (IR, inventory), not a global certification. Existing sourced IR
    modifiers are preserved; coverage is checked over EVERY listed rank.
    """
    compiled, compilation = promote_atomic_source_talent_effects(ir)
    missing = []
    executable = []
    for talent in compiled.talents:
        for rank in talent.ranks:
            record = {'talent_id': talent.id, 'rank': rank.rank,
                      'tree_key': talent.tree_key,
                      'source_build': talent.metadata.get('checkpoint_source_build'),
                      'source_url': talent.metadata.get('checkpoint_source_url')
                                    or rank.provenance.get('source_url'),
                      'modifier_count': len(rank.modifiers)}
            if not rank.modifiers:
                missing.append({**record, 'code': 'TALENT_RANK_HAS_NO_EXECUTOR',
                    'source_domains': [e.get('domain') for e in
                        (rank.provenance.get('checkpoint_source_l0') or {}).get('effects', ())]})
            else:
                executable.append(record)
    return compiled, {
        'status': 'PARTIAL_RUNTIME_COVERAGE' if missing else 'RANK_MODIFIERS_PRESENT_NOT_FULL_EXECUTION_PROOF',
        'talent_count': len(compiled.talents),
        'rank_count': len(missing) + len(executable),
        'rank_with_modifiers': len(executable),
        'rank_missing_executor': len(missing),
        'missing': missing,
        'compilation': {
            'promoted_rank_count': compilation['promoted_rank_count'],
            'preexisting_rank_count': compilation['preexisting_rank_count'],
            'unscored_rank_count': compilation['unscored_rank_count'],
        },
        'full_talent_execution_certified': False,
        'eligible_for_checkpoint_acceptance': False,
    }


def compile_talent_candidate(ir, *, selection, level, bonus_talent_points=0):
    """Fail closed on unexecuted selected ranks, tier/point legality or wrong IR.

    Checkpoints must opt in to the canonical staged source database before this
    is called; no synthetic rank fill or silent fallback to a different build.
    """
    compiled, inventory = compile_talent_runtime(ir)
    chosen_missing = [r for r in inventory['missing']
                      if int(selection.get(r['talent_id'], 0)) == int(r['rank'])]
    if chosen_missing:
        return None, {'status': 'BLOCKED_SELECTED_TALENT_RANK_UNEXECUTABLE',
                      'missing': chosen_missing, 'coverage': inventory,
                      'eligible_for_checkpoint_acceptance': False}
    # Real engine checks rank, tier, prerequisite and bonus-point constraints.
    selected, application = apply_talent_selection(compiled, selection,
        level=level, bonus_talent_points=bonus_talent_points)
    return selected, {'status': 'EXECUTABLE_CANDIDATE_DIAGNOSTIC',
        'spent_points': application.spent_points,
        'available_points': application.available_points,
        'applied_count': len(application.applied_modifiers),
        'coverage': inventory,
        'eligible_for_checkpoint_acceptance': False}
