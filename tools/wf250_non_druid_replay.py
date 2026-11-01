"""Mage L20 independent source search and separately frozen historical challenger.

Historical I15's gear is an unnamed analytical fixture, so an exact old build
cannot be evaluated on canonical named gear. The old talent allocation and
FBo-only policy are executed as a *controlled translated* candidate, explicitly
NOT advertised as an apples-to-apples complete old winner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.model.ir import PolicyDefinition, PolicyRuleDefinition
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.shared.leveling.objective import representative_hp
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_legal_beam import search_source_legal_beam
from src.v2.source_multi_pull_joint import _score_state

LEGACY = Path(__file__).resolve().parents[1] / 'docs/validation/I15/LISTENER_LOCAL_I15_STATE_v0.11.48.103.json'


def run():
    legacy=json.loads(LEGACY.read_text())['endpoint_paths']['mage']['targets']['20']['routes']['frost']['path']
    if legacy['policy'] != 'FBo' or legacy['gear'] != 'bounded_i15_validation_fixture':
        raise ValueError('historical challenger fixture unexpectedly changed')
    old_allocation={('improved_'+k[4:] if k.startswith('imp_') else k):int(v)
                    for k,v in legacy['talent_ranks'].items()}
    source=build_game_ir_slice(class_key='mage',level=20)
    validate_talent_selection(source,old_allocation,level=20)
    # Historical winner is never passed to independent search or its scorer.
    independent=search_source_legal_beam(class_key='mage',level=20,
        max_allocations=110,screening_gear_count=2,finalists=6,
        policy_cap=16,beam_width=3)
    winner=independent['independent_winner']
    gears=_gear_envelope('mage',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=source)
    gear=next(g for g in gears if g['id']==winner['gear_id'])
    old_search=_score_state(source,level=20,gear=gear,allocation=old_allocation,
        pulls=3,policy_cap=16,target_health=representative_hp(20))
    selection=gear['selection']
    geared,_=apply_gear_selection(source,aggregate_stats=selection.aggregate_stats,
        selected_items=tuple(selection.slots.values()),source='canonical_sqlite_forever_catalogue')
    old_ir,_=apply_talent_selection(geared,old_allocation,level=20)
    # FBo is the legacy Frostbolt-only policy label. This is an explicit
    # translation, not a claim of matching old travel/regen/wand behavior.
    frostbolt=next(a for a in old_ir.actions if a.family_key=='frostbolt')
    frozen_policy=PolicyDefinition(id='historical_i15_FBo_translated',
        label='Historical FBo (Frostbolt only, translated)',
        rules=(PolicyRuleDefinition('fbo',frostbolt.id),),
        provenance={'source':'I15_LEGACY_MAGE_L20','comparison':'not_exact_old_sim'})
    old_frozen=evaluate_repeated_pulls(ir_slice=old_ir,policy=frozen_policy,level=20,
        target_health=representative_hp(20),count=3,
        schedule_incoming_attacks=True,apply_target_defense=True)
    return {
        'version':'0.11.48.250','status':'EVALUATED_BOUNDED',
        'independent_search':independent,
        'legacy_reference':{'source':str(LEGACY.relative_to(LEGACY.parents[2])),
            'original_allocation':legacy['allocation'],'old_s_per_mob':legacy['seconds_per_mob'],
            'original_policy':legacy['policy'],'original_gear':legacy['gear'],
            'objective':legacy['timing_contract']},
        'historical_allocation_real_candidate':{
            'allocation':old_allocation,'gear_id':winner['gear_id'],
            'new_engine_best_policy_s_per_mob':old_search['seconds_per_mob'],
            'new_engine_best_policy':old_search['best_policy']['policy'] if old_search['best_policy'] else None,
            'new_engine_frozen_FBo_s_per_mob':old_frozen.seconds_per_mob,
            'frozen_FBo_executed':True,
            'new_engine_frozen_FBo_pulls':list(old_frozen.pulls)},
        'old_full_build_comparison_valid':False,
        'why_not_exact':['I15 historical gear is unnamed bounded analytical fixture, not a canonical item-by-item selection.',
            'Historical FBo travel/recovery and spell mechanics differ from new three-pull incoming-inclusive scorer.',
            'Current Mage provider still uses a qualified mana/HP/wand proxy and omits many legal actions/talent effects.',
            'Source spell ranks and Frostbolt L20 live tooltip changed since historical I15 snapshot.'],
        'new_search_is_global_optimum':False,
    }


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='WF250_NON_DRUID_JOINT_REPLAY.json');a=parser.parse_args()
    r=run();Path(a.output).write_text(json.dumps(r,indent=2))
    print(json.dumps({'winner_s_per_mob':r['independent_search']['independent_winner']['seconds_per_mob'],
        'winner_talents':r['independent_search']['independent_winner']['talent_allocation'],
        'historical_translated_FBo':r['historical_allocation_real_candidate']['new_engine_frozen_FBo_s_per_mob'],
        'historical_same_gear_reoptimized_policy':r['historical_allocation_real_candidate']['new_engine_best_policy_s_per_mob'],
        'full_old_comparison_valid':r['old_full_build_comparison_valid']},indent=2))
