"""Emit reproducible, source-ranked 9-class IR-coverage evidence.

Index candidates are not automatically trained/legal actions.  All missing
rank/effect rows remain visible with their SQL source IDs and provenance.
"""
from __future__ import annotations
import json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice, registered_class_keys
from src.v2.source_action_coverage import audit_source_action_coverage
from src.v2.source_button_discovery import discover_source_combat_buttons


def main():
    entries=[]
    for cls in registered_class_keys():
        for lvl in (10,20):
            ir=build_game_ir_slice(class_key=cls,level=lvl)
            if ir is None:
                entries.append({'class_key':cls,'level':lvl,'status':'IR_NOT_AVAILABLE'})
                continue
            ledger=ir.provenance['indexed_ability_coverage']
            audit=audit_source_action_coverage(ir,level=lvl)
            buttons=discover_source_combat_buttons(ir,level=lvl)
            indexed=next(x for x in ir.source_facts if x.get('fact_kind')=='canonical_indexed_ability_coverage')
            entries.append({**ledger,'executable_ir_actions':len(ir.actions),
                'discoverable_initial_mode_buttons':len(buttons['action_ids']),
                'ir_action_blockers':audit['ir_action_blocker_count'],
                'unrepresented_source_ranks':audit['source_indexed_unrepresented_rank_count'],
                'source_rank_blockers':audit['source_indexed_rank_blockers'],
                'source_acquisition_proven':False,
                'complete_gear_talent_rotation_optimization':False})
    druid27=build_game_ir_slice(class_key='druid',level=27)
    row=next(r for f in druid27.source_facts if f.get('fact_kind')=='canonical_indexed_ability_coverage' for r in f['records'] if r['spell_id']==1822)
    report={'scope':'index-vs-IR, not final trained or legal skill completeness',
            'classes':entries,'druid_27_rake':row,
            'source_database':'data/forever/catalogue/forever_abilities.sqlite',
            'ruleset':'WoW Forever; source listview 2026-10-08, independently qualified',
            'schema_version':druid27.schema_version,
            'acceptance':{'class_level_product_done':0,'total_class_level_targets':540,
                          'global_optimum_claimed':False}}
    out=Path(__file__).resolve().parents[1]/'WF270_INDEXED_ACTION_COVERAGE.json'
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print('Saved',out)
    print('Class L20 | indexed at/below | exact rank action | unrepresented')
    for x in entries:
        if x.get('scenario_level')==20:
            print(f"{x['class_key']:9s} {x['at_or_unknown_below_level_count']:5d} {x['exact_source_rank_in_ir_count']:5d} {x['unrepresented_rank_count']:5d}")
    print('Rake L27 indexed',row['status'],row['matched_action_ids'])


if __name__=='__main__':
    main()
