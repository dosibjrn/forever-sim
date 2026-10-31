"""WF303: persistent source audit must not invent full checkpoint coverage."""
import json
from pathlib import Path
from copy import deepcopy
import pytest
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from tools.wf303_checkpoint_falsifier import source_gap_audit,validate

ROOT=Path(__file__).resolve().parents[1]
WINNER=json.loads((ROOT/'WF299_DRUID_L20_30S_BLIND_EVIDENCE.json').read_text())['winner']


def test_source_source_authorized_removal_is_not_a_complete_action_model():
    report=source_gap_audit('druid',20)
    cats=report['counts_by_source_semantics']
    assert report['raw_indexed_at_or_unknown_level']==124
    assert report['raw_unrepresented']==107  # source-ranked Mark now executable, acquisition still unverified
    assert sum(cats.values())==124
    assert cats['source_explicitly_removed']==5
    assert cats['source_precombat_setup_unmodeled']>0
    assert cats['active_or_uncertain_nonsetup_unrepresented']>0
    assert report['full_source_gameplay_coverage_proven'] is False
    assert report['setup_effects_and_gameplay_unlocks_still_require_source_modeling'] is True
    assert all(row['source_url'].startswith('https://www.wowhead.com/forever/spell=')
               for row in report['unrepresented_nonsetup_records'])


def test_candidate_time_pruning_is_explicit_not_fake_complete():
    c=prepare_candidate(class_key='druid',level=20,stage=WINNER)
    with pytest.raises(ValueError,match='finite and positive'):
        evaluate_persistent_candidate(c,level=20,mobs=2,max_wall_s=-1)
    short=evaluate_persistent_candidate(c,level=20,mobs=100,max_wall_s=1e-12)
    assert short['status']=='BLOCKED_EVALUATION_TIME_BUDGET'
    assert short['mob_completed']<100
    assert 'mean_s_per_mob' not in short
    full=evaluate_persistent_candidate(c,level=20,mobs=100,max_wall_s=10.)
    assert full['status']=='COMPLETE' and full['count']==100


def test_tampered_persistent_score_cannot_inflate_checkpoint_count():
    # Tiny stub of post-search result: no historical winner enters the search.
    obj={'class_key':'druid','level':20,'screening':{'winner':True},
         'profile_results':[{'source_context_sha256':'test-source'}],
         'persistent_winner':{'stage':WINNER,'persistent':{'mean_s_per_mob':-1}}}
    with pytest.raises(ValueError,match='COLD_PERSISTENT_REPLAY_MISMATCH'):
        validate(obj)
