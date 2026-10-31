"""Reproducible same-scorer weapon replacement evidence; not a complete optimum."""
from __future__ import annotations
import json
from pathlib import Path

from src.version import SOFTWARE_VERSION
from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.gear import select_named_gear
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.source_mode_search import evaluate_discovered_mode_search
from src.v2.source_policy_search import evaluate_discovered_policy_search


def run():
    source = build_source_slice(20)
    builds = {'held_out_feral': {'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1},
              'wrath5': {'improved_wrath':5}}
    for allocation in builds.values():
        validate_talent_selection(source, allocation, level=20)
    records = []
    for axis in ('weapon_dps','strength','spell_power'):
        selection = select_named_gear(class_key='druid',level=20,role='druid_feral',stat_weights={axis:1.0})
        # .231-like path is for controlled *mechanical* comparison only: its
        # weapon anchor remains baked, while other gear stats still execute.
        old, old_report = apply_gear_selection(source, aggregate_stats={k:v for k,v in selection.aggregate_stats.items() if k!='weapon_dps'})
        equipped, report = apply_gear_selection(source, aggregate_stats=selection.aggregate_stats,
                                                selected_items=tuple(selection.slots.values()))
        scores = {}
        for name,allocation in builds.items():
            scores[name] = {}
            for label, ir in (('old_baked_weapon_anchor',old),('equipped_weapon_source',equipped)):
                talented, _ = apply_talent_selection(ir, allocation, level=20)
                mode = evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=talented,
                                                       max_policies_per_path=24)
                caster = evaluate_discovered_policy_search(class_key='druid',level=20,
                                                            ir_slice=ir,talent_selection=allocation,max_policies=24)
                mode_s = float(mode['winner']['seconds_per_mob'])
                caster_s = float(caster['winner']['seconds_per_mob'])
                scores[name][label] = {
                    'mode_s_per_mob':mode_s, 'caster_s_per_mob':caster_s,
                    'best_s_per_mob':min(mode_s,caster_s),
                    'mode_auto_attack_damage':mode['winner']['auto_attack_damage'],
                    'best_branch':'mode' if mode_s < caster_s else 'caster',
                }
        records.append({'gear_weight':axis,
                        'weapon': {'name':selection.slots['weapon']['name'],
                                   'item_id':selection.slots['weapon']['item_id'],
                                   'dps':selection.aggregate_stats['weapon_dps']},
                        'gear_ids':{k:v['item_id'] for k,v in selection.slots.items()},
                        'applied_weapon_dps':report.applied_stats['weapon_dps'],
                        'previously_unsupported_weapon_dps':selection.aggregate_stats['weapon_dps'],
                        'scores':scores})
    return {'version':SOFTWARE_VERSION,'increment':'WF-COMBAT232',
            'status':'EVALUATED_BOUNDED_HELD_OUT_MECHANICAL_COMPARISON',
            'source':'https://worldofwarcraft.blizzard.com/en-us/news/24301515/',
            'class_key':'druid','level':20,
            'policy_cap_per_mode_path':24,'policy_cap_caster':24,
            'incoming_scheduled':False,'full_joint_search':False,
            'blockers':['base Armor not sourced; incoming schedule remains opt-in',
                        'Bear armor multiplier not sourced/executable',
                        'all talent ranks/legality not source-complete',
                        'weapon enchants/procs not modeled',
                        'bounded three gear sets and two held-out talents only',
                        'historical reference objective not proven identical',
                        'no all-slot unrestricted gear/talent/policy optimization'],
            'gear_comparisons':records}


if __name__=='__main__':
    out=Path(f'WF_COMBAT232_EQUIPPED_WEAPON_EVIDENCE_v{SOFTWARE_VERSION}.json')
    out.write_text(json.dumps(run(),indent=2,sort_keys=True)+'\n')
    print(out)
