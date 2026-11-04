"""PROCESS v2: equipped-weapon dependencies require canonical source facts."""
from types import SimpleNamespace

from src.game.checkpoint_p3_smoke import (
    fast_p3_smoke_for_policy,
    policy_uses_equipped_weapon_damage,
    policy_uses_equipped_weapon_mean_hit,
    policy_uses_weapon_damage,
)
from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.mage import build_source_slice as build_mage_source_slice
from src.game.data.forever.priest import build_source_slice as build_priest_source_slice
from src.rulesets.forever.items.catalogue import ItemRecord


def _policy(action_id):
    return SimpleNamespace(
        id="source:" + action_id,
        rules=(SimpleNamespace(action_id=action_id),),
    )


def _source_fact(
    *,
    source_stat="weapon_dps",
    damage_source_kind="equipped_weapon",
    weapon_speed_semantics="equipped",
):
    return SimpleNamespace(
        source_stat=source_stat,
        damage_source_kind=damage_source_kind,
        weapon_speed_semantics=weapon_speed_semantics,
    )


def test_real_druid_l20_claw_flat_anchor_is_equipped_dps_not_equipped_mean_hit():
    ir = build_source_slice(20)
    claw = next(action for action in ir.actions if action.family_key == "claw")
    policy = _policy(claw.id)
    assert policy_uses_weapon_damage(ir, policy) is True
    effect = next(effect for effect in claw.effects if effect.effect_type == "weapon_damage")
    assert effect.damage_source.flat_dps > 0
    assert effect.damage_source.dps_stat_id is None
    assert policy_uses_equipped_weapon_damage(ir, policy) is True
    assert policy_uses_equipped_weapon_mean_hit(ir, policy) is False


def test_source_druid_claw_requires_equipped_dps_but_not_mean_hit(monkeypatch):
    weapon = ItemRecord(
        94001,
        "Feral stat mace",
        "two_hand",
        item_level=21,
        required_level=19,
        stamina=5,
        weapon_dps=10,
        weapon_min_damage=11,
        weapon_max_damage=29,
    )
    monkeypatch.setattr(
        "src.game.checkpoint_p3_smoke.available_items",
        lambda *args, **kwargs: (weapon,),
    )
    ir = build_source_slice(20)
    claw = next(action for action in ir.actions if action.family_key == "claw")
    result = fast_p3_smoke_for_policy(
        source_ir=ir,
        policy=_policy(claw.id),
        class_key="druid",
        level=20,
        weights={"stamina": 0.1, "weapon_dps": 0},
        weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
    )
    assert result["p3_pass"] is False
    assert "MISSING_APPLICABLE_DPS_WEIGHT" in result["blockers"]
    assert "MISSING_WEIGHT:mean_weapon_hit_damage" not in result["blockers"]
    assert result["weapon_damage_dependent"] is False
    assert result["equipped_weapon_dps_relevant"] is True
    assert result["slots"]["weapon"]["items"][0]["score"] == 0.5


def test_equipped_weapon_action_requires_matching_mode_source_and_both_weights(monkeypatch):
    weapon = ItemRecord(
        94002,
        "Strike axe",
        "two_hand",
        item_level=20,
        required_level=19,
        stamina=5,
        weapon_dps=10,
        weapon_min_damage=11,
        weapon_max_damage=29,
    )
    monkeypatch.setattr(
        "src.game.checkpoint_p3_smoke.available_items",
        lambda *args, **kwargs: (weapon,),
    )
    fact = _source_fact()
    monkeypatch.setattr(
        "src.game.gear._weapon_facts_for_ir",
        lambda _ir: ((fact, "human"),),
    )
    action = SimpleNamespace(
        id="strike",
        requirements=({"kind": "mode_is", "value": "human"},),
        effects=(
            SimpleNamespace(
                effect_type="weapon_damage",
                damage_source=SimpleNamespace(
                    kind="equipped_weapon",
                    dps_stat_id="weapon_dps",
                    flat_dps=0,
                ),
            ),
        ),
    )
    ir = SimpleNamespace(
        id="melee-ir",
        actor=SimpleNamespace(metadata={"class_key": "warrior"}),
        actions=(action,),
        auto_attacks=(),
    )
    policy = _policy("strike")
    assert policy_uses_equipped_weapon_damage(ir, policy) is True
    assert policy_uses_equipped_weapon_mean_hit(ir, policy) is True
    result = fast_p3_smoke_for_policy(
        source_ir=ir,
        policy=policy,
        class_key="warrior",
        level=20,
        weights={"stamina": 1, "weapon_dps": 0},
        weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
    )
    assert "MISSING_APPLICABLE_DPS_WEIGHT" in result["blockers"]
    assert "MISSING_WEIGHT:mean_weapon_hit_damage" in result["blockers"]
    assert result["source_policy"]["equipped_weapon_damage_relevant"] is True
    assert result["source_policy"]["equipped_weapon_mean_hit_relevant"] is True
    assert result["source_policy"]["equipped_weapon_dependency_derived_from_canonical_mode_facts_only"] is True


