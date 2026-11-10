"""One class-independent execution-coverage contract for sourced talent builds.

P2's source catalogue, rows and rank curves are NOT executable proof. This
module makes the distinction queryable for every class/level, with stable
machine-readable blockers. It does not interpret any class-specific talent.
"""
from __future__ import annotations

from src.game.data.forever.source_rank_promotion import promote_atomic_source_talent_effects
from src.game.source_objective_relevance import solo_threat_exclusion


def compile_talent_runtime(ir):
    """Compile versioned typed L0 clauses where complete; keep untouched IR L2.

    Returns (IR, inventory), not a global certification. Existing sourced IR
    modifiers are preserved; coverage is checked over EVERY listed rank.
    """
    compiled, compilation = promote_atomic_source_talent_effects(ir)
    missing = []
    executable = []
    excluded = []
    for talent in compiled.talents:
        for rank in talent.ranks:
            record = {'talent_id': talent.id, 'rank': rank.rank,
                      'tree_key': talent.tree_key,
                      'source_build': talent.metadata.get('checkpoint_source_build'),
                      'source_url': talent.metadata.get('checkpoint_source_url')
                                    or rank.provenance.get('source_url'),
                      'modifier_count': len(rank.modifiers)}
            if rank.modifiers:
                executable.append(record)
            else:
                exclusion = solo_threat_exclusion(compiled, rank)
                if exclusion is not None:
                    excluded.append({**record, 'objective_exclusion': exclusion})
                else:
                    missing.append({**record, 'code': 'TALENT_RANK_HAS_NO_EXECUTOR',
                        'source_domains': [e.get('domain') for e in
                            (rank.provenance.get('checkpoint_source_l0') or {}).get('effects', ())]})
    return compiled, {
        'status': 'PARTIAL_RUNTIME_COVERAGE' if missing else 'RANK_MODIFIERS_PRESENT_NOT_FULL_EXECUTION_PROOF',
        'talent_count': len(compiled.talents),
        'rank_count': len(missing) + len(executable) + len(excluded),
        'rank_with_modifiers': len(executable),
        'rank_missing_executor': len(missing),
        'rank_objective_excluded': len(excluded),
        'objective_excluded': excluded,
        'missing': missing,
        'compilation': {
            'promoted_rank_count': compilation['promoted_rank_count'],
            'preexisting_rank_count': compilation['preexisting_rank_count'],
            'unscored_rank_count': compilation['unscored_rank_count'],
        },
        'full_talent_execution_certified': False,
        'eligible_for_checkpoint_acceptance': False,
    }
