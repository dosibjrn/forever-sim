"""Reject a suboptimal self-certified checkpoint; no oracle search seeding."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from tools.wf365_druid_l30_reaudit import compare_heldout,run


def record(score, **changes):
    return {**{'status':'COMPLETE','count':100,'mean_s_per_mob':score,
        'source_db_sha256':'same-real-verified-source','recovery_policy':{'health_fraction':0.25}},**changes}


def test_prior_source_legal_candidate_falsifies_self_saturation():
    verdict=compare_heldout(accepted=record(16.7097568666),challenger=record(16.2875958252))
    assert verdict['falsified'] is True
    assert verdict['absolute_gap_s_per_mob'] == pytest.approx(.4221610414)
    assert verdict['same_100_mob_objective'] is True


def test_no_forged_incomparable_challenger():
    for alteration in ({'status':'NOT_RUN'},{'count':2},{'source_db_sha256':'other'},
                       {'recovery_policy':{'health_fraction':0.01}}):
        with pytest.raises(ValueError):
            compare_heldout(accepted=record(17),challenger=record(15,**alteration))


def test_slower_candidate_does_not_revoke():
    assert not compare_heldout(accepted=record(15),challenger=record(17))['falsified']


def test_real_same_runtime_source_and_100_mobs(tmp_path):
    out=tmp_path/'revocation.json'
    report=run(out)
    assert json.loads(out.read_text())==report
    assert report['accepted_checkpoints_after_revocation']=='1/148'
    assert report['comparison']['falsified']
    assert report['bear_l30_primal_bite_source_action']
    assert report['replays']['claimed_wf360']['combat_s']==pytest.approx(1449)
    assert report['replays']['heldout_wf358']['combat_s']==pytest.approx(1448)
    assert report['holdout_used_as_search_seed'] is False
