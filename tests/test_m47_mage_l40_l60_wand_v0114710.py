from src.rulesets.forever.classes.mage import engine as mage


def _l40_old_build():
    return mage.Talents(
        imp_frostbolt=5, elemental_precision=5, ice_shards=5, permafrost=3,
        piercing_ice=3, frost_channeling=3, arctic_reach=2, winters_chill=5,
    )


def _l60_old_build():
    return mage.Talents(
        imp_frostbolt=5, elemental_precision=4, ice_shards=3, piercing_ice=3,
        frost_channeling=3, arctic_reach=2, improved_channeling=5,
        arcane_subtlety=2, arcane_concentration=5, arcane_impact=2,
        arcane_blast=1, arcane_meditation=3, imp_fireball=5,
        flame_throwing=2, impact=3, improved_flamestrike=2, pyroblast=1,
    )


def test_l40_l60_best_wands_match_named_gear_authority():
    # Runtime item authority is the canonical SQL catalogue.  The catalogue is
    # refreshed independently of this regression, so assert end-to-end identity
    # rather than freezing historical item names here.
    for level in (40, 60):
        wand = mage.best_wand(level)
        gear = mage.real_gear_snapshot(level)["slots"]["wand"]
        assert wand.name == gear["name"]
        assert wand.item_id == int(gear["item_id"])
        assert abs(wand.dmin - float(gear["weapon_min_damage"])) < 1e-9
        assert abs(wand.dmax - float(gear["weapon_max_damage"])) < 1e-9
        assert abs(wand.speed - float(gear["weapon_speed"])) < 1e-9
        assert abs(wand.dps - float(gear["wand_dps"])) < 0.02


def test_l40_l60_wand_cutoffs_remain_bounded_search_dimensions():
    cfg = mage.SimConfig()
    for level, talents in ((40, _l40_old_build()), (60, _l60_old_build())):
        ps = [p for p in mage.candidate_policies_for_build(level, talents, focused=True, school="frost")
              if p.primary == "frostbolt"]
        best = {}
        for p in ps:
            cutoff = int(p.wand_finisher_max_hits)
            if cutoff not in (0, 1, 2, 3):
                continue
            r = mage.simulate_chain(level, talents, p, cfg, n=8, seed=7)
            mph = 3600.0 / (float(r["total_s"]) / 8.0)
            old = best.get(cutoff)
            if old is None or mph > old[0]:
                best[cutoff] = (mph, r)
        assert set(best) == {0, 1, 2, 3}
        assert float(best[0][1].get("casts_wand_finisher", 0.0)) == 0.0
        for cutoff, (_mph, result) in best.items():
            # OOM fallback wanding is independent of the HP-finisher cutoff;
            # only the dedicated finisher casts are bounded by this policy knob.
            assert float(result.get("casts_wand_finisher", 0.0)) <= cutoff * 8 + 1e-9
