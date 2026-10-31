"""WF402 RED: resume paid 4->20->100 work without replay or false acceptance."""
import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import search_bounded_joint_frontier
from src.v2.source_joint_progress import load_verified_joint_progress

ROOT = Path(__file__).resolve().parents[1]


def source():
    ir = build_game_ir_slice(class_key='druid', level=30,
        ability_db_path=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite')
    stage = json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    stage['allocation'] = {'furor': 5, 'ferocity': 5, 'genesis': 5,
                           'naturalist': 5, 'feral_instinct': 1}
    return ir, stage


def search(ir, stage, path, **overrides):
    kw = dict(class_key='druid', level=30, source_ir=ir, seed_stage=stage,
        max_talents=2, max_gear_moves=0, max_policies=3,
        max_recovery_policies=2, max_paid_builds=5, max_cpu_s=35.,
        per_candidate_wall_s=12., screen_then_finalists=True,
        max_finalists=2, pack_size=2, qualification_mobs=12,
        max_qualifiers=3, progress_path=path)
    kw.update(overrides)
    return search_bounded_joint_frontier(**kw)


def run_interruption(tmp_path, horizon, number):
    ir, stage = source()
    path = tmp_path/'journal.json'
    seen = Counter()
    def paid(candidate, *, mobs, **kwargs):
        seen[mobs] += 1
        if mobs == horizon and seen[mobs] == number:
            raise KeyboardInterrupt('external interruption')
        return {'status': 'COMPLETE', 'mean_s_per_mob': 18. + mobs/100.,
                'mob_completed': mobs, 'events': mobs*9,
                'elapsed_cpu_s': .001, 'outer_wall_s': .001}
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation', side_effect=paid):
        with pytest.raises(KeyboardInterrupt):
            search(ir, stage, path)
        before = load_verified_joint_progress(path)
        assert before['status'] == 'IN_PROGRESS_NOT_CERTIFIED'
        result = search(ir, stage, path, resume_progress=True)
    after = load_verified_joint_progress(path)
    assert after['status'] == 'FINISHED_NOT_CERTIFIED'
    assert result['complete_100mob_candidates'] == 2
    assert result['paid_candidates'] == 5
    assert result['unique_full_builds'] == 5
    assert after['complete_100mob_candidates'] == 2
    assert after['events'] == 5*4*9 + 3*12*9 + 2*100*9
    assert result['events'] == after['events']
    assert result['winner']['mobs'] == 100
    assert result['eligible_for_checkpoint_acceptance'] is False
    assert result['source_legal_gear_universe_verified'] is False
    assert seen == Counter({4: 6 if horizon == 4 else 5,
                            12: 4 if horizon == 12 else 3,
                            100: 3 if horizon == 100 else 2})
    assert result['wall_s'] == pytest.approx(after['wall_s_at_snapshot'], abs=.05)
    return ir, stage, path


def test_resume_during_paid_four_mob_screening_without_repeating_completed_screens(tmp_path):
    run_interruption(tmp_path, 4, 3)


def test_resume_during_twelve_mob_survival_qualification_without_repeating_completed_qualifiers(tmp_path):
    run_interruption(tmp_path, 12, 2)


def test_resume_during_full_100mob_finalists_preserves_first_winner_without_replaying_it(tmp_path):
    run_interruption(tmp_path, 100, 2)


def test_resume_rejects_changed_search_context(tmp_path):
    ir, stage = source()
    path = tmp_path/'journal.json'
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',
               side_effect=KeyboardInterrupt('abort')):
        with pytest.raises(KeyboardInterrupt):
            search(ir, stage, path)
    with pytest.raises(ValueError, match='SOURCE_JOINT_PROGRESS_INTEGRITY'):
        search(ir, stage, path, resume_progress=True, max_policies=2)


def test_real_source_2d_resumed_search_reaches_100_mobs(tmp_path):
    from src.v2 import source_bounded_joint_frontier as f
    ir, stage = source()
    path = tmp_path/'real.json'
    real = f.isolated_joint_evaluation
    seen = Counter()
    def interrupt_once(candidate, *, mobs, **kwargs):
        seen[mobs] += 1
        if mobs == 4 and seen[mobs] == 2:
            raise KeyboardInterrupt('interrupt real paid search')
        return real(candidate, mobs=mobs, **kwargs)
    kwargs = dict(max_talents=1, max_gear_moves=0, max_policies=2,
                  max_recovery_policies=1, max_paid_builds=2,
                  max_cpu_s=60., per_candidate_wall_s=24.,
                  qualification_mobs=12, max_qualifiers=2, max_finalists=1)
    with patch.object(f, 'isolated_joint_evaluation', side_effect=interrupt_once):
        with pytest.raises(KeyboardInterrupt):
            search(ir, stage, path, **kwargs)
        result = search(ir, stage, path, resume_progress=True, **kwargs)
    assert result['complete_100mob_candidates'] == 1, result
    assert result['winner']['mobs'] == 100
    assert result['winner']['full_events'] > 1000
    assert result['winner']['seconds_per_mob'] > 0
    assert seen[4] == 3  # 1 completed, 1 interrupted, 1 resumed
    assert result['eligible_for_checkpoint_acceptance'] is False


