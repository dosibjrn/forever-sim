"""Source-text-bound L0 *conditional* utility estimates for checkpoint actions.

Deliberately NOT executable game mechanics or an L2 rank/acquisition proof.
Patterns describe generic effects seen verbatim in canonical source text.  No
spell ID, class name or spell name selects an effect; missing text remains
missing, and unverified ranks are never promoted to paid CombatRuntime actions.
"""
from __future__ import annotations

import re

_NUMBER = r'(\d+(?:\.\d+)?)'


def source_context_evidence(text: str, *, target_hp: float) -> dict:
    """Class-neutral, uncertainty-preserving, 100-target heuristic feature set."""
    text = ' '.join((text or '').replace('\xa0', ' ').split())
    typed = []
    context = set()
    quantities = {}
    uncertainty = []

    def add(kind, numbers, *, required=()):
        typed.append({'kind': kind, 'source_numbers': numbers,
                      'conditional_on': list(required)})
        context.update(required)

    # The old generic direct-damage atom recognizer matches '4 Nature
    # damage' inside *retaliatory* buffs, falsely making it a direct nuke.
    m = re.search(r'\b(?:causing|dealing)\s+' + _NUMBER +
                  r'\s+\w+\s+damage\s+to\s+attackers\s+when\s+hit\b', text, re.I)
    if m:
        v = float(m.group(1))
        quantities['reactive_damage_per_incoming_hit'] = v
        add('retaliatory_damage', {'damage_per_attacker_hit': v},
            required=('self_or_buff_target_is_hit', 'buff_active'))
        quantities['reactive_damage_fraction_target_hp_per_hit'] = round(v / max(1., target_hp), 6)

    m = re.search(r'\b(?:heals|restores)\s+(?:the\s+\w+\s+)?(?:target\s+)?for\s+' +
                  _NUMBER + r'\s+over\s+' + _NUMBER + r'\s+sec\b', text, re.I)
    if m:
        v, seconds = map(float, m.groups())
        quantities['periodic_heal_total'] = v
        quantities['periodic_heal_duration_s'] = seconds
        add('periodic_healing', {'total_healing': v, 'duration_s': seconds},
            required=('target_damaged', 'healing_timing_and_overheal'))

    m = re.search(r'\bdecreas(?:e|es|ing)\s+(?:nearby\s+)?enemies[\'’]?\s+melee\s+attack\s+power\s+by\s+' +
                  _NUMBER, text, re.I)
    if m:
        v = float(m.group(1))
        quantities['enemy_melee_attack_power_reduction'] = v
        add('attack_power_debuff', {'enemy_melee_attack_power_reduction': v},
            required=('enemy_melee_damage', 'debuff_uptime'))

    m = re.search(r'\bincreas(?:e|es|ing)\s+(?:the\s+)?(?:friendly\s+target[\'’]s|target[\'’]s|your)\s+armor\s+by\s+' +
                  _NUMBER, text, re.I)
    if m:
        v = float(m.group(1))
        quantities['friendly_armor_bonus'] = v
        add('friendly_armor_buff', {'armor': v}, required=('incoming_physical_damage', 'buff_uptime'))
    m = re.search(r'\ball\s+attributes\s+by\s+' + _NUMBER, text, re.I)
    if m:
        v = float(m.group(1))
        quantities['all_attributes_bonus'] = v
        add('all_attributes_buff', {'each_attribute_bonus': v},
            required=('actor_attributes', 'buff_uptime'))

    m = re.search(r'\b(?:grants?\s+you|increases\s+your(?:\s+maximum)?)\s+' +
                  _NUMBER + r'%\s+of\s+your\s+maximum\s+health\b', text, re.I)
    if m:
        v = float(m.group(1))
        quantities['temporary_max_health_percent'] = v
        add('temporary_survival_health', {'maximum_health_percent': v},
            required=('damage_timing', 'temporary_health_expiration'))

    if re.search(r'\bnext\s+\d+\s+melee\s+attack\b.*\b(?:afflict|root|stun)\b', text, re.I):
        add('attacker_triggered_control', {},
            required=('incoming_melee_attack', 'target_control_susceptibility'))
    if re.search(r'\b(?:chance\s+to\s+grant|chance\s+of\s+causing)\b.*\b(?:clearcasting|free\s+cast)\b', text, re.I):
        add('proc_resource_saving', {}, required=('proc_rate_unknown', 'subsequent_resource_cost'))
        uncertainty.append('SOURCE_DOES_NOT_QUANTIFY_PROC_CHANCE')
    if re.search(r'\b(?:instantly\s+grants?\s+you|regenerate(?:s|d)?\s+\d+\s+\w+\s+every\s+time)\b',text,re.I):
        add('conditional_resource_sustain', {},
            required=('resource_state', 'trigger_and_amount_if_unspecified'))
    if re.search(r'\b(?:swim\s+speed|breathe\s+underwater)\b',text,re.I):
        add('aquatic_movement', {},required=('underwater_or_aquatic_scenario',))
    if re.search(r'\b(?:resurrects?|brings?\s+a\s+dead\s+\w+\s+back\s+to\s+life)\b',text,re.I):
        add('resurrection', {},required=('dead_friendly_target',))
    if re.search(r'\bcannot\s+be\s+cast\s+(?:(?:while|when)\s+)?in\s+combat\b',text,re.I):
        add('noncombat_only', {},required=('out_of_combat',))
    if re.search(r'\btaunts?\s+the\s+target\b', text,re.I):
        add('threat_target_control', {},required=('multiple_threat_targets_or_target_not_attacking_actor',))
    if re.search(r'\b(?:increases|decreases)\s+all\s+non-physical\s+healing\b',text,re.I):
        add('healing_multiplier', {},required=('nonphysical_heals_cast',))

    # Additional *qualitative* web-indexed source roles. A label describes
    # potential context value, never a fabricated numeric DPS or free cast.
    if re.search(r'\b(?:forces?\s+.*?to\s+sleep|asleep|hibernat(?:e|es|ing))\b',text,re.I):
        add('conditional_sleep_control', {},required=('target_is_beast_or_dragonkin','sleep_breaks_on_damage'))
    if re.search(r'\b(?:prowl|stealth(?:ed)?|sneak)\b',text,re.I):
        add('precombat_stealth', {},required=('out_of_combat','stealth_detection','movement_speed'))
    if re.search(r'\b(?:cures?\s+\d+\s+poison|remove(?:s)?\s+.*?poison|dispel\s*\(?poison)\b',text,re.I):
        add('poison_dispel', {},required=('target_has_poison','poison_damage_or_debuff'))
    if re.search(r'\b(?:charge(?:s|d)?\s+(?:an?\s+)?enemy|leaps?\s+(?:to|behind)\s+(?:an?\s+)?enemy)\b',text,re.I):
        add('distance_closing', {},required=('target_out_of_melee','range_and_path_geometry'))
    if re.search(r'\b(?:interrupt(?:s|ing)?\s+(?:any\s+)?spells?(?:casting)?|interrupt\s+cast|preventing\s+.*?spell)\b',text,re.I):
        add('spell_interrupt', {},required=('enemy_is_casting','school_lockout_duration'))
    if re.search(r'\b(?:immobiliz(?:e|es|ing)|root(?:s|ed)?\s+(?:an?\s+)?enemy)\b',text,re.I):
        add('movement_root', {},required=('enemy_movement_matters','root_break_conditions'))
    if re.search(r'\b(?:teleport(?:s|ed)?\s+(?:the\s+caster\s+)?to|transport\s+(?:yourself|the\s+caster)\s+to)\b',text,re.I):
        add('out_of_combat_teleport', {},required=('world_travel_context',))
    if re.search(r'\b(?:returns?\s+the\s+spirit\b.*?\bto\s+the\s+body|restor(?:e|es)\s+(?:a\s+)?dead\s+target\s+to\s+life)\b',text,re.I):
        add('resurrection', {},required=('dead_friendly_target',))
    if re.search(r'\b(?:heals?\s+(?:a\s+)?(?:friendly\s+)?target|heals?\s+all\s+party|heals?\s+.*?over\s+\d+\s+sec|healing\s+over\s+time)\b',text,re.I):
        add('healing_potential', {},required=('actor_or_ally_damaged','overheal_and_timing'))
    if re.search(r'\b(?:burns?\s+the\s+enemy|(?:deals?|causes?|inflicts?)\s+.*?damage|damage\s+over\s+\d+\s+sec|weapon\s+damage)\b',text,re.I):
        add('damage_potential', {},required=('enemy_defenses','spell_hit_and_crit','cast_or_proc_availability'))
    if re.search(r'\b(?:generat(?:e|es|ing)\s+\d+\s+combo\s+point|awards?\s+\d+\s+combo\s+point)\b',text,re.I):
        add('combo_generation', {},required=('cat_form','target_combo_point_state'))
    if re.search(r'\b(?:next\s+.*?cast\s+by\s+\d+%|increases?\s+(?:the\s+)?damage\s+done\s+by\s+your\s+next)\b',text,re.I):
        add('next_cast_amplifier', {},required=('following_cast','buff_uptime'))
    if re.search(r'\b(?:when\s+you\s+critically\s+heal|next\s+time\s+the\s+target\s+takes\s+damage)\b',text,re.I):
        add('conditional_heal_proc', {},required=('critical_heal_occurs','future_damage_event'))
    if re.search(r'\b(?:periodically\s+trigger\s+spell|summon\s+a\s+flurry\s+of\s+stars|maximum\s+\d+\s+stars)\b',text,re.I):
        add('periodic_multi_target_proc', {},required=('proc_frequency','targets_in_range','source_acquisition'))
    if re.search(r'\b(?:can\s+now\s+be\s+active\s+on\s+targets\s+affected\s+by\s+another|overrides?\s+actionbar\s+spell)\b',text,re.I):
        add('conditional_spell_modifier', {},required=('grant_or_override_active','affected_spell_cast'))
    if re.search(r'\b(?:not\s+an\s+action|passive\s+spell|hidden\s+until\s+overridden)\b',text,re.I):
        add('non_independent_action_flag', {},required=('granting_source','not_free_spellbook_action'))
    return {'effect_candidates': typed, 'numeric_context_features': quantities,
            'context_requirements': sorted(context), 'unknown_parameters': uncertainty,
            'source_text_available': bool(text),
            'proxy_is_gameplay_execution_or_legality_proof': False}
