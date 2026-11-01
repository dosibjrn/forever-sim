"""P1: a compiled exact-ID action is not proof it was learned.

Acceptance remains fail-closed until a version-matched learned spellbook or
independently observed acquisition record exists for the whole checkpoint.
These are source-decision tests, not a claim of complete L60 spell coverage.
"""
from tools.wf_gate_p1_live import (_require_learned_source_proof,
    _verified_npc_acquisition_in_frontier, _source_legality_evidence_rows,
    P1SetupError)


def test_compiled_untrained_action_is_unresolved_without_spellbook():
    status,reason=_require_learned_source_proof(
        'LEGAL','SOURCE_INDEX_EXACT_ID_CHECKPOINT_GAME_IR_ACTION',
        spellbook_present=False)
    assert (status,reason)==(
        'UNRESOLVED','EXACT_GAME_IR_ACTION_IS_NOT_ACQUISITION_EVIDENCE')


def test_source_book_lookup_can_admit_exact_legal_rank():
    # The source-book decision itself is validated by SourceSpellbook and
    # checked against the source-index SHA in _source_legality.
    assert _require_learned_source_proof(
        'LEGAL','CLIENT_SPELLBOOK_EXACT_NAME_AND_LEARN_LEVEL',
        spellbook_present=True)==(
            'LEGAL','CLIENT_SPELLBOOK_EXACT_NAME_AND_LEARN_LEVEL')


def test_independently_observed_npc_acquisition_remains_legal():
    assert _require_learned_source_proof(
        'LEGAL','SOURCE_OBSERVED_NPC_TRAINING_METHOD',
        spellbook_present=False,acquisition_verified=True)==(
            'LEGAL','SOURCE_VERIFIED_NPC_TEACHING_METHOD')


def test_unverified_npc_training_table_row_is_never_enough():
    # _status() may see NPC method counts from an acquisition table for an
    # old source batch. Only the complete, snapshot-matched source frontier
    # is allowed to authorize an independently verified teacher.
    for evidence in (False, None, 0, 'VERIFIED'):
        assert _require_learned_source_proof(
            'LEGAL','SOURCE_OBSERVED_NPC_TRAINING_METHOD',
            spellbook_present=False,acquisition_verified=evidence)==(
                'UNRESOLVED','NPC_TRAINING_SOURCE_BATCH_NOT_VERIFIED')


def test_npc_method_cannot_override_explicit_source_illegality():
    assert _require_learned_source_proof(
        'ILLEGAL','NOT_A_LEARNED_STANDALONE_ACTION_IN_CLIENT_SPELLBOOK',
        spellbook_present=True,acquisition_verified=True)==(
            'ILLEGAL','NOT_A_LEARNED_STANDALONE_ACTION_IN_CLIENT_SPELLBOOK')


def test_unresolved_source_does_not_become_legal_with_book_presence():
    assert _require_learned_source_proof(
        'UNRESOLVED','INDEX_LEVEL_HINT_IS_NOT_ACQUISITION',
        spellbook_present=True)==(
            'UNRESOLVED','INDEX_LEVEL_HINT_IS_NOT_ACQUISITION')


def test_illegal_and_conditional_source_decisions_remain_distinct():
    for status,reason in [
        ('ILLEGAL','ENGRAVING_DISABLED'),
        ('ILLEGAL','NOT_A_LEARNED_STANDALONE_ACTION_IN_CLIENT_SPELLBOOK'),
        ('CONDITIONAL','CLIENT_SPELLBOOK_EXACT_TALENT_GRANT_ID'),
        ('PASSIVE','CLIENT_SPELLBOOK_AUTOMATIC_PASSIVE_NOT_PLAYER_CAST'),
    ]:
        assert _require_learned_source_proof(
            status,reason,spellbook_present=False)==(status,reason)


def test_combat_runtime_action_id_never_invents_trainer_proof():
    # Previously an indexed rank with a compiled action could be marked
    # LEGAL in _status even without any actual trainer/learned-rank source.
    for sid in (467,740,769):
        assert _require_learned_source_proof(
            'LEGAL','SOURCE_INDEX_EXACT_ID_CHECKPOINT_GAME_IR_ACTION',
            spellbook_present=False)[0]=='UNRESOLVED',sid


