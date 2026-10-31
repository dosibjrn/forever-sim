"""WF335 integration fix: default action proxy is actually shipped."""
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_action_proxy import checkpoint_action_proxy_coverage
from src.v2.source_budgeted_prefix import source_prefix_envelope


def test_generic_proxy_is_present_and_keeps_unresolved_visible():
    ir=build_game_ir_slice(class_key='druid',level=20)
    proxy=checkpoint_action_proxy_coverage(ir,level=20)
    assert proxy['source_ir_id']==ir.id
    assert proxy['proxy_not_s_per_mob']
    assert {x['action_id'] for x in proxy['ir_actions']}=={
        a.id for a in ir.actions if a.owner_actor_id==ir.actor.id
        and all(int(r['value'])<=20 for r in a.requirements if r.get('kind')=='minimum_level')}
    assert all(not x['is_zero_utility_proven'] for x in proxy['ir_actions'])
    envelope=source_prefix_envelope(ir,level=20)
    assert envelope['l0_action_proxy_coverage']['source_ir_id']==ir.id
    assert not envelope['l0_priored_candidate_order_applied']