def test_resumed_finalist_time_is_not_relabelled_as_qualification_wall(tmp_path):
    import time
    ir, stage = source()
    path = tmp_path/'phase.json'
    seen = Counter()
    def paid(candidate, *, mobs, **kwargs):
        seen[mobs] += 1
        if mobs == 100 and seen[mobs] == 1:
            time.sleep(.15)
        if mobs == 100 and seen[mobs] == 2:
            raise KeyboardInterrupt('second full interrupted')
        return {'status':'COMPLETE','mean_s_per_mob':20.,'mob_completed':mobs,
                'events':mobs*5,'elapsed_cpu_s':.001}
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',side_effect=paid):
        with pytest.raises(KeyboardInterrupt):
            search(ir,stage,path)
        prior=load_verified_joint_progress(path)['phase_wall_s']
        assert prior['finalist'] >= .14
        result=search(ir,stage,path,resume_progress=True)
    assert result['qualification_phase_wall_s'] <= prior['qualification']+.04
    assert result['finalist_phase_wall_s'] >= prior['finalist']
    assert result['wall_s'] == pytest.approx(sum((result['screen_phase_wall_s'],
        result['qualification_phase_wall_s'],result['finalist_phase_wall_s'])),abs=.02)


def test_cli_can_resume_existing_journal_without_overwriting_output(tmp_path):
    from tools.wf400_paid_joint_with_journal import run
    progress=tmp_path/'progress.json'
    output=tmp_path/'result.json'
    kwargs=dict(class_key='druid',level=30,
        ability_db=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite',
        seed_stage=ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json',
        output=output,progress=progress,budget_s=30.,pack_size=2,
        max_talents=1,max_gear_moves=0,max_policies=2,
        max_recovery_policies=1,max_paid_builds=2,max_finalists=1,
        per_candidate_s=10.,qualification_mobs=12,max_qualifiers=2)
    seen=Counter()
    def paid(candidate,*,mobs,**kw):
        seen[mobs]+=1
        if mobs==4 and seen[mobs]==2:
            raise KeyboardInterrupt('external stop')
        return {'status':'COMPLETE','mean_s_per_mob':19.,
                'mob_completed':mobs,'events':mobs*5,'elapsed_cpu_s':.001}
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',side_effect=paid):
        with pytest.raises(KeyboardInterrupt):
            run(**kwargs)
        assert progress.exists() and not output.exists()
        result=run(**kwargs,resume=True)
    assert output.exists()
    assert result['complete_100mob_candidates']==1
    assert seen[4]==3
    with pytest.raises(FileExistsError,match='REFUSE_OVERWRITE_PAID_JOINT_RESULT'):
        run(**kwargs,resume=True)


def test_marginal_source_scheduler_resume_matches_independent_uninterrupted_search(tmp_path):
    ir,stage=source()
    kwargs=dict(max_paid_builds=8,max_policies=3,max_talents=2,
                max_gear_moves=0,max_recovery_policies=2,
                proposal_strategy='marginal_screen')
    seen=Counter()
    def paid(candidate,*,mobs,**kw):
        seen[mobs]+=1
        if mobs==4 and seen[mobs]==7:
            raise KeyboardInterrupt('marginal suffix interrupted')
        return {'status':'COMPLETE','mean_s_per_mob':20.+(len(candidate.policy.rules)%3)*.25+mobs/100.,
                'mob_completed':mobs,'events':mobs*6,'elapsed_cpu_s':.001}
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',side_effect=paid):
        with pytest.raises(KeyboardInterrupt):
            search(ir,stage,tmp_path/'resumed.json',**kwargs)
        resumed=search(ir,stage,tmp_path/'resumed.json',resume_progress=True,**kwargs)
    def normal(candidate,*,mobs,**kw):
        return {'status':'COMPLETE','mean_s_per_mob':20.+(len(candidate.policy.rules)%3)*.25+mobs/100.,
                'mob_completed':mobs,'events':mobs*6,'elapsed_cpu_s':.001}
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',side_effect=normal):
        fresh=search(ir,stage,tmp_path/'fresh.json',**kwargs)
    identity=lambda result:[(r['allocation'],r['gear_move'],r['policy_signature'],r['recovery'])
                            for r in result['rows']]
    assert identity(resumed)==identity(fresh)
    assert resumed['events']==fresh['events']
    assert resumed['winner']['seconds_per_mob']==fresh['winner']['seconds_per_mob']
    assert resumed['complete_100mob_candidates']==fresh['complete_100mob_candidates']==2
    assert seen[4]==9  # eight successful 4mob screens plus one interrupted