def test_exact_source_batch_verified_npc_method_overrides_ir_only_uncertainty():
    assert _require_learned_source_proof(
        'LEGAL','SOURCE_INDEX_EXACT_ID_CHECKPOINT_GAME_IR_ACTION',
        spellbook_present=False,acquisition_verified=True)==(
            'LEGAL','SOURCE_VERIFIED_NPC_TEACHING_METHOD')


def test_missing_or_stale_npc_evidence_cannot_promote_ir_action():
    for verified in (False,None,0,'VERIFIED'):
        assert _require_learned_source_proof(
            'LEGAL','SOURCE_INDEX_EXACT_ID_CHECKPOINT_GAME_IR_ACTION',
            spellbook_present=False,acquisition_verified=verified)==(
            'UNRESOLVED','EXACT_GAME_IR_ACTION_IS_NOT_ACQUISITION_EVIDENCE')


def test_verification_reads_real_frontier_category_and_detail_status():
    row={
        'source_acquisition_category':'DETAIL_OBSERVED_NPC_TEACHING_NOT_POSSESSION',
        'source_acquisition_evidence_status':'VERIFIED_DETAIL_NPC_TRAINING',
    }
    assert _verified_npc_acquisition_in_frontier(row)
    for invalid in (
        {**row,'source_acquisition_evidence_status':'STALE_DETAIL_ACQUISITION_EVIDENCE'},
        {**row,'source_acquisition_evidence_status':'SOURCE_INDEX_ACQUISITION_HINT_UNVERIFIED'},
        {**row,'source_acquisition_category':'SOURCE_INDEX_ACQUISITION_HINT_UNVERIFIED'},
        {'source_acquisition_verified':True},
        {},
    ):
        assert not _verified_npc_acquisition_in_frontier(invalid)


def test_full_acquisition_ledger_keeps_all_ranks_including_unresolved():
    def rec(sid,rank,reason):
        return {'spell_id':sid,'name':'Example','source_rank_hint':rank,
                'source_level_hint':rank*10,
                'source_url':'https://example.invalid/'+str(sid),
                'source_index_batch':'source-batch-pinned',
                'source_row_sha256':('a' if rank==1 else 'b')*64,
                'source_acquisition_category':reason,
                'source_acquisition_evidence_status':'NO_MATCHING_ACQUISITION_EVIDENCE',
                'ir_action_ids':[]}
    frontier={'records':[
        rec(740,1,'UNRESOLVED'),rec(467,1,'HINT'),
        rec(769,3,'UNRESOLVED'),{'ir_only_action_id':'unrelated'},
    ]}
    ledger={467:('LEGAL','CLIENT_SPELLBOOK_EXACT_NAME_AND_LEARN_LEVEL'),
            740:('UNRESOLVED','INDEX_LEVEL_HINT_IS_NOT_ACQUISITION'),
            769:('ILLEGAL','NO_VERIFIED_NONRUNE_GRANT')}
    result=_source_legality_evidence_rows(frontier,ledger)
    assert [r['spell_id'] for r in result]==[467,740,769]
    assert len(result)==len(ledger)==3
    assert [r['legality'] for r in result]==['LEGAL','UNRESOLVED','ILLEGAL']
    assert result[1]['source_index_batch']=='source-batch-pinned'
    assert result[2]['source_row_sha256']=='b'*64


def test_full_acquisition_ledger_rejects_missing_or_duplicate_rank_ids():
    import pytest
    rec={'spell_id':467,'name':'Thorns'}
    with pytest.raises(P1SetupError,match='LEDGER_MISSING'):
        _source_legality_evidence_rows({'records':[rec]}, {})
    with pytest.raises(P1SetupError,match='DUPLICATE_P1_SOURCE_LEGALITY_SPELL_ID'):
        _source_legality_evidence_rows({'records':[rec,rec]},
                                       {467:('UNRESOLVED','MISSING')})
    with pytest.raises(P1SetupError,match='LEDGER_UNMATCHED_IDS'):
        _source_legality_evidence_rows({'records':[rec]},
                                       {467:('UNRESOLVED','MISSING'),
                                        740:('UNRESOLVED','MISSING')})
