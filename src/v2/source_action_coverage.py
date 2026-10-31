"""Fail-closed, source-backed action coverage ledger for discovery benchmarks.

A legal action may be strategically bad, but cannot disappear from search silently.
This ledger does not assert that the optimizer covers any excluded action.
"""
from __future__ import annotations

from src.game.runtime.effect_capabilities import effect_role


def audit_source_action_coverage(ir, *, level: int, search_envelopes=()) -> dict:
    """Report legal source actions absent from declared search envelopes across modes."""
    modes = tuple(ir.modes)
    present = {a for envelope in search_envelopes for a in envelope.get('eligible_buttons', ())}
    records = []
    for action in ir.actions:
        requirements = action.requirements or ()
        minimums = [r for r in requirements if r.get('kind') == 'minimum_level']
        try:
            if any(level < int(r['value']) for r in minimums):
                continue
        except (ValueError, TypeError, KeyError):
            pass  # unparseable requirement must remain visible, not assumed locked
        mode_reqs = [r.get('value') for r in requirements if r.get('kind') == 'mode_is']
        legal_modes = [m.id for m in modes if (not mode_reqs or m.id in mode_reqs)
                       and (m.enabled_action_ids is None or action.id in m.enabled_action_ids)]
        if modes and not legal_modes:
            continue
        warnings = [{'effect_index': i, 'semantic': dict(w)}
                    for i, e in enumerate(action.effects)
                    for w in getattr(e, 'unsupported_semantics', ())]
        unknown_requirements = [str(r.get('kind')) for r in requirements
                                if r.get('kind') not in ('minimum_level', 'mode_is', 'resource_min')]
        is_mode_transition = any(effect_role(e) == 'mode_change' for e in action.effects)
        unexecutable = [{'effect_index': i, 'effect_type': type(e).__name__}
                        for i, e in enumerate(action.effects) if effect_role(e) is None]
        missing_provenance = not bool(action.provenance)
        covered = action.id in present
        records.append({'action_id': action.id, 'effect_types': [type(e).__name__ for e in action.effects],
                        'legal_mode_ids': legal_modes, 'in_search': covered,
                        'mode_transition': is_mode_transition,
                        'unknown_requirements': unknown_requirements,
                        'semantic_gaps': warnings,
                        'unexecutable_effects': unexecutable,
                        'missing_provenance': missing_provenance,
                        'blocking': bool(not covered or warnings or unknown_requirements or unexecutable or missing_provenance)})
    blockers = [r for r in records if r['blocking']]
    # The old audit enumerated ONLY already-compiled IR actions, allowing an
    # entire missing source spell family to disappear before the audit ran.
    # Keep that legacy count separately so consumers can distinguish missing
    # source ranks from actions rejected by the optimizer.
    indexed = next((fact for fact in ir.source_facts
                    if fact.get('fact_kind') == 'canonical_indexed_ability_coverage'), None)
    source_records = () if indexed is None else indexed['records']
    missing_ranks = [r for r in source_records if not r['matched_action_ids']]
    return {'status': 'INCOMPLETE' if blockers or missing_ranks else 'ALL_AUDITED_ACTIONS_REACHABLE',
            'complete_optimizer': False,  # action coverage never proves global optimum
            'level': level, 'source_ir_id': ir.id,
            'audited_action_count': len(records), 'blocker_count': len(blockers) + len(missing_ranks),
            'ir_action_blocker_count':len(blockers),
            'source_indexed_unrepresented_rank_count':len(missing_ranks),
            'source_indexed_rank_blockers':missing_ranks,
            'source_index_is_not_acquisition_legality_proof':True,
            'actions': records, 'blockers': blockers}
