import json
from pathlib import Path
import re
import subprocess

import pytest

from src import listener
from src.v2.decision_dashboard import _talent_trees
from src.v2.icon_provenance import decorate_gear_stats, item_icon


def test_item_identity_rejects_wrong_id_and_stale_decorations():
    assert item_icon('Searing Dagger', source_url='https://www.wowhead.com/forever/item=14151/searing-dagger') is None
    assert item_icon('Searing Dagger', source_url='https://www.wowhead.com/forever/item=273003/searing-dagger')['entity_id'] == 273003
    row = decorate_gear_stats({'slots': {'weapon': {'name': 'Searing Dagger', 'source_url': 'https://www.wowhead.com/forever/item=14151', 'icon': {'entity_id':14151}}}})['slots']['weapon']
    assert 'icon' not in row and row['identity_status'] == 'unverified'


@pytest.mark.parametrize('cls,key,tree', [('mage','imp_frostbolt','frost'),('druid','ferocity','feral'),('paladin','deflection','retribution')])
def test_tree_totals_derive_from_ranks_when_matrix_omits_points(cls,key,tree):
    assert _talent_trees(cls, {'talent_ranks': {key:5}})[tree]['points'] == 5


def test_druid_weights_are_scored_and_probe_state_is_restored():
    from src.rulesets.forever.classes.druid import engine
    from src.rulesets.forever.classes.druid.mechanics import _GEAR_PROBE
    talents = engine.Talents(ferocity=5)
    before = engine.experimental_level_score(20, talents, 'feral')
    weights = engine.marginal_stat_weights(20, talents, 'feral', before)
    assert weights['analytical'] is False
    assert weights['stats']['strength']['seconds_saved_per_100_per_point'] > 0
    assert _GEAR_PROBE.get() is None
    assert engine.experimental_level_score(20, talents, 'feral') == before


def test_listener_js_cross_class_level_switch_and_reference_math(tmp_path):
    # Execute the shipped JavaScript with a minimal DOM sink. This verifies the
    # renderer and change handlers, not CSS layout or a real browser runtime.
    script = re.findall(r'<script>(.*?)</script>', listener.DECISIONS_HTML, re.S)[-1]
    script = script[:script.index('load().catch')]
    harness = r'''
const assert=require('assert');
const elements=new Map();
const document={getElementById(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',addEventListener(k,fn){this[k]=fn},querySelectorAll(){return []}});return elements.get(id)},querySelectorAll(){return []}};
const localStorage={getItem(){return null},setItem(){}};
const window={};const setTimeout=()=>0,clearTimeout=()=>{};
'''
    checks = r'''
const fallback={stat_weights:{reference_stat:'spell_power',stats:{spell_power:{seconds_saved_per_100_per_point:0,normalized_to_reference:null},strength:{seconds_saved_per_100_per_point:2,normalized_to_reference:null},agility:{seconds_saved_per_100_per_point:1,normalized_to_reference:null}}}};
assert.equal(statWeightModel(fallback).reference,'strength');
assert.equal(itemEquivalentScore({strength:3,agility:4},fallback).value,5);
const zero={stat_weights:{stats:{spell_power:{seconds_saved_per_100_per_point:0,normalized_to_reference:null}}}};
assert.equal(statWeightModel(zero).kind,'raw');assert.equal(itemEquivalentScore({spell_power:10},zero),null);
const sp={stat_weights:{stats:{spell_power:{seconds_saved_per_100_per_point:2}}}};
assert.equal(itemEquivalentScore({spell_power:0,spell_damage:7},sp).value,7);
const names={mage:['arcane','fire','frost'],paladin:['holy','protection','retribution'],druid:['balance','feral','restoration']};
for(const [cls,trees] of Object.entries(names)){
 const rows=[19,20,40,60].map(level=>({level,allocation:'',talent_trees:Object.fromEntries(trees.map(t=>[t,{points:0,talents:[]}])),gear_stats:{slots:{weapon:{name:'Test weapon',strength:level}}},stat_weights:fallback.stat_weights}));
 data={endpoint_paths:{[cls]:{targets:{60:{status:'available',routes:{unconstrained:{status:'available',path:{steps:rows}}}}}}},route_rows:{[cls]:{60:{routes:{unconstrained:{rows}}}}}};
 state={cls,target:'60',route:'unconstrained',level:20};bind();
 for(const level of [20,19,20,40,60]){
  $('levelPick').change({target:{value:String(level)}});
  const html=$('focusBoard').innerHTML;
  assert.equal((html.match(/class="talent-tree /g)||[]).length,3);
  for(const tree of trees)assert(html.includes(prettyTalent(tree)+' (0)'));
  assert(html.includes('Str-eq'));assert($('focusTitle').textContent.includes('Level '+level));
  if(cls!=='paladin')assert(!html.includes('Protection ('));
 }
}
console.log('cross-class JS contract passed');
'''
    path=tmp_path/'contract.cjs'
    path.write_text(harness+script+checks)
    subprocess.run(['node',str(path)],check=True,capture_output=True,text=True)


@pytest.mark.parametrize('level', [20,40,60])
def test_druid_matrix_units_slots_and_weights(level):
    from src.rulesets.forever.classes.druid import engine
    from src.v2.spec_matrix import _mature_score
    for profile in ('feral','bear','balance'):
        score = engine.experimental_level_score(level, engine.Talents(), profile)
        if not score.get('feasible', True):
            continue
        assert score['total_s'] == pytest.approx(score['kill_s'] + score['recovery_s'] + score['travel_s'])
        gear = score['gear_stats']
        for stat in ('strength','intellect','spell_power','armor'):
            assert gear[stat] == pytest.approx(sum(x.get(stat,0) for x in gear['slots'].values()))
    row, _, _ = _mature_score(engine, level, engine.Talents())
    assert row['mobs_per_hour'] == pytest.approx(3600/row['seconds_per_mob'])
