import json
from pathlib import Path
from src.v2.source_joint_feedback import trace_joint_feedback

def test_real_source_evaluated_feedback_trace():
    doc=json.loads(Path('WF_GEN03A1_DRUID_L20_DISCOVERY_v0.11.48.203.json').read_text())
    states=[doc['winner'],*doc['alternatives']]
    result=trace_joint_feedback(states)
    assert result['converged']
    assert result['trace'][-1]['score_s_per_mob'] < result['trace'][0]['score_s_per_mob']
    assert result['trace'][-1]['score_s_per_mob'] == result['global_grid_winner']['score_s_per_mob']
    assert {x['axis'] for x in result['trace']}=={'initial','gear','talents'}
    assert result['trace'][0]['branch'] != result['trace'][1]['branch']
