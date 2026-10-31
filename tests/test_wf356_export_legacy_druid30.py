import pytest
from tools.wf356_export_legacy_druid30 import export_legacy_winner


def snapshot():
    best={'level':30,'talent_ranks':{'ferocity':5,'heart_of_the_wild':5,'furor':5,'naturalist':5,'shredding_attacks':1},
          'gear_stats':{'slots':{'head':{'item_id':123}}},'rotation':'Claw','combat_profile':'cat','score_s_per_100':2000}
    return {'engine':'v2-forever-experimental-class','game':{'ruleset':'forever','class_name':'druid'},
            'phase':'complete','running':False,'config':{'beam_width':4},
            'views':{'experimental':{'level_summaries':[{'level':30,'best':best}]}}}


def test_independent_legacy_export_preserves_candidate():
    r=export_legacy_winner(snapshot(),snapshot_sha256='a'*64)
    assert r['P7_comparable_replay']=='NOT_RUN'
    assert r['talent_points']==21
    assert r['gear']['slots']['head']['item_id']==123
    assert r['rotation']=='Claw'

@pytest.mark.parametrize('mod,code',[
    (lambda s:s.update(phase='searching'),'LEGACY_SEARCH_NOT_COMPLETED'),
    (lambda s:s.update(game={'ruleset':'forever','class_name':'mage'}),'WRONG_LEGACY_CLASS'),
    (lambda s:s['views']['experimental']['level_summaries'].clear(),'NOT_ONE_LEGACY_L30_SEARCH_RESULT'),
    (lambda s:s['views']['experimental']['level_summaries'][0]['best']['gear_stats'].update(slots={}), 'LEGACY_NAMED_GEAR_INCOMPLETE'),
    (lambda s:s['views']['experimental']['level_summaries'][0]['best'].update(rotation=''), 'LEGACY_POLICY_INCOMPLETE'),
])
def test_fail_closed_cases(mod,code):
    s=snapshot();mod(s)
    with pytest.raises(ValueError, match=code): export_legacy_winner(s,snapshot_sha256='a'*64)