def test_flat_dps_anchor_with_canonical_equipped_source_fact_is_applicable(monkeypatch):
    # The real gear applicator replaces a flat-DPS anchor by source kind/mode,
    # even when no actor stat ID is present on the original damage source.
    fact = _source_fact(source_stat="weapon_dps")
    monkeypatch.setattr(
        "src.game.gear._weapon_facts_for_ir",
        lambda _ir: ((fact, "human"),),
    )
    action = SimpleNamespace(
        id="flat-strike",
        requirements=({"kind": "mode_is", "value": "human"},),
        effects=(
            SimpleNamespace(
                effect_type="weapon_damage",
                damage_source=SimpleNamespace(
                    kind="equipped_weapon", dps_stat_id=None, flat_dps=12.0,
                ),
            ),
        ),
    )
    ir = SimpleNamespace(
        id="flat-anchor-ir",
        actor=SimpleNamespace(metadata={"class_key": "warrior"}),
        actions=(action,),
        auto_attacks=(),
    )
    policy = _policy("flat-strike")
    assert policy_uses_equipped_weapon_damage(ir, policy) is True
    assert policy_uses_equipped_weapon_mean_hit(ir, policy) is True


def test_mode_free_proxy_autoattack_without_source_fact_is_not_equipped_weapon_dependency():
    auto = SimpleNamespace(
        id="mage:wand-auto",
        required_mode_id=None,
        damage_source=SimpleNamespace(
            kind="qualified_wand_dps_proxy",
            dps_stat_id="wand_dps",
        ),
    )
    ir = SimpleNamespace(
        id="mage-ir",
        actions=(SimpleNamespace(id="wand-policy", effects=()),),
        auto_attacks=(auto,),
    )
    policy = _policy("wand-policy")
    assert policy_uses_equipped_weapon_damage(ir, policy) is False
    assert policy_uses_equipped_weapon_mean_hit(ir, policy) is False


def test_proxy_action_effect_without_a_matching_source_fact_is_not_equipped_weapon(monkeypatch):
    monkeypatch.setattr("src.game.gear._weapon_facts_for_ir", lambda _ir: ())
    action = SimpleNamespace(
        id="wand-shot",
        requirements=({"kind": "mode_is", "value": "human"},),
        effects=(
            SimpleNamespace(
                effect_type="weapon_damage",
                damage_source=SimpleNamespace(
                    kind="qualified_wand_dps_proxy",
                    dps_stat_id="wand_dps",
                    flat_dps=0,
                ),
            ),
        ),
    )
    ir = SimpleNamespace(
        id="mage-ir",
        actor=SimpleNamespace(metadata={"class_key": "mage"}),
        actions=(action,),
        auto_attacks=(),
    )
    policy = _policy("wand-shot")
    assert policy_uses_equipped_weapon_damage(ir, policy) is False
    assert policy_uses_equipped_weapon_mean_hit(ir, policy) is False


def test_mode_free_source_fact_backed_autoattack_requires_dps_and_equipped_mean_hit(monkeypatch):
    fact = _source_fact()
    monkeypatch.setattr(
        "src.game.gear._weapon_facts_for_ir",
        lambda _ir: ((fact, None),),
    )
    auto = SimpleNamespace(
        id="warrior:auto",
        required_mode_id=None,
        damage_source=SimpleNamespace(
            kind="equipped_weapon",
            dps_stat_id="weapon_dps",
        ),
    )
    ir = SimpleNamespace(
        id="warrior-ir",
        actor=SimpleNamespace(metadata={"class_key": "warrior"}),
        actions=(SimpleNamespace(id="rally", effects=(), requirements=()),),
        auto_attacks=(auto,),
    )
    policy = _policy("rally")
    assert policy_uses_equipped_weapon_damage(ir, policy) is True
    assert policy_uses_equipped_weapon_mean_hit(ir, policy) is True


