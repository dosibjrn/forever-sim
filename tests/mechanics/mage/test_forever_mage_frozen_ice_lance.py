from src.rulesets.forever.classes.mage import engine as mage
from src.rulesets.forever.classes.mage import wowhead_facts as wh


def test_frostbite_constants_match_forever_tooltip():
    assert wh.FROSTBITE_PROC_CHANCE_PER_RANK == 0.05
    assert wh.FROSTBITE_ROOT_DURATION_S == 5.0


def test_action_selector_uses_ice_lance_on_real_frozen_root_not_only_fof():
    level = 40
    talents = mage.Talents(ice_lance=1)
    stats = mage.player_stats(level, talents, 1.0)
    cfg = mage.SimConfig()
    mob = mage.Mob(level+1, 1000.0, cfg.mob_speed, cfg.mob_swing, cfg.melee_reach)
    state = mage.State(10.0, 1000.0, stats.max_mana, stats.max_mana, 20.0)
    state.root_until = 14.0  # Frostbite/Nova-style real Frozen state.
    policy = mage.Policy('frost','frostbolt',use_proc_ice_lance=True,use_fireblast=False,use_nova=False,use_blink=False)
    action, rank = mage.choose_action(state, level, talents, stats, cfg, mob, policy, 1000.0)
    assert action == 'ice_lance'
    assert rank.spell == 'ice_lance'
