"""Source-pinned, checkpoint-level P2 reachability and L2 executor audit.

This is a RED/GREEN gate *predicate*, not a talent-spell whitelist and not a
shortcut to certification.  Reachability uses the actual talent budget, not
historical level-only labels written before bonus points were enabled.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from src.game.data.forever.source_checkpoint_p2 import (
    P2Checkpoint, _witness, check_structural_allocation,
)
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import available_talent_points, apply_talent_selection


def _source_partial_semantics(rank):
    """Typed, nonduplicative execution gaps: a partial effect is never GREEN."""
    result=set()
    for modifier in rank.modifiers:
        provenance=modifier.provenance
        is_channel=modifier.kind in ('cooldown_factor_pct','threat_factor_pct') and (
            provenance.get('authority')=='source_pinned_compound_channel_talent')
        if provenance.get('unsupported_party_scope'):
            result.add('SOURCE_CHANNEL_PARTY_HEAL_OR_THREAT_NOT_EXECUTED'
                       if is_channel else 'SOURCE_PARTY_AURA_NOT_EXECUTED')
        if provenance.get('unsupported_expected_value_distribution'):
            result.add('DISCRETE_CRIT_PROC_DISTRIBUTION_NOT_CERTIFIED')
        if provenance.get('unsupported_heal_school_binding'):
            result.add('SOURCE_NATURE_HEAL_ACTION_SCHOOL_NOT_VERIFIED')
        if provenance.get('unsupported_future_action_scope'):
            result.add('FUTURE_LEVEL_CONTROL_ACTION_NOT_EXECUTED')
        if provenance.get('unsupported_interrupt_cast'):
            result.add('ENEMY_CAST_INTERRUPT_NOT_RUNTIME_CERTIFIED')
        if provenance.get('unsupported_target_orientation'):
            result.add('TARGET_FACING_BEHIND_PROXY_NOT_CERTIFIED')
        if provenance.get('unsupported_out_of_2d'):
            result.add('SPATIAL_CHARGE_SOLO_FALLBACK_UNAVAILABLE')
        if provenance.get('unsupported_multi_hot_selection'):
            result.add('MULTIPLE_ACTIVE_HOT_SELECTION_NOT_SOURCE_VERIFIED')
        if provenance.get('unsupported_healing_snapshot'):
            result.add('ACTIVE_HOT_HEALING_POWER_SNAPSHOT_NOT_VERIFIED')
        if provenance.get('unsupported_heal_crit_multiplier_build_bridge'):
            result.add('SOURCE_CLASSIC_HEAL_CRIT_MULTIPLIER_TO_70338_UNVERIFIED')
        if provenance.get('unsupported_prerequisite_rank_bridge'):
            result.add('PREREQUISITE_REQUIRED_RANK_SOURCE_BUILD_BRIDGE_UNVERIFIED')
        if provenance.get('unsupported_build_bridge'):
            result.add('SOURCE_CHANNEL_ABILITY_BUILD_BRIDGE_UNVERIFIED' if is_channel
                else 'SOURCE_RESOURCE_ACTION_MECHANICS_BUILD_BRIDGE_UNVERIFIED'
                if modifier.kind=='grant_source_resource_action'
                else 'RESOURCE_AMOUNT_SOURCE_BUILD_BRIDGE_UNVERIFIED'
                if modifier.kind=='critical_resource_gain'
                else 'SOURCE_BUILD_BRIDGE_UNVERIFIED')
    return sorted(result)


def _pinned_source_positions(db_path, *, checkpoint, ir):
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro', uri=True) as db:
        records = db.execute('SELECT source_build, source_sha256, source_json '
            'FROM checkpoint_talent_source_catalogue WHERE class_key=? AND min_level=?',
            (checkpoint.class_key, checkpoint.level)).fetchall()
    if len(records) != 1:
        raise ValueError('P2_SOURCE_CATALOGUE_MISSING_OR_AMBIGUOUS')
    source_build, source_hash, source_json = records[0]
    if source_build != checkpoint.source_build or sha256(source_json.encode()).hexdigest() != source_hash:
        raise ValueError('P2_SOURCE_BUILD_OR_SHA_MISMATCH')
    source = json.loads(source_json)
    if (source['class_key'] != checkpoint.class_key
            or int(source['min_level']) != checkpoint.level
            or source['source_build'] != checkpoint.source_build):
        raise ValueError('P2_SOURCE_CATALOGUE_WRONG_CHECKPOINT')
    for talent in ir.talents:
        meta = talent.metadata
        if (meta.get('checkpoint_source_build') != source_build
                or meta.get('checkpoint_source_stage_sha256') != source_hash):
            raise ValueError('P2_GAME_IR_NOT_BOUND_TO_PINNED_SOURCE:' + talent.id)
    source_positions = {}
    for row in source.get('observed_unreachable_talent_positions', ()):
        # "Unreachable" is a historical *normal-talent-point* annotation.
        # Only the source's actual row is authoritative when bonus points exist.
        if (row.get('client_build') != source_build
                or not str(row.get('source_url', '')).startswith('https://')
                or not isinstance(row.get('row'), int)
                or row['row'] < 0):
            raise ValueError('P2_UNTRUSTED_SOURCE_POSITION')
        talent_id = row['indexed_talent_id']
        if talent_id in source_positions:
            raise ValueError('P2_DUPLICATE_POSITION')
        source_positions[talent_id] = {'row': row['row']}
    return source_hash, source_positions


def _executable_filler_witness(target, target_rank, talents, *, points, step):
    """Find source-tree tier fillers that actually compile, not alphabetical gaps.

    This is a bounded witness, NOT a full reachability/optimality oracle.
    It must subsequently pass the unchanged structural legality verifier and
    the real apply_talent_selection executor. A miss stays RED/UNRESOLVED.
    """
    definitions={talent.id:talent for talent in talents}
    selected={}
    def require(talent,rank,stack=()):
        if talent.id in stack:return False
        if rank>talent.max_rank or rank<=0:return False
        if len(talent.ranks)<rank or any(not r.modifiers for r in talent.ranks[:rank]):return False
        selected[talent.id]=max(selected.get(talent.id,0),rank)
        prerequisite=talent.prerequisite or {}
        if prerequisite:
            needed=definitions.get(str(prerequisite.get('talent_id')))
            needed_rank=prerequisite.get('required_rank')
            if not needed or needed_rank is None or not require(needed,int(needed_rank),(*stack,talent.id)):
                return False
        return True
    if not require(target,target_rank):return None
    row=target.metadata.get('row')
    if row is None:return None
    row=int(row)
    tree=target.tree_key
    # Fill each tier with legal, source-compilable ranks at earlier tiers.
    # Favour a high-rank compiled row, but preserve target prerequisites.
    for tier in range(1,row+1):
        while sum(selected.get(t.id,0) for t in talents
                  if t.tree_key==tree and t.metadata.get('row') is not None
                  and int(t.metadata['row'])<tier)<tier*step:
            viable=[]
            for talent in talents:
                tr=talent.metadata.get('row')
                if (talent.tree_key!=tree or tr is None or int(tr)>=tier
                        or talent.id==target.id):continue
                next_rank=selected.get(talent.id,0)+1
                if (next_rank>talent.max_rank or next_rank>len(talent.ranks)
                        or not talent.ranks[next_rank-1].modifiers):continue
                prereq=talent.prerequisite or {}
                if prereq and selected.get(str(prereq.get('talent_id')),0)<int(prereq.get('required_rank',999)):
                    continue
                # Source row legality must hold at the time the rank is added.
                needed=int(tr)*step
                existing=sum(selected.get(t.id,0) for t in talents if
                    t.tree_key==tree and t.metadata.get('row') is not None
                    and int(t.metadata['row'])<int(tr))
                if existing<needed:continue
                viable.append((int(tr),-talent.max_rank,talent.id,talent))
            if not viable:return None
            pick=min(viable)[3]
            selected[pick.id]=selected.get(pick.id,0)+1
            if sum(selected.values())>points:return None
    return selected if sum(selected.values())<=points else None


def audit_checkpoint_p2_executor(ir, *, db_path, checkpoint: P2Checkpoint,
                                 bonus_talent_points: int):
    """Expose every legal rank with a real structural witness or a blocker.

    Never mark a rank unreachable merely because the older 21-point source
    labels it so, because no greedy witness was found, or because its IR row
    happens to be missing. Preserve uncertainty; never fabricate a modifier.
    """
    if (ir.actor.metadata.get('class_key') != checkpoint.class_key
            or int(ir.actor.metadata.get('level', -1)) != checkpoint.level):
        raise ValueError('P2_IR_CHECKPOINT_MISMATCH')
    source_sha, override_rows = _pinned_source_positions(
        db_path, checkpoint=checkpoint, ir=ir)
    compiled, coverage = compile_talent_runtime(ir)
    available = available_talent_points(checkpoint.level,
                                        bonus_talent_points=bonus_talent_points)
    step = int((ir.provenance.get('talent_tree_rules') or {}).get('points_per_row') or 0)
    if step <= 0:
        raise ValueError('P2_TIER_RULE_MISSING')
    reachable = []
    unreachable = []
    unresolved = []
    application_failures = []
    for talent in compiled.talents:
        row = talent.metadata.get('row')
        if row is None:
            row = override_rows.get(talent.id, {}).get('row')
        for rank in talent.ranks:
            evidence = {'talent_id': talent.id, 'rank': int(rank.rank),
                'source_build': checkpoint.source_build,
                'source_url': talent.metadata.get('checkpoint_source_url'),
                'row': row, 'modifier_count': len(rank.modifiers),
                'source_domains': [key for key in (
                    (rank.provenance.get('checkpoint_source_l0') or {}).get('effect_domain'),
                    (rank.provenance.get('checkpoint_source_l0') or {}).get('additional_effect_domain'))
                    if key is not None]}
            # Tier arithmetic is a mathematically necessary condition, not an
            # inference based on the approximate single-path witness builder.
            if row is not None and int(row)*step + int(rank.rank) > available:
                unreachable.append({**evidence, 'why':'TIER_MINIMUM_EXCEEDS_BUDGET'})
                continue
            witness = _witness(talent, rank.rank, compiled.talents,
                               available, step, override_rows=override_rows)
            if witness is None:
                unresolved.append({**evidence, 'code':'P2_REACHABILITY_UNRESOLVED'})
                continue
            try:
                check_structural_allocation(ir, witness, checkpoint,
                    override_rows=override_rows,
                    bonus_talent_points=bonus_talent_points)
            except ValueError as exc:
                unresolved.append({**evidence, 'code':'P2_WITNESS_REJECTED',
                                   'detail':str(exc)})
                continue
            # A source-legal selection MUST also enter the real application
            # pipeline. Compiling one target rank is insufficient when the
            # prerequisite/filler ranks in the same allocation still fail.
            application = {'status':'NOT_APPLIED'}
            try:
                _, receipt = apply_talent_selection(compiled, witness,
                    level=checkpoint.level, bonus_talent_points=bonus_talent_points)
                delivered = sum(1 for value in receipt.applied_modifiers
                    if value.get('talent_id') == talent.id
                    and int(value.get('rank', -1)) == rank.rank)
                if not delivered:
                    application={'status':'RED_TARGET_RANK_NOT_DELIVERED'}
                else:
                    application={'status':'APPLIED_IN_GAME_IR',
                                 'target_modifier_applications':delivered}
            except ValueError as exc:
                application={'status':'RED_LEGAL_BUILD_FAILS_TALENT_APPLICATION',
                             'detail':str(exc)}
            if application['status'].startswith('RED') and rank.modifiers:
                # Alphabetic structural witnesses often contain unrelated,
                # unsupported filler talents. Verify a separately executable
                # 26-point legal build before blaming the target rank.
                alternate=_executable_filler_witness(talent,rank.rank,compiled.talents,
                    points=available,step=step)
                if alternate is not None and alternate!=witness:
                    try:
                        check_structural_allocation(ir,alternate,checkpoint,
                            override_rows=override_rows,bonus_talent_points=bonus_talent_points)
                        _,second=apply_talent_selection(compiled,alternate,
                            level=checkpoint.level,bonus_talent_points=bonus_talent_points)
                        delivered=sum(1 for v in second.applied_modifiers
                            if v.get('talent_id')==talent.id and int(v.get('rank',-1))==rank.rank)
                        if delivered:
                            witness=alternate
                            application={'status':'APPLIED_IN_GAME_IR',
                                'target_modifier_applications':delivered,
                                'witness_strategy':'EXECUTABLE_SOURCE_FILLERS'}
                    except ValueError:
                        pass
            partial_semantics = _source_partial_semantics(rank)
            status = ('RED_NO_EXECUTOR' if not rank.modifiers else
                'SOURCE_RANK_CURVE_DEFERRED' if talent.metadata.get('checkpoint_source_deferred_rank_curve')
                else 'SOURCE_RANK_PARTIAL_RUNTIME_SEMANTICS' if partial_semantics
                else 'MODIFIER_PRESENT_RUNTIME_PARITY_NOT_PROVEN')
            rec={**evidence,'witness':witness,'application':application,
                'partial_semantics':partial_semantics,
                'source_rank_curve_deferred':bool(talent.metadata.get('checkpoint_source_deferred_rank_curve')),
                # Position-only observation is not a verified legal talent:
                # prerequisites and full rank curves may still be unknown.
                'source_prerequisites_unverified':bool(talent.metadata.get('checkpoint_source_deferred_rank_curve') or
                    talent.metadata.get('checkpoint_source_prerequisite_rank_unverified')),
                'status':status}
            if application['status'].startswith('RED'):
                application_failures.append(rec)
            reachable.append(rec)
    blockers = [r for r in reachable if r['status'] != 'MODIFIER_PRESENT_RUNTIME_PARITY_NOT_PROVEN'
                or r['application']['status'].startswith('RED')]
    source_gaps = [r for r in reachable if r['source_prerequisites_unverified']]
    # These are full-gate reasons, not sub-gates and not permission to use
    # a position-only witness as proof of complete source legality.
    fail_reasons=[]
    if any(r['status']=='RED_NO_EXECUTOR' for r in reachable):
        fail_reasons.append('REACHABLE_RANK_MISSING_EXECUTABLE_MODIFIER')
    if application_failures:
        fail_reasons.append('SOURCE_STRUCTURAL_WITNESS_FAILS_TALENT_APPLICATION')
    if source_gaps:
        fail_reasons.append('SOURCE_PREREQUISITE_OR_RANK_CURVE_UNVERIFIED')
    if any(r['partial_semantics'] for r in reachable):
        fail_reasons.append('SOURCE_RANK_PARTIAL_RUNTIME_SEMANTICS')
    if unresolved:
        fail_reasons.append('SOURCE_REACHABILITY_UNKNOWN')
    fail_reasons.append('REAL_COMBAT_RUNTIME_SEMANTIC_PARITY_NOT_CERTIFIED')
    # Even with complete rank coverage, full P2 requires real generic effect
    # behavior / unlock witnesses. Merely creating modifiers is insufficient.
    status = ('RED_REACHABLE_TALENT_EXECUTION' if blockers or unresolved else
              'AWAITING_PORT_LEVEL_RUNTIME_SEMANTIC_PROOF')
    return {'gate':'P2', 'checkpoint':f'{checkpoint.class_key}:L{checkpoint.level}:{checkpoint.profile}',
        'source_build':checkpoint.source_build,'source_sha256':source_sha,
        'bonus_talent_points':bonus_talent_points,'available_points':available,
        'status':status,'green':False,'certified_checkpoint':False,
        'reachability_scope':'STRUCTURAL_WITHIN_PINNED_STAGED_SOURCE_NOT_FINAL_PREREQUISITE_CERTIFICATION',
        'remaining_gate_fail_reasons':fail_reasons,
        'source_prerequisite_or_curve_unverified_count':len(source_gaps),
        'source_prerequisite_or_curve_unverified':source_gaps,
        'partial_runtime_semantics_count':sum(bool(r['partial_semantics']) for r in reachable),
        'rank_application_failure_count':len(application_failures),
        'rank_application_failures':application_failures,
        'source_rank_total':len(reachable)+len(unreachable)+len(unresolved),
        'reachable_rank_count':len(reachable),
        'unreachable_rank_count':len(unreachable),
        'unreachable_without_executor':sum(r['modifier_count']==0 for r in unreachable),
        'unresolved_reachability_count':len(unresolved),
        'reachable_without_executor':sum(r['status']=='RED_NO_EXECUTOR' for r in reachable),
        'reachable_deferred_source_curve':sum(r['source_rank_curve_deferred'] for r in reachable),
        'structural_witnesses':reachable,'provably_unreachable':unreachable,
        'unresolved':unresolved,'remaining_executable_blockers':blockers,
        'existing_compilation':coverage['compilation']}
