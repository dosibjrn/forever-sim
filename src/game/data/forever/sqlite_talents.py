from __future__ import annotations

"""SQLite-indexed Forever talents, with explicit rank/legality coverage gaps.

No class/talent inventory or special spell IDs are embedded here. The index
provides all family identities. An older normalized snapshot is read only from
SQLite and identified as such; a missing rank is never synthesized.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable

from src.game.model.ir import TalentDefinition, TalentModifier, TalentRankDefinition
from src.game.data.forever.talent_modifiers import normalize_talent_definition
from src.rulesets.forever.data.schema import TalentRecord


DEFAULT_DB = Path(__file__).resolve().parents[4] / 'data/forever/catalogue/forever_abilities.sqlite'
from .source_db_scope import active_ability_db


def _slug(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_').replace("_s_", 's_')


def _rank_one_tooltip(payload: dict) -> str | None:
    changed = payload.get('envChange') or {}
    before, after = changed.get('before') or {}, changed.get('after') or {}
    if str(before.get('rank') or '').lower() == 'rank 1' and after.get('text'):
        return str(after['text'])
    return None


def _source_action_targets(value: str) -> tuple[str, ...]:
    """Normalize the action list in source text, never a hand-selected class list."""
    return tuple(_slug(part) for part in re.split(r',\s*(?:and\s+)?|\s+and\s+', value) if part.strip())


def _parse_rank_tooltip(text: str, *, action_families: set[str], source: dict,
                        mode_labels: dict[str, str] | None = None,
                        stat_conversions: dict[tuple[str, str], tuple[dict, ...]] | None = None,
                        effect_scopes: dict[str, dict] | None = None):
    """Generic source wording -> executable action modifiers.

    Unknown effects stay blocked. Inactive action targets remain visible as
    coverage gaps, rather than silently changing the source effect's scope.
    """
    # A source-qualified scope may be broader than the abbreviated client
    # tooltip. Only the canonical SQLite scope fact may resolve that ambiguity.
    offensive_hit = re.fullmatch(
        r'Increases the range of your offensive (.+?) spells by (\d+(?:\.\d+)?)% '
        r'and improves your chance to hit by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if offensive_hit:
        scope = (effect_scopes or {}).get('spell_hit_bonus')
        if not scope or scope.get('scope_filter') != 'damage_spell':
            return (), (), 'offensive_spell_hit_scope_not_verified'
        fraction = float(offensive_hit.group(3)) * 0.01
        return (TalentModifier(kind='hit_chance_bonus',target_type='action_filter',
            target_id='damage_spell',value=fraction,
            provenance={'source':dict(source),'scope_authority':dict(scope),
                        'raw_text_summary':text,
                        'range_increase_pct':float(offensive_hit.group(2)) * 0.01,
                        'range_status':'travel_and_pull_distance_not_yet_modeled'}),), (), \
            'range_secondary_effect_not_executable'
    casting_regen = re.fullmatch(
        r'Allows (\d+(?:\.\d+)?)% of your Mana regeneration to continue while casting\.',
        text.strip(), re.IGNORECASE)
    if casting_regen:
        fraction = float(casting_regen.group(1)) * 0.01
        if not 0.0 <= fraction <= 1.0:
            return (), (), 'invalid_casting_mana_regeneration_fraction'
        return (TalentModifier(kind='actor_stat_flat',target_type='actor_stat',
            target_id='casting_mana_regen_fraction',value=fraction,
            provenance={'source':dict(source),'raw_text_summary':text,
                        'regeneration_basis':'shared_classic_proxy'}),), (), None
    # Generic passive modifiers whose scopes are described by the rank text.
    # Seal/Judgement damage is emitted by an event trigger, not by the
    # aura-maintenance action; it must modify the trigger's damage payload.
    seal_damage = re.fullmatch(
        r'Increases the damage done by your Seals and Judgements by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if seal_damage:
        return (TalentModifier(kind='effect_damage_pct', target_type='trigger_filter',
            target_id='seal_damage', value=float(seal_damage.group(1)) * .01,
            provenance={'source':dict(source),'raw_text_summary':text}),), (), None
    instant_cost = re.fullmatch(
        r'Reduces the Mana cost of all instant cast spells and abilities by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if instant_cost:
        return (TalentModifier(kind='resource_cost_pct', target_type='action_filter',
            target_id='instant_mana', value=-float(instant_cost.group(1))*.01,
            provenance={'source':dict(source),'raw_text_summary':text}),), (), None
    judge_cd = re.fullmatch(
        r'Decreases the cooldown of your (.+?) ability by (\d+(?:\.\d+)?) sec\.',
        text.strip(), re.IGNORECASE)
    if judge_cd:
        target=_slug(judge_cd.group(1))
        if target not in action_families:return (), (target,), 'source_cooldown_target_missing'
        return (TalentModifier(kind='cooldown_delta_s',target_type='action_family',
            target_id=target,value=-float(judge_cd.group(2)),
            provenance={'source':dict(source),'raw_text_summary':text}),), (), None
    melee_crit = re.fullmatch(
        r'Improves your chance to get a critical strike with melee attacks by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if melee_crit:
        return (TalentModifier(kind='actor_stat_flat',target_type='actor_stat',
            target_id='melee_crit_chance',value=float(melee_crit.group(1))*.01,
            provenance={'source':dict(source),'raw_text_summary':text}),), (), None
    strength_pct = re.fullmatch(r'Increases your (?:total )?Strength by (\d+(?:\.\d+)?)%\.',
        text.strip(),re.IGNORECASE)
    if strength_pct:
        return (TalentModifier(kind='actor_stat_pct',target_type='actor_stat',
            target_id='strength',value=float(strength_pct.group(1))*.01,
            provenance={'source':dict(source),'raw_text_summary':text}),), (), None
    # Compound cast-time + cost reduction. Both clauses must match; the
    # affected family and all numeric rank values come from the source text.
    cast_cost = re.fullmatch(
        r'Reduces the cast time of your (.+?) spell by (\d+(?:\.\d+)?) sec '
        r'and its Mana cost by (\d+(?:\.\d+)?)%\.', text.strip(), re.IGNORECASE)
    if cast_cost:
        targets=_source_action_targets(cast_cost.group(1))
        missing=tuple(x for x in targets if x not in action_families)
        if missing:return (),missing,'source_cast_cost_target_missing'
        return tuple(m for target in targets for m in (
            TalentModifier(kind='cast_time_delta_s',target_type='action_family',
                target_id=target,value=-float(cast_cost.group(2)),
                provenance={'source':dict(source),'raw_text_summary':text}),
            TalentModifier(kind='resource_cost_pct',target_type='action_family',
                target_id=target,value=-float(cast_cost.group(3))*0.01,
                provenance={'source':dict(source),'raw_text_summary':text}))),(),None
    # Source's Swipe damage clause executes in the common damage modifier
    # path. Stealth detection is separately flagged as unimplemented; it is
    # never silently equated to a complete talent implementation.
    damage_stealth = re.fullmatch(
        r'Increases damage done by your (.+?) ability by (\d+(?:\.\d+)?)% '
        r'and reduces the chance enemies have to detect you while Prowling '
        r'as if you were (\d+) level higher\.',text.strip(),re.IGNORECASE)
    if damage_stealth:
        targets=_source_action_targets(damage_stealth.group(1))
        missing=tuple(x for x in targets if x not in action_families)
        mods=tuple(TalentModifier(kind='effect_damage_pct',target_type='action_family',
            target_id=x,value=float(damage_stealth.group(2))*0.01,
            provenance={'source':dict(source),'raw_text_summary':text,
                'secondary_effect':'stealth_detection_level_bonus',
                'secondary_effect_value':int(damage_stealth.group(3)),
                'secondary_effect_status':'not_executable_in_current_solo_objective'})
            for x in targets if x in action_families)
        return mods,missing,'stealth_detection_secondary_effect_not_executable'
    patterns = (
        (r'Reduces the cost of your (.+?) abilities by (\d+(?:\.\d+)?) Rage or Energy\.',
         'resource_cost_flat', -1.0),
        (r'Increases the damage caused by your (.+?) abilities by (\d+(?:\.\d+)?)%\.',
         'effect_damage_pct', 0.01),
    )
    for expression, kind, scale in patterns:
        match = re.fullmatch(expression, text.strip(), re.IGNORECASE)
        if match is None:
            continue
        targets = _source_action_targets(match.group(1))
        active = tuple(t for t in targets if t in action_families)
        absent = tuple(t for t in targets if t not in action_families)
        mods = tuple(TalentModifier(
            kind=kind, target_type='action_family', target_id=target,
            value=float(match.group(2)) * scale,
            provenance={'authority': 'sqlite_spell_index_tooltip', 'source': dict(source),
                        'raw_text_summary': text, 'all_source_targets': list(targets)},
        ) for target in active)
        return mods, absent, (None if active else 'no_mentioned_actions_in_current_ir')
    # Shared mode-scoped melee crit bonus; mode names and magnitudes are
    # sourced from the canonical rank text, not a class/talent lookup table.
    mode_crit = re.fullmatch(
        r'Increases your critical strike chance while in (.+?) by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if mode_crit:
        labels = tuple(_slug(label) for label in re.split(r',\s*(?:or\s+)?|\s+or\s+', mode_crit.group(1)) if label.strip())
        modes = mode_labels or {}
        active = tuple(modes[label] for label in labels if label in modes)
        absent = tuple(label for label in labels if label not in modes)
        if not active:
            return (), absent, 'no_mentioned_modes_in_current_ir'
        return tuple(TalentModifier(kind='mode_stat_flat', target_type='mode',
            target_id=mode_id, value=float(mode_crit.group(2))*0.01,
            provenance={'source':dict(source),'raw_text_summary':text,
                        'target_stat':'melee_crit_chance','source_modes':list(labels)})
            for mode_id in active), absent, None

    # Movement speed is mode-scoped; Dodge is a global actor avoidance stat.
    # The movement stat is retained for later travel scoring, not credited as
    # a combat speedup. Dodge is consumed by incoming physical hit resolution.
    speed_dodge = re.fullmatch(
        r'Increases your movement speed while in (.+?) by (\d+(?:\.\d+)?)%, '
        r'and increases your chance to Dodge by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if speed_dodge:
        labels = tuple(_slug(label) for label in re.split(r',\s*(?:or\s+)?|\s+or\s+', speed_dodge.group(1)) if label.strip())
        modes = mode_labels or {}
        absent = tuple(label for label in labels if label not in modes)
        if absent or not labels:
            return (), absent, 'movement_source_mode_missing'
        mods = [TalentModifier(kind='actor_stat_flat',target_type='actor_stat',
            target_id='dodge_chance',value=float(speed_dodge.group(3))*0.01,
            provenance={'source':dict(source),'raw_text_summary':text})]
        mods.extend(TalentModifier(kind='mode_stat_flat',target_type='mode',
            target_id=modes[label],value=float(speed_dodge.group(2))*0.01,
            provenance={'source':dict(source),'raw_text_summary':text,
                        'target_stat':'movement_speed_pct'}) for label in labels)
        return tuple(mods), (), None

    # Mode transition resource rules. The names, ranks, chance, energy
    # retention, rate, cap and forbidden modes are all read from source text.
    # This grammar intentionally rejects any incomplete tooltip.
    entry = re.fullmatch(
        r'Gives you a (\d+(?:\.\d+)?)% chance to gain (\d+(?:\.\d+)?) (\w+) when shapeshifting into (.+?)\. '
        r'Shapeshifting into (.+?) restores (\d+(?:\.\d+)?)% of the (\w+) you had when last in (.+?), '
        r'plus (\d+(?:\.\d+)?) \7 per sec spent outside (.+?), up to (\d+(?:\.\d+)?) \7\.\s*'
        r'(.+?) forfeit this \7 and halt its restoration while active\.',
        text.strip(), re.IGNORECASE | re.DOTALL)
    if entry is not None:
        # Numeric regex group references are fixed grammar positions, not
        # game facts. All mode/resource identities come from the captured text.
        def mode_names(raw):
            return tuple(_slug(x) for x in re.split(r'\s*,\s*|\s+or\s+|\s+and\s+', raw) if x.strip())
        rage_labels = mode_names(entry.group(4))
        cat_labels = mode_names(entry.group(5))
        old_cat_labels = mode_names(entry.group(8))
        forbidden_labels = mode_names(entry.group(12))
        modes = mode_labels or {}
        absent = tuple(sorted({x for x in rage_labels + cat_labels + old_cat_labels + forbidden_labels if x not in modes}))
        if len(cat_labels) != 1 or cat_labels != old_cat_labels or cat_labels[0] not in modes:
            return (), absent, 'mode_entry_source_modes_missing_or_ambiguous'
        rage_resource, energy_resource = _slug(entry.group(3)), _slug(entry.group(7))
        chance=float(entry.group(1))*0.01
        gain=float(entry.group(2))
        retained=float(entry.group(6))*0.01
        regen=float(entry.group(9))
        maximum=float(entry.group(11))
        if not (0.0 <= chance <= 1.0 and 0.0 <= retained <= 1.0 and
                gain >= 0.0 and regen >= 0.0 and maximum >= 0.0):
            return (), (), 'mode_entry_source_numeric_bounds_invalid'
        expected_gain = chance*gain
        mods = [TalentModifier(kind='mode_entry_expected_gain', target_type='mode',
            target_id=modes[label], value=expected_gain,
            provenance={'source':dict(source),'raw_text_summary':text,'resource_id':rage_resource})
            for label in rage_labels if label in modes]
        mods.append(TalentModifier(kind='mode_entry_restore_last', target_type='mode',
            target_id=modes[cat_labels[0]], value=float(entry.group(6))*0.01,
            provenance={'source':dict(source),'raw_text_summary':text,'resource_id':energy_resource,
                'outside_regen_per_s':float(entry.group(9)), 'max_restored':float(entry.group(11)),
                'forbidden_mode_ids':[modes[label] for label in forbidden_labels if label in modes]}))
        return tuple(mods), absent, None
    spell_melee_crit = re.fullmatch(
        r'Increases your critical strike chance with spells and melee attacks by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if spell_melee_crit:
        return (TalentModifier(kind='crit_chance_pct',target_type='action_filter',
            target_id='spells_and_melee',value=float(spell_melee_crit.group(1))*0.01,
            provenance={'source':dict(source),'raw_text_summary':text}),), (), None
    spell_damage_crit = re.fullmatch(
        r'Increases the damage and critical strike chance of your (.+?) spell by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if spell_damage_crit:
        targets=_source_action_targets(spell_damage_crit.group(1))
        absent=tuple(t for t in targets if t not in action_families)
        if absent:
            return (),absent,'source_spell_damage_and_crit_target_missing'
        fraction=float(spell_damage_crit.group(2))*0.01
        return tuple(m for target in targets for m in (
            TalentModifier(kind='effect_damage_pct',target_type='action_family',
                target_id=target,value=fraction,
                provenance={'source':dict(source),'raw_text_summary':text}),
            TalentModifier(kind='crit_chance_pct',target_type='action_family',
                target_id=target,value=fraction,
                provenance={'source':dict(source),'raw_text_summary':text}))), (), None
    # Two independent, source-stated effects: a named cast-time reduction
    # and an all-damage increase. Never approximate the second as spell-only.
    cast_and_damage = re.fullmatch(
        r'Reduces the cast time of your (.+?) spell by (\d+(?:\.\d+)?) sec '
        r'and increases all damage you deal by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if cast_and_damage is not None:
        targets = _source_action_targets(cast_and_damage.group(1))
        absent = tuple(x for x in targets if x not in action_families)
        if absent:
            return (), absent, 'source_cast_target_missing'
        return (
            tuple(TalentModifier(kind='cast_time_delta_s', target_type='action_family',
                target_id=target, value=-float(cast_and_damage.group(2)),
                provenance={'source':dict(source),'raw_text_summary':text})
                for target in targets)
            + (TalentModifier(kind='effect_damage_pct', target_type='action_filter',
                target_id='all_damage', value=float(cast_and_damage.group(3))*0.01,
                provenance={'source':dict(source),'raw_text_summary':text}),)
        ), (), None
    # Base armor scaled by actor level and Defense above a source-specified
    # level threshold. Mode names and numeric values are taken from the rank
    # tooltip; executable modes are discovered from the current Game IR.
    armor = re.fullmatch(
        r'While in (.+?), you gain (\d+(?:\.\d+)?) additional base Armor per level '
        r'and another (\d+(?:\.\d+)?) base Armor for each point of defense skill '
        r'beyond (five|\d+(?:\.\d+)?) times your level\. '
        r'This amount can be further increased by multipliers from those forms\.',
        text.strip(), re.IGNORECASE)
    if armor is not None:
        labels = tuple(_slug(x) for x in re.split(r',\s*(?:or\s+)?|\s+or\s+', armor.group(1)) if x.strip())
        modes = mode_labels or {}
        active = tuple((label, modes[label]) for label in labels if label in modes)
        absent = tuple(label for label in labels if label not in modes)
        threshold_text = armor.group(4).lower()
        threshold = 5.0 if threshold_text == 'five' else float(threshold_text)
        mods = []
        for label, mode_id in active:
            for kind, value in (('mode_armor_per_level', float(armor.group(2))),
                                ('mode_armor_excess_defense', float(armor.group(3)))):
                mods.append(TalentModifier(
                    kind=kind, target_type='mode', target_id=mode_id, value=value,
                    provenance={'authority': 'sqlite_spell_index_tooltip', 'source': dict(source),
                                'raw_text_summary': text, 'source_mode_label': label,
                                'reference_level_multiplier': threshold,
                                'all_source_modes': list(labels)},
                ))
        return tuple(mods), absent, (None if active else 'no_mentioned_modes_in_current_ir')
    # Compound primary-stat talent: global percentage plus independently
    # source-declared mode percentages. Both stat-to-AP and stat-to-Resource
    # conversion facts are read from the same SQLite authority, not inferred
    # from the talent name, class, or a built-in stat conversion table.
    compound = re.fullmatch(
        r'Increases your ([A-Za-z_]+) by (\d+(?:\.\d+)?)%\. In addition, '
        r'while in (.+?) your ([A-Za-z_]+) is increased by (\d+(?:\.\d+)?)% '
        r'and while in (.+?) your ([A-Za-z_]+) is increased by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if compound is not None:
        global_stat = _slug(compound.group(1))
        mods = [TalentModifier(kind='actor_stat_pct', target_type='actor_stat',
                               target_id=global_stat, value=float(compound.group(2))*0.01,
                               provenance={'source': dict(source), 'raw_text_summary': text})]
        missing_modes = []
        for labels_text, stat, percent in ((compound.group(3), compound.group(4), compound.group(5)),
                                           (compound.group(6), compound.group(7), compound.group(8))):
            source_stat = _slug(stat)
            fraction = float(percent) * 0.01
            labels = tuple(_slug(label) for label in re.split(r',\s*(?:or\s+)?|\s+or\s+', labels_text)
                           if label.strip())
            for label in labels:
                mode_id = (mode_labels or {}).get(label)
                if mode_id is None:
                    missing_modes.append(label)
                    continue
                conversions = (stat_conversions or {}).get((label, source_stat), ())
                if not conversions:
                    # Without a derived combat/resource effect, this mode stat
                    # would silently count as an optimizer improvement/no-op.
                    return (), tuple(sorted(set(missing_modes))), 'source_stat_conversion_missing'
                mods.append(TalentModifier(kind='mode_stat_pct', target_type='mode',
                    target_id=mode_id, value=fraction,
                    provenance={'source': dict(source), 'raw_text_summary': text,
                                'source_stat': source_stat, 'source_mode_label': label}))
                for rule in conversions:
                    kind = ('mode_derived_stat_pct' if rule['target_type'] == 'stat'
                            else 'mode_resource_capacity_pct')
                    mods.append(TalentModifier(kind=kind, target_type='mode',
                        target_id=mode_id, value=fraction * float(rule['coefficient']),
                        provenance={'source': dict(source), 'raw_text_summary': text,
                                    'source_stat': source_stat, 'target_id': rule['target_id'],
                                    'conversion_authority': rule['authority'],
                                    'conversion_source_url': rule['source_url'],
                                    'conversion_coefficient': float(rule['coefficient'])}))
        if len(mods) <= 1:
            return (), tuple(sorted(set(missing_modes))), 'no_mentioned_modes_in_current_ir'
        return tuple(mods), tuple(sorted(set(missing_modes))), None
    # Multi-target duration extension: each source clause supplies its own
    # action families and seconds. A duration extension preserves the original
    # tick strength and interval (it does not spread old damage over more ticks).
    duration = re.fullmatch(
        r'Increases the duration of your (.+)\.', text.strip(), re.IGNORECASE)
    if duration:
        clauses = re.split(r',\s*(?:and\s+)?your\s+|\s+and\s+your\s+',
                           duration.group(1), flags=re.IGNORECASE)
        clauses = [re.sub(r'^your\s+', '', clause, flags=re.IGNORECASE) for clause in clauses]
        matches = [re.fullmatch(r'(.+?) spells? by (\d+(?:\.\d+)?) sec', clause, re.IGNORECASE)
                   for clause in clauses]
        if all(matches) and matches:
            targets = [(family, float(match.group(2))) for match in matches
                       for family in _source_action_targets(match.group(1))]
            active = [(family, seconds) for family, seconds in targets if family in action_families]
            missing = tuple(family for family, _ in targets if family not in action_families)
            mods = tuple(TalentModifier(kind='periodic_duration_delta_s',target_type='action_family',
                target_id=family,value=seconds,provenance={'source':dict(source),
                    'raw_text_summary':text,'all_source_targets':[x for x,_ in targets]})
                for family,seconds in active)
            return mods,missing,('duration_source_targets_missing' if missing else None)
    # Named action GCD reductions, including partially available action lists.
    gcd = re.fullmatch(
        r'Reduces the global cooldown by (\d+(?:\.\d+)?) seconds? on your (.+?) spells\.',
        text.strip(), re.IGNORECASE)
    if gcd:
        targets = _source_action_targets(gcd.group(2))
        missing = tuple(x for x in targets if x not in action_families)
        mods = tuple(TalentModifier(kind='gcd_delta_s',target_type='action_family',
            target_id=x,value=-float(gcd.group(1)),provenance={'source':dict(source),
                'raw_text_summary':text,'all_source_targets':list(targets)})
            for x in targets if x in action_families)
        return mods,missing,('gcd_source_targets_missing' if missing else None)
    # Separate resource-specific reductions must never reduce the *other*
    # resource on a mixed-resource action. Both source clauses are parsed.
    paired_cost = re.fullmatch(
        r'Reduces the (\w+) cost of your (.+?) ability by (\d+(?:\.\d+)?) '
        r'and reduces the (\w+) cost of your (.+?) ability by (\d+(?:\.\d+)?)\.',
        text.strip(), re.IGNORECASE)
    if paired_cost:
        specs = ((paired_cost.group(1),paired_cost.group(2),paired_cost.group(3)),
                 (paired_cost.group(4),paired_cost.group(5),paired_cost.group(6)))
        targets = [(family,_slug(resource),float(amount)) for resource,names,amount in specs
                   for family in _source_action_targets(names)]
        missing = tuple(family for family,_,_ in targets if family not in action_families)
        mods = tuple(TalentModifier(kind='resource_cost_flat',target_type='action_family',
            target_id=family,value=-amount,provenance={'source':dict(source),
                'raw_text_summary':text,'resource_id':resource,
                'all_source_targets':[x for x,_,_ in targets]})
            for family,resource,amount in targets if family in action_families)
        return mods,missing,('resource_cost_source_targets_missing' if missing else None)
    # Damage plus control resilience: damage is executable independently,
    # while the root break threshold is explicitly *not* silently simulated.
    damage_control = re.fullmatch(
        r'Increases the damage done by your (.+?) spell by (\d+(?:\.\d+)?)%, '
        r'and its victims can take up to (\d+(?:\.\d+)?)% more damage '
        r'without interrupting the effect\.',text.strip(),re.IGNORECASE)
    if damage_control:
        targets = _source_action_targets(damage_control.group(1))
        missing = tuple(x for x in targets if x not in action_families)
        mods = tuple(TalentModifier(kind='effect_damage_pct',target_type='action_family',
            target_id=x,value=float(damage_control.group(2))*0.01,
            provenance={'source':dict(source),'raw_text_summary':text,
                'secondary_effect':'control_break_damage_threshold',
                'secondary_value_pct':float(damage_control.group(3)),
                'secondary_status':'not_executable'}) for x in targets if x in action_families)
        return mods,missing,'control_break_secondary_effect_not_executable'
    # Source language is matched by effect category, not by spell/class name.
    # The target is resolved against executable IR actions in the generic
    # modifier executor; rank values and descriptions remain SQLite facts.
    category_patterns = (
        (r'Reduces the Mana cost of your damaging spells by (\d+(?:\.\d+)?)%\.',
         'resource_cost_pct', 'damage_spell', -0.01),
        (r'Reduces the mana cost of all shapeshifting by (\d+(?:\.\d+)?)%\.',
         'resource_cost_pct', 'shapeshift_mana', -0.01),
        (r'Increases the periodic damage and healing done by your spells and abilities by (\d+(?:\.\d+)?)%\.',
         'effect_periodic_pct', 'periodic', 0.01),
        (r'Increases the effect of all your healing spells by (\d+(?:\.\d+)?)%\.',
         'effect_healing_pct', 'healing', 0.01),
    )
    for expression, kind, target, scale in category_patterns:
        match = re.fullmatch(expression, text.strip(), re.IGNORECASE)
        if match:
            return (TalentModifier(kind=kind, target_type='action_filter',
                target_id=target, value=float(match.group(1))*scale,
                provenance={'source':dict(source),'raw_text_summary':text}),), (), None
    specific_heal = re.fullmatch(
        r'Increases the effect of your (.+?) spell by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if specific_heal:
        targets = _source_action_targets(specific_heal.group(1))
        active = tuple(x for x in targets if x in action_families)
        absent = tuple(x for x in targets if x not in action_families)
        return tuple(TalentModifier(kind='effect_healing_pct',target_type='action_family',
            target_id=x,value=float(specific_heal.group(2))*0.01,
            provenance={'source':dict(source),'raw_text_summary':text}) for x in active), absent, (
            None if active else 'no_mentioned_actions_in_current_ir')
    spell_cost = re.fullmatch(
        r'Reduces the mana cost of your (.+?) spells by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if spell_cost:
        targets = _source_action_targets(spell_cost.group(1))
        active = tuple(x for x in targets if x in action_families)
        absent = tuple(x for x in targets if x not in action_families)
        return tuple(TalentModifier(kind='resource_cost_pct',target_type='action_family',
            target_id=x,value=-float(spell_cost.group(2))*0.01,
            provenance={'source':dict(source),'raw_text_summary':text}) for x in active), absent, (
            None if active else 'no_mentioned_actions_in_current_ir')
    # A sourced critical-damage *bonus* scales the excess over the normal
    # crit multiplier, not the base spell damage.  The school list and value
    # come exclusively from the captured rank tooltip, never a class preset.
    school_critical_damage = re.fullmatch(
        r'Increases the critical strike damage bonus of your (.+?) spells by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if school_critical_damage:
        schools = _source_action_targets(school_critical_damage.group(1))
        if not schools or len(schools) != len(set(schools)):
            return (), (), 'invalid_source_critical_damage_school_scope'
        return (TalentModifier(kind='critical_damage_bonus_pct',
            target_type='action_filter',
            target_id='damage_schools:' + ','.join(schools),
            value=float(school_critical_damage.group(2)) * 0.01,
            provenance={'source':dict(source),'raw_text_summary':text}),), (), None
    school_damage = re.fullmatch(
        r'Increases the damage done by your (.+?) spells by (\d+(?:\.\d+)?)%\.',
        text.strip(), re.IGNORECASE)
    if school_damage:
        schools = _source_action_targets(school_damage.group(1))
        return (TalentModifier(kind='effect_damage_pct',target_type='action_filter',
            target_id='damage_schools:'+','.join(schools),
            value=float(school_damage.group(2))*0.01,
            provenance={'source':dict(source),'raw_text_summary':text}),), (), None
    return (), (), 'unparsed_effect_semantics'


# Kept as a compatibility alias for earlier parser tests; both parse arbitrary ranks.
_parse_rank_one_tooltip = _parse_rank_tooltip


@dataclass(frozen=True)
class SQLiteTalentInventory:
    talents: tuple[TalentDefinition, ...]
    blockers: tuple[dict, ...]
    captured_count: int
    expected_count: int | None
    batch_id: str
    source_db: str
    tree_rule: dict | None = None

    @property
    def complete(self) -> bool:
        return not self.blockers and self.expected_count == self.captured_count


def load_sqlite_talents(class_key: str, *, action_families: Iterable[str],
                        mode_labels: dict[str, str] | None = None,
                        db_path: Path | None = None, level: int | None = None) -> SQLiteTalentInventory:
    db = Path(db_path or active_ability_db(DEFAULT_DB))
    if not db.is_file():
        raise FileNotFoundError(f'canonical Forever abilities SQLite missing: {db}')
    conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        list_row = conn.execute('''SELECT * FROM capture_lists
            WHERE class_key=? AND kind='talents' ORDER BY batch_id DESC LIMIT 1''',
            (class_key.lower(),)).fetchone()
        if list_row is None or not int(list_row['complete']):
            raise ValueError(f'no complete SQLite talent index for {class_key}')
        rows = conn.execute('''SELECT * FROM spell_index
            WHERE class_key=? AND kind='talents' AND batch_id=? ORDER BY spell_id''',
            (class_key.lower(), list_row['batch_id'])).fetchall()
        if len(rows) != int(list_row['captured_count']):
            raise ValueError('SQLite talent index capture count mismatch')
        try:
            normalized_rows = conn.execute('''SELECT spell_id,snapshot_id,source_record_json
                FROM talent_normalized_records WHERE class_key=?''', (class_key.lower(),)).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError('normalized talent SQLite migration missing') from exc
        normalized = {int(r['spell_id']): r for r in normalized_rows}
        # Sourced per-rank trait curves override the old one-rank listview
        # observation, but never synthesize uncaptured ranks or effects.
        try:
            rank_facts: dict[int, list[sqlite3.Row]] = {}
            for fact in conn.execute('''SELECT * FROM talent_rank_source_facts
                    WHERE class_key=? ORDER BY spell_id,rank''', (class_key.lower(),)).fetchall():
                rank_facts.setdefault(int(fact['spell_id']), []).append(fact)
        except sqlite3.OperationalError:
            rank_facts = {}  # Older SQLite is still valid but rank coverage remains blocked.
        # Inherited stat conversions are explicit, source-versioned SQLite facts.
        # Missing conversion tables do not silently create a zero-effect talent.
        stat_conversions: dict[tuple[str, str], list[dict]] = {}
        try:
            conversion_rows = conn.execute('''SELECT * FROM stat_conversion_source_facts
                WHERE class_key=?''', (class_key.lower(),)).fetchall()
        except sqlite3.OperationalError:
            conversion_rows = []
        for conversion in conversion_rows:
            stat_conversions.setdefault((str(conversion['mode_label']),str(conversion['source_stat'])),[]).append(dict(conversion))
        try:
            scope_rows = conn.execute('''SELECT * FROM talent_effect_scope_source_facts
                WHERE class_key=?''', (class_key.lower(),)).fetchall()
        except sqlite3.OperationalError:
            scope_rows = []
        scope_facts = {}
        for fact in scope_rows:
            key=(int(fact['spell_id']),str(fact['scope_kind']))
            if key in scope_facts:
                raise ValueError('conflicting sourced talent effect scope')
            scope_facts[key]=dict(fact)
        # Partial, source-evidenced row coordinates. Unknown rows remain unknown;
        # secondary source rows may constrain a provisional search but do not
        # establish verified legality or completeness.
        try:
            row_facts = {int(r['spell_id']): r for r in conn.execute(
                "SELECT * FROM talent_tree_row_facts WHERE class_key=?", (class_key.lower(),)).fetchall()}
        except sqlite3.OperationalError as exc:
            raise ValueError('canonical talent tree row SQLite migration missing') from exc
        try:
            tier_row = conn.execute('SELECT * FROM talent_tree_rules WHERE class_key=?',
                                    (class_key.lower(),)).fetchone()
        except sqlite3.OperationalError as exc:
            raise ValueError('canonical talent tier rule SQLite migration missing') from exc
        tree_rule = (None if tier_row is None else {
            'points_per_row': int(tier_row['points_per_row']),
            'authority': tier_row['authority'], 'source_url': tier_row['source_url'],
            'evidence_text': tier_row['evidence_text'], 'capture_id': tier_row['capture_id'],
            'verified_current': False})
        tree_map: dict[int, str] = {}
        for row in rows:
            raw = json.loads(row['raw_listview_json'])
            specs = raw.get('talentspec') or []
            norm = normalized.get(int(row['spell_id']))
            if len(specs) == 1 and norm is not None:
                tree = str(json.loads(norm['source_record_json'])['tree_key'])
                if int(specs[0]) in tree_map and tree_map[int(specs[0])] != tree:
                    raise ValueError(f'conflicting source talent tree mapping {specs[0]}')
                tree_map[int(specs[0])] = tree

        talents: list[TalentDefinition] = []
        blockers: list[dict] = []
        action_set = set(action_families)
        source_modes = dict(mode_labels or {})
        for row in rows:
            spell_id = int(row['spell_id'])
            raw = json.loads(row['raw_listview_json'])
            specs = raw.get('talentspec') or []
            spec_id = int(specs[0]) if len(specs) == 1 else None
            tree = tree_map.get(spec_id, f'source_spec:{spec_id}')
            source = {'provider': 'wowhead', 'url': row['source_url'],
                      'entity_id': spell_id, 'batch_id': list_row['batch_id'],
                      'authority': 'canonical_sqlite_spell_index'}
            normalized_row = normalized.get(spell_id)
            row_fact = row_facts.get(spell_id)
            row_metadata = {
                'row': (None if row_fact is None else int(row_fact['tree_row'])),
                'col': (None if row_fact is None else row_fact['tree_col']),
                'tree_row_known': row_fact is not None,
                'tree_row_verified': False,  # dated announcement is not current calculator verification
                'tree_row_explicit_announcement': bool(row_fact is not None and row_fact['authority'] == 'wowhead_announcement_row'),
                'tree_row_source': (None if row_fact is None else {
                    'authority': row_fact['authority'], 'url': row_fact['source_url'],
                    'evidence_text': row_fact['evidence_text'], 'capture_id': row_fact['capture_id']}),
                'tree_position_verified': bool(row_fact is not None and row_fact['tree_col'] is not None
                                               and row_fact['authority'] == 'current_calculator_verified'),
            }
            if spell_id in rank_facts:
                facts = rank_facts[spell_id]
                cap = int(facts[0]['max_rank'])
                if (len(facts) != cap or
                        [int(f['rank']) for f in facts] != list(range(1, cap + 1)) or
                        len({int(f['trait_id']) for f in facts}) != 1 or
                        len({f['capture_id'] for f in facts}) != 1):
                    raise ValueError(f'incomplete or conflicting SQLite rank facts: {spell_id}')
                rank_defs = []
                missing_targets = set()
                missing_modes = set()
                rank_blockers = []
                for fact in facts:
                    fact_source = {'provider': 'wowhead', 'url': fact['source_url'],
                                   'trait_id': int(fact['trait_id']),
                                   'capture_id': fact['capture_id'],
                                   'tooltip_source_url': fact['tooltip_source_url'],
                                   'authority': fact['source_authority']}
                    modifiers, absent, reason = _parse_rank_tooltip(
                        str(fact['raw_tooltip']), action_families=action_set, source=fact_source,
                        mode_labels=source_modes, stat_conversions=stat_conversions,
                        effect_scopes={kind:scope for (sid,kind),scope in scope_facts.items()
                                       if sid==spell_id})
                    if (str(fact['raw_tooltip']).lstrip().lower().startswith('while in ')
                            or 'while in ' in str(fact['raw_tooltip']).lower()):
                        missing_modes.update(absent)
                    else:
                        missing_targets.update(absent)
                    if reason:
                        rank_blockers.append({'rank': int(fact['rank']), 'reason': reason})
                    rank_defs.append(TalentRankDefinition(
                        rank=int(fact['rank']), modifiers=tuple(modifiers),
                        provenance={'source': fact_source, 'raw_tooltip': fact['raw_tooltip']}))
                talent = TalentDefinition(
                    id=_slug(row['name']), name=row['name'], tree_key=tree,
                    max_rank=cap, ranks=tuple(rank_defs), provenance=(source,),
                    metadata={'class_key': class_key.lower(), 'sqlite_spell_id': spell_id,
                              'source_spec_id': spec_id, **row_metadata,
                              'rank_cap_verified': True,
                              'rank_origin': (f'primary_wowhead_trait_capture:{facts[0]["capture_id"]}'
                                              if int(facts[0]['trait_id']) > 0 else
                                              f'secondary_client_rank_capture:{facts[0]["capture_id"]}'),
                              'rank_trait_id': (int(facts[0]['trait_id']) if int(facts[0]['trait_id']) > 0 else None),
                              'rank_capture_count': len(facts),
                              'unavailable_action_targets': sorted(missing_targets),
                              'unavailable_mode_targets': sorted(missing_modes),
                              'unsupported_rank_effects': rank_blockers,
                              'effect_blocker': (None if not rank_blockers else 'unparsed_rank_effect_semantics'),
                              'source_status': ('primary_trait_rank_curve_current_build_unverified'
                                                if int(facts[0]['trait_id']) > 0 else
                                                'secondary_client_rank_curve_not_primary_verified')},
                )
            elif normalized_row is not None:
                record = TalentRecord.from_dict(json.loads(normalized_row['source_record_json']))
                base = normalize_talent_definition(record)
                talent = TalentDefinition(
                    id=base.id, name=base.name, tree_key=tree,
                    max_rank=base.max_rank, prerequisite=base.prerequisite,
                    ranks=base.ranks, provenance=base.provenance + (source,),
                    metadata={**dict(base.metadata), 'sqlite_spell_id': spell_id,
                              'source_spec_id': spec_id,
                              'rank_origin': f'pinned_snapshot_migrated_to_sqlite:{normalized_row["snapshot_id"]}',
                              **row_metadata,
                              'source_status': 'legacy_normalized_snapshot_not_reverified'},
                )
            else:
                tooltip = _rank_one_tooltip(raw)
                modifiers, absent, reason = ((), (), 'rank_one_tooltip_not_identified')
                if tooltip:
                    modifiers, absent, reason = _parse_rank_one_tooltip(
                        tooltip, action_families=action_set, source=source,
                        mode_labels=source_modes, stat_conversions=stat_conversions,
                        effect_scopes={kind:scope for (sid,kind),scope in scope_facts.items()
                                       if sid==spell_id})
                talent = TalentDefinition(
                    id=_slug(row['name']), name=row['name'], tree_key=tree,
                    max_rank=1,  # observed lower bound ONLY, not an asserted cap
                    ranks=((TalentRankDefinition(rank=1, modifiers=tuple(modifiers),
                             provenance={'source': source, 'raw_tooltip': tooltip}) ,) if tooltip else ()),
                    provenance=(source,),
                    metadata={'class_key': class_key.lower(), 'sqlite_spell_id': spell_id,
                              'source_spec_id': spec_id, **row_metadata,
                              'rank_cap_verified': False,
                              'rank_origin': 'observed_rank_one_only' if tooltip else 'unknown',
                              'unavailable_action_targets': list(absent),
                              'effect_blocker': reason,
                              'source_status': 'indexed_identity_only_or_partial_rank'},
                )
            reasons = []
            if not talent.metadata.get('tree_row_known'):
                reasons.append('tree_row_and_tier_gate_not_in_sqlite')
            elif not talent.metadata.get('tree_row_verified'):
                reasons.append('tree_row_secondary_source_provisional')
            if not talent.metadata.get('tree_position_verified'):
                reasons.append('tree_column_or_verified_position_missing')
            if not talent.metadata.get('rank_cap_verified', bool(normalized_row)):
                reasons.append('higher_rank_count_and_effects_unverified')
            if not talent.ranks or not any(r.modifiers for r in talent.ranks):
                reasons.append('no_executable_effect')
            if talent.metadata.get('effect_blocker'):
                reasons.append(str(talent.metadata['effect_blocker']))
            if talent.metadata.get('unsupported_rank_effects'):
                reasons.append('unsupported_captured_rank_effects')
            if talent.metadata.get('unavailable_action_targets'):
                reasons.append('some_source_affected_actions_missing_from_level_ir')
            if talent.metadata.get('unavailable_mode_targets'):
                reasons.append('some_source_affected_modes_missing_from_level_ir')
            if reasons:
                blockers.append({'talent_id': talent.id, 'spell_id': spell_id,
                                 'reasons': sorted(set(reasons)),
                                 'missing_action_targets': list(talent.metadata.get('unavailable_action_targets') or []),
                                 'missing_mode_targets': list(talent.metadata.get('unavailable_mode_targets') or [])})
            talents.append(talent)
        # Stable generic seed priority: executable action semantics before
        # mode-only effects whose contribution to the policy scorer may still
        # be blocked (for example incoming mitigation). The optimizer still
        # enumerates every represented executable family, independent of order.
        # No talent name, ID or class-specific selection is privileged.
        talents.sort(key=lambda t: (
            not any(r.modifiers for r in t.ranks),
            -len({m.kind for r in t.ranks for m in r.modifiers
                  if m.target_type == 'action_family'}),
            -sum(m.target_type == 'action_family' for r in t.ranks for m in r.modifiers),
            -sum(len(r.modifiers) for r in t.ranks), t.id))
        if len({t.id for t in talents}) != len(talents):
            raise ValueError('duplicate normalized talent identities in SQLite index')
        if level is not None:
            from .source_checkpoint_talent_stage import apply_staged_talent_catalogue
            talents, staged = apply_staged_talent_catalogue(conn, class_key, int(level), talents)
            if staged is not None:
                # Prior SQLite blockers are historical diagnostics for the
                # unstaged catalogue; the P2 certificate checks the staged
                # ranks and retains unmodeled L2 effects explicitly.
                blockers.append({'source_stage':staged,
                    'reasons':['SOURCE_L0_ONLY_EFFECTS_NOT_FULLY_EXECUTABLE']})
        from .source_checkpoint_talent_positions import apply_staged_talent_positions
        talents, position_stage = apply_staged_talent_positions(conn, class_key, int(level or 0), talents)
        if position_stage is not None:
            blockers.append({'source_position_stage': position_stage,
                'reasons': ['SOURCE_RANK_EFFECTS_UNSTAGED_NOT_ZERO']})
        return SQLiteTalentInventory(
            talents=tuple(talents), blockers=tuple(blockers),
            captured_count=len(rows), expected_count=list_row['expected_count'],
            batch_id=str(list_row['batch_id']), source_db=db.name, tree_rule=tree_rule,
        )
    finally:
        conn.close()
