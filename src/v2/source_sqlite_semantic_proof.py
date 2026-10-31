"""Independent, fail-closed proof contract for source-to-executor equivalence.

This gate does not construct executable IR. Evidence must be supplied by an
independent verifier; neither regex extraction nor effect-kind existence counts
as executor behavioral proof. No spell-specific facts or exceptions live here.
"""
from __future__ import annotations

from collections.abc import Mapping

REQUIRED_DIMENSIONS = (
    'complete_effect_clauses', 'targeting', 'prerequisites', 'activation',
    'timing', 'resource_accounting', 'scaling', 'executor_behavior',
)


class InvalidProofEvidence(ValueError):
    """Evidence is structurally malformed or refers to another source."""


def evaluate_semantic_proof(audit: dict, evidence: Mapping | None = None) -> dict:
    """Evaluate a proof packet without promoting a spell to executable IR.

    Evidence is admissible only when it has an independent verifier identity,
    the exact source SHA-256, a matching spell ID, and explicit PASS for every
    required dimension. A self-described PASS is *not* trusted as behavioral
    proof: this routine only establishes completeness of a proof *packet*.
    End-to-end release is a separate authority gate.
    """
    source = audit.get('source')
    if not isinstance(source, dict) or not source.get('html_sha256') or type(audit.get('spell_id')) is not int:
        raise InvalidProofEvidence('audited source identity required')
    if audit.get('execution_status') != 'BLOCKED_UNPARSED_EFFECTS' or audit.get('ir_promotion_allowed') is not False:
        raise InvalidProofEvidence('only fail-closed audited spells are accepted')
    if not isinstance(audit.get('blockers'), list) or not isinstance(audit.get('observations'), list):
        raise InvalidProofEvidence('complete semantic audit required')
    reasons = []
    statuses = {}
    evidence = {} if evidence is None else evidence
    if not isinstance(evidence, Mapping):
        raise InvalidProofEvidence('proof evidence must be a mapping')
    if evidence:
        if evidence.get('spell_id') != audit['spell_id'] or evidence.get('html_sha256') != source['html_sha256']:
            raise InvalidProofEvidence('proof evidence source identity mismatch')
        verifier = evidence.get('independent_verifier')
        if not isinstance(verifier, str) or not verifier.strip():
            raise InvalidProofEvidence('independent verifier identity missing')
    claims = evidence.get('dimensions', {})
    if not isinstance(claims, Mapping):
        raise InvalidProofEvidence('proof dimensions must be a mapping')
    unknown = set(claims) - set(REQUIRED_DIMENSIONS)
    if unknown:
        raise InvalidProofEvidence('unknown proof dimensions: ' + ','.join(sorted(map(str, unknown))))
    for dimension in REQUIRED_DIMENSIONS:
        claim = claims.get(dimension)
        # A verifier must name a test/reference artifact; booleans alone cannot
        # constitute independent source/executor agreement.
        admissible = (isinstance(claim, Mapping) and claim.get('status') == 'PASS'
                      and isinstance(claim.get('evidence_ref'), str)
                      and bool(claim['evidence_ref'].strip()))
        statuses[dimension] = 'EVIDENCED' if admissible else 'MISSING_OR_UNPROVEN'
        if not admissible:
            reasons.append('UNPROVEN_' + dimension.upper())
    if audit.get('blockers'):
        reasons.append('UNRESOLVED_SOURCE_AUDIT_BLOCKERS')
    if not audit.get('source_clause_coverage_complete'):
        reasons.append('INCOMPLETE_SOURCE_CLAUSE_COVERAGE')
    # This is only a packet-format gate; even apparently complete evidence must
    # undergo independent reproduction and end-to-end regression before use.
    packet_complete = not reasons
    return {
        'spell_id': audit['spell_id'], 'source': source,
        'dimension_status': statuses, 'proof_packet_complete': packet_complete,
        'blocking_reasons': reasons,
        'independent_reproduction_verified': False,
        'end_to_end_regression_verified': False,
        'ir_promotion_allowed': False,
        'execution_status': 'BLOCKED_UNPARSED_EFFECTS',
        'executable_effects': [],
    }


def evaluate_verified_spell(database, *, batch_id: str, spell_id: int, evidence=None) -> dict:
    from src.v2.source_sqlite_semantic_audit import audit_verified_spell
    return evaluate_semantic_proof(audit_verified_spell(database, batch_id=batch_id, spell_id=spell_id), evidence)
