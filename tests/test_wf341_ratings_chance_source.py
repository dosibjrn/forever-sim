"""WF341: source-bound damage probability sensitivity; rating analogue is NOT proven."""
import json
from pathlib import Path
from dataclasses import dataclass
from types import SimpleNamespace
import pytest
from src.game.data.forever.source_checkpoint_p3_chance import (
    chance_perturbed_ir,
    context_weapon_speed_semantics)
from src.game.data.forever.source_checkpoint_p3_weights import verify_weighted_ranking
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'evidence/wf341/WF341_DRUID_L20_CHANCE_SENSITIVITY_TOP5.json'
NEW_REPORT=ROOT/'evidence/wf346/WF346_TOP5.json'
STAGE=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']

def test_rating_analogue_is_not_a_confirmed_forever_weight():
    report=json.loads(REPORT.read_text())
    for key in ('hit','crit','dodge','defense'):
        row=report['stat_weights']['weights'][key]
        assert row['weight_s_saved_per_mob_per_unit'] is None
        assert 'HISTORICAL_TBC_ANALOGUE_NOT_FOREVER_AUTHORITY' in row['reason']
        assert 'wowpedia' in row['historical_source_url']
    assert report['p3_pass'] is True and report['full_numeric_effect_certainty'] is False

def test_all_three_chance_sensitivities_measured_on_100_mobs():
    report=json.loads(REPORT.read_text())
    for key in ('hit','crit','dodge'):
        sensitivity=report['stat_weights']['chance_sensitivities'][key]
        assert sensitivity['status']=='MEASURED_EXECUTOR_CHANCE_SENSITIVITY'
        assert sensitivity['mobs']==100
        assert sensitivity['weight_s_saved_per_mob_per_chance_fraction']>0
        assert any('events' in x for x in sensitivity['full_probes'])
    hit=report['stat_weights']['chance_sensitivities']['hit']
    assert abs(hit['effective_chance_delta_after_cap']-.05)<1e-9
    assert hit['delta_chance_fraction']>.05

def test_melee_hit_probe_perturbs_target_profile_not_already_100pct_attack():
    @dataclass(frozen=True)
    class FakeIR:
        provenance: dict
    ir=FakeIR(provenance={'target_combat_profile':{'melee_hit':.95,'spell_hit':.96}})
    altered=chance_perturbed_ir(ir,'hit',.08)
    assert abs(altered.provenance['target_combat_profile']['melee_hit']-1.)<1e-12
    assert altered.provenance['target_combat_profile']['spell_hit']==.96
    assert ir.provenance['target_combat_profile']['melee_hit']==.95
    assert altered.provenance['synthetic_hit_chance_sensitivity_delta']==.08

def test_probabilities_cannot_be_outside_closed_perturbation_limits():
    fake=SimpleNamespace(provenance={'target_combat_profile':{'melee_hit':.95}})
    for bad in (0.,-.01,.21,float('nan'),float('inf')):
        with pytest.raises(ValueError):chance_perturbed_ir(fake,'hit',bad)

def test_current_source_item_conversion_is_level_independent():
    from src.game.data.forever.source_checkpoint_p3_ratings import forever_display_chance_fraction_per_raw_point
    assert forever_display_chance_fraction_per_raw_point('crit',20) == forever_display_chance_fraction_per_raw_point('crit',60)
    assert forever_display_chance_fraction_per_raw_point('hit',20) == .001
    assert forever_display_chance_fraction_per_raw_point('defense',20) is None


def test_fixed_form_speed_is_mechanically_justified_zero():
    report=json.loads(REPORT.read_text())
    row=report['stat_weights']['weights']['weapon_speed']
    assert row['weight_s_saved_per_mob_per_unit']==0
    assert row['status']=='CONTEXTUAL_ZERO_FROM_SOURCE_FORM_FIXED'
    assert report['stat_weights']['weapon_speed_source_status']=='FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY'

def test_ratings_stay_uncertain_and_provisional_score_audited():
    report=json.loads(REPORT.read_text())
    assert report['unknown_item_count']>0
    for slot,entry in report['slots'].items():
        assert len(entry['historical_rating_sensitivity_top_ids'])==min(5,entry['available_legal'])
        for x in entry['top']:
            assert 'provisional_rating_adjusted_score' in x
            assert len(x['provisional_rating_contributions'])>=0
            assert abs(sum(c['contribution_s_saved_per_mob'] for c in x['contributions'])-
                       x['known_score_s_saved_per_mob'])<1e-9
    assert report['slots']['hands']['available_legal']>=5

def test_no_source_catalogue_or_build_identifier_drift():
    report=json.loads(NEW_REPORT.read_text())
    assert report['total_legal_items']==1171
    verify_weighted_ranking(report,class_key='druid',level=20,stage=STAGE)
    assert abs(report['stat_weights']['base_s_per_mob']-13.46412880141965)<1e-9

def test_provisional_rating_report_still_powers_exact_paid_shortlist():
    from src.v2.source_persistent_slot_search import _source_slot_proposals
    r=json.loads(NEW_REPORT.read_text())
    base=STAGE['gear_policy_result']['winner']['gear']
    proposals,counts=_source_slot_proposals(class_key='druid',level=20,
        base=base,weighted_p3_report=r,seed_stage=STAGE,per_slot=2,max_proposals=45)
    assert len(proposals)>0 and counts['weapon']>0
    for slot,item in proposals:
        assert item.item_id in r['slots'][slot]['all_ranked_item_ids']