def test_form_fixed_source_fact_backed_autoattack_needs_dps_but_not_equipped_mean_hit(monkeypatch):
    fact = _source_fact(weapon_speed_semantics="form_fixed")
    monkeypatch.setattr(
        "src.game.gear._weapon_facts_for_ir",
        lambda _ir: ((fact, "cat"),),
    )
    auto = SimpleNamespace(
        id="druid:cat-auto",
        required_mode_id="cat",
        damage_source=SimpleNamespace(
            kind="equipped_weapon",
            dps_stat_id="weapon_dps",
        ),
    )
    ir = SimpleNamespace(
        id="druid-ir",
        actor=SimpleNamespace(metadata={"class_key": "druid"}),
        actions=(SimpleNamespace(
            id="cat-policy", effects=(),
            requirements=({"kind": "mode_is", "value": "cat"},),
        ),),
        auto_attacks=(auto,),
    )
    policy = _policy("cat-policy")
    assert policy_uses_equipped_weapon_damage(ir, policy) is True
    assert policy_uses_equipped_weapon_mean_hit(ir, policy) is False


def test_qualified_mage_and_priest_wand_proxies_are_not_equipped_weapon_dependencies():
    for source_ir in (
        build_mage_source_slice(20),
        build_priest_source_slice(20),
    ):
        policy = source_ir.policies[0]
        assert policy_uses_equipped_weapon_damage(source_ir, policy) is False
        assert policy_uses_equipped_weapon_mean_hit(source_ir, policy) is False


def test_caster_wrath_is_not_equipped_weapon_dependent():
    ir = build_source_slice(20)
    wrath = next(action for action in ir.actions if action.family_key == "wrath")
    assert not policy_uses_equipped_weapon_damage(ir, _policy(wrath.id))
    assert not policy_uses_equipped_weapon_mean_hit(ir, _policy(wrath.id))


def test_negative_weight_still_fails_feral_exception(monkeypatch):
    item = ItemRecord(
        94003,
        "Cloak",
        "back",
        item_level=20,
        required_level=1,
        stamina=3,
    )
    monkeypatch.setattr(
        "src.game.checkpoint_p3_smoke.available_items",
        lambda *args, **kwargs: (item,),
    )
    ir = build_source_slice(20)
    claw = next(action for action in ir.actions if action.family_key == "claw")
    result = fast_p3_smoke_for_policy(
        source_ir=ir,
        policy=_policy(claw.id),
        class_key="druid",
        level=20,
        weights={"stamina": -0.1},
        weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
    )
    assert "NEGATIVE_WEIGHT:stamina" in result["blockers"]


def test_source_weapon_effect_without_damage_source_fails_closed():
    import pytest

    ir = SimpleNamespace(
        id="ir",
        actions=(
            SimpleNamespace(
                id="strike",
                effects=(
                    SimpleNamespace(
                        effect_type="weapon_damage",
                        damage_source=None,
                    ),
                ),
            ),
        ),
        auto_attacks=(),
    )
    with pytest.raises(ValueError, match="P3_UNRESOLVED_WEAPON_DAMAGE_SOURCE"):
        policy_uses_equipped_weapon_damage(ir, _policy("strike"))


def test_mode_bound_equipped_auto_cannot_force_caster_policy_weapon_weight():
    ir = SimpleNamespace(
        id="ir",
        actions=(SimpleNamespace(id="bolt", effects=()),),
        auto_attacks=(
            SimpleNamespace(
                id="cat-auto",
                required_mode_id="cat",
                damage_source=SimpleNamespace(
                    kind="equipped_weapon",
                    dps_stat_id="weapon_dps",
                ),
            ),
        ),
    )
    assert policy_uses_equipped_weapon_damage(ir, _policy("bolt")) is False
    assert policy_uses_equipped_weapon_mean_hit(ir, _policy("bolt")) is False
