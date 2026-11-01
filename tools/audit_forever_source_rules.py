#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rulesets.forever.data.catalogue import ForeverSourceCatalogue
from src.rulesets.forever.data.rules import default_rules


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--json-out', type=Path)
    args=ap.parse_args()
    r=default_rules()
    checks={
        'mage.piercing_ice.r3': r.talent_value('mage','piercing_ice',3,'school_damage_pct',target='frost_spells',school='frost'),
        'mage.arcane_blast.l40.sp_coeff': r.spell_value('mage','arcane_blast',40,'spell_power_coefficient',target='arcane_blast'),
        'paladin.divine_strength.r5': r.talent_value('paladin','divine_strength',5,'stat_pct',target='strength'),
        'paladin.toughness.r5': r.talent_value('paladin','toughness',5,'item_armor_pct',target='item_armor'),
        'paladin.anticipation.r5.defense': r.talent_value('paladin','anticipation',5,'skill_bonus',target='defense'),
        'paladin.seal_of_command.l20.judgement_base': r.spell_value('paladin','seal_of_command',20,'judgement_base_damage',target='judgement'),
        'paladin.seal_of_command.l20.stunned_mult': r.spell_value('paladin','seal_of_command',20,'target_state_damage_multiplier',target='judgement'),
        'paladin.seal_of_command.l60.judgement_base': r.spell_value('paladin','seal_of_command',60,'judgement_base_damage',target='judgement'),
        'paladin.holy_light.heal_sp_coeff': r.spell_family_value('paladin','holy_light','spell_power_coefficient',target='heal',school='holy'),
        'paladin.flash_of_light.heal_sp_coeff': r.spell_family_value('paladin','flash_of_light','spell_power_coefficient',target='heal',school='holy'),
        'paladin.holy_strike.sp_coeff': r.spell_family_value('paladin','holy_strike','spell_power_coefficient',target='holy_damage',school='holy'),
        'paladin.consecration.first4_tick_sp_coeff': r.spell_family_value('paladin','consecration','spell_power_coefficient',target='first4_tick',school='holy'),
        'paladin.sor.proc_sp_coeff': r.spell_family_value('paladin','seal_of_righteousness','spell_power_coefficient',target='seal_proc',school='holy'),
        'paladin.sor.judgement_sp_coeff': r.spell_family_value('paladin','seal_of_righteousness','spell_power_coefficient',target='judgement',school='holy'),
        'paladin.fury.proc_sp_coeff': r.spell_family_value('paladin','seal_of_fury','spell_power_coefficient',target='seal_proc',school='holy'),
        'paladin.fury.judgement_sp_coeff': r.spell_family_value('paladin','seal_of_fury','spell_power_coefficient',target='judgement',school='holy'),
        'paladin.fury.absorb_fraction': r.spell_family_value('paladin','seal_of_fury','damage_absorb_fraction',target='shield'),
        'druid.improved_wrath.r5.cast_delta_s': r.talent_value('druid','improved_wrath',5,'cast_time_delta_s',target='wrath'),
        'druid.improved_wrath.r5.cost_pct': r.talent_value('druid','improved_wrath',5,'resource_cost_pct',target='wrath'),
    }
    expected={
        'mage.piercing_ice.r3':0.06,
        'mage.arcane_blast.l40.sp_coeff':0.714,
        'paladin.divine_strength.r5':0.10,
        'paladin.toughness.r5':0.10,
        'paladin.anticipation.r5.defense':20.0,
        'paladin.seal_of_command.l20.judgement_base':71.0,
        'paladin.seal_of_command.l20.stunned_mult':2.0,
        'paladin.seal_of_command.l60.judgement_base':202.5,
        'paladin.holy_light.heal_sp_coeff':0.714,
        'paladin.flash_of_light.heal_sp_coeff':0.429,
        'paladin.holy_strike.sp_coeff':0.429,
        'paladin.consecration.first4_tick_sp_coeff':0.095,
        'paladin.sor.proc_sp_coeff':0.10,
        'paladin.sor.judgement_sp_coeff':0.50,
        'paladin.fury.proc_sp_coeff':0.10,
        'paladin.fury.judgement_sp_coeff':0.45,
        'paladin.fury.absorb_fraction':0.50,
        'druid.improved_wrath.r5.cast_delta_s':-0.5,
        'druid.improved_wrath.r5.cost_pct':-0.5,
    }
    issues=[k for k,v in checks.items() if abs(v-expected[k])>1e-12]

    # Assert migrated class code no longer owns the numeric source truths.
    source_text={
        'mage.engine': (ROOT/'src/rulesets/forever/classes/mage/engine.py').read_text(),
        'paladin.mechanics': (ROOT/'src/rulesets/forever/classes/paladin/mechanics.py').read_text(),
        'druid.mechanics': (ROOT/'src/rulesets/forever/classes/druid/mechanics.py').read_text(),
    }
    forbidden={
        'paladin.mechanics':['.02*t.divine_strength','.02 * t.divine_strength','.02*t.toughness','.02 * t.toughness', '_SOC_PROC_SP_COEFF', '_SOC_JUDGEMENT_SP_COEFF', '4.0*t.anticipation', '4.0 * t.anticipation', '_HEALING_COEFF', '_HOLY_STRIKE_SP_COEFF', '_CONSECRATION_FIRST4_TOTAL_SP_COEFF', '_SOR_ONHIT_SP_COEFF', '_SOR_JUDGEMENT_SP_COEFF', '_FURY_ONHIT_SP_COEFF', '_FURY_JUDGEMENT_SP_COEFF'],
        'druid.mechanics':['0.1*t.improved_wrath','.1*t.improved_wrath','.10*t.improved_wrath'],
    }
    duplicates=[]
    for mod, needles in forbidden.items():
        for needle in needles:
            if needle in source_text[mod]:
                duplicates.append(f'{mod}:{needle}')

    cat=ForeverSourceCatalogue()
    report={
        'ok': not issues and not duplicates,
        'snapshot_id':cat.snapshot_id,
        'normalized_fingerprint':cat.manifest.get('normalized_fingerprint'),
        'checks':checks,
        'issues':issues,
        'duplicate_class_local_source_numbers':duplicates,
    }
    if args.json_out:
        args.json_out.parent.mkdir(parents=True,exist_ok=True)
        args.json_out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0 if report['ok'] else 2

if __name__=='__main__':
    raise SystemExit(main())
