"""Regression: old rating-labelled API must NOT revive TBC scaling."""
from math import isclose
from dataclasses import dataclass,field
from src.game.data.forever.source_checkpoint_p3_ratings import (
    rating_to_chance,apply_provisional_rating_delta,SOURCE_STATUS)
from src.game.runtime.simulator import expected_incoming_attack
from src.game.model.ir import IncomingAttackDefinition

@dataclass
class FakeActor: stats:dict
@dataclass(frozen=True)
class Actor:base_stats:dict
@dataclass(frozen=True)
class IR:actor:Actor;provenance:dict=field(default_factory=dict)

def test_legacy_api_normalizes_to_displayed_percent_not_tbc():
    assert isclose(rating_to_chance('hit',10,level=20)['channel_deltas']['melee_hit_bonus'],.01)
    assert isclose(rating_to_chance('hit',10,level=60)['channel_deltas']['melee_hit_bonus'],.01)
    assert isclose(rating_to_chance('crit',14,level=20)['channel_deltas']['melee_crit_chance'],.01)
    assert rating_to_chance('crit',14,level=20)['status']==SOURCE_STATUS

def test_incoming_attack_consumes_miss_and_dodge_without_affecting_spell_hits():
    atk=lambda school:IncomingAttackDefinition('test','test','mob','actor',school,100.,.9,'health')
    plain=expected_incoming_attack(atk('physical'),actor=FakeActor({}))
    guarded=expected_incoming_attack(atk('physical'),actor=FakeActor({'dodge_chance':.02,'incoming_miss_chance_bonus':.03}))
    assert isclose(plain['post_mitigation_damage'],90.)
    assert isclose(guarded['post_mitigation_damage'],85.5)
    assert isclose(expected_incoming_attack(atk('arcane'),actor=FakeActor({'dodge_chance':.02,'incoming_miss_chance_bonus':.03}))['post_mitigation_damage'],90.)

def test_old_api_applies_skill_points_without_mutating_original():
    original=IR(Actor({'strength':5}))
    changed=apply_provisional_rating_delta(original,'defense',5,level=20)
    assert isclose(changed.actor.base_stats['dodge_chance'],.002)
    assert original.actor.base_stats=={'strength':5}
