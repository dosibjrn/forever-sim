"""G46b: source-grounded long-duration stat maintenance compared to unbuffed Mage."""
from src.game.data.forever.mage import build_source_slice
from src.v2.generic_backend import _policy_combat_evaluation

def test_arcane_intellect_maintenance_changes_executable_starting_mana():
    for level in (10,15,20):
        buff=build_source_slice(level)
        bare=build_source_slice(level,arcane_intellect_maintenance=False)
        m=lambda ir: next(x for x in ir.resources if x.id=='mana')
        assert m(buff).capacity-m(bare).capacity==30
        assert m(buff).initial_amount-m(bare).initial_amount==30
        assert buff.actor.base_stats['intellect']==2
        assert bare.actor.base_stats['intellect']==0
        fact=next(x for x in buff.source_facts if x.get('spell_id')==1459)
        assert fact['duration_s']==1800 and fact['cast_mana']==60
        assert 'outside_single_combat' in fact['amortization']

def test_arcane_intellect_changes_real_generic_evaluation_without_runtime_fork():
    buff=build_source_slice(20)
    bare=build_source_slice(20,arcane_intellect_maintenance=False)
    ev_b,ex_b,_=_policy_combat_evaluation(buff,level=20)
    ev_u,ex_u,_=_policy_combat_evaluation(bare,level=20)
    assert ev_b is not None and ev_u is not None
    assert ex_b.timeline.target_defeated and ex_u.timeline.target_defeated
    assert ev_b.as_dict()!=ev_u.as_dict() or ex_b.as_dict()!=ex_u.as_dict()
