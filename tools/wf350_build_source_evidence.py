"""Pin current 70338 calculator talent names and rank caps in source order.

This is a source transcription of the 2026-10-11 calculator's 52 visible
linked talents and their displayed rank caps, not a generated guess from the
stale SQLite catalogue. The resulting JSON is the versioned source stage.
"""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
OBS=ROOT/'evidence/wf349/druid_l30_talent_rank_observations_70338.json'
OUT=ROOT/'evidence/wf350/druid_l30_source_talent_catalogue_70338.json'
GROUPS=[
 ('balance', '''Improved Wrath|Genesis|Moonglow|Improved Moonfire|Nature's Majesty|Nature's Reach|Improved Entangling Roots|Nature's Splendor|Insect Swarm|Vengeance|Improved Starfire|Overgrowth|Nature's Grace|Eclipse|Moonfury|Moonkin Form''', [5,5,3,2,2,2,3,1,1,5,5,2,1,3,5,1]),
 ('feral', '''Ferocity|Heart of the Wild|Feral Swiftness|Feral Instinct|Brutal Impact|Thick Hide|Shredding Attacks|Savage Fury|Feral Charge|Sharpened Claws|Shifting Power|Primal Bite|Predatory Strikes|Blood Frenzy|Improved Shifting Power|Leader of the Pack|Natural Instinct|Natural Reaction|Rend and Tear|Berserk''', [5,5,2,3,2,3,3,2,1,2,1,1,3,2,2,1,2,5,5,1]),
 ('restoration', '''Nature's Focus|Furor|Naturalist|Subtlety|Natural Shapeshifter|Reflection|Gift of Nature|Gift of the Earthmother|Tranquil Spirit|Improved Rejuvenation|Swiftmend|Nature's Swiftness|Living Spirit|Improved Tranquility|Improved Regrowth|Wild Growth''', [5,5,5,3,3,3,5,1,5,3,1,1,3,2,5,1]),
]
def slug(n):return re.sub('[^a-z0-9]+','_',n.lower()).strip('_').replace('_s_','s_')

def run():
    evidence=json.loads(OBS.read_text())
    evidence['observed_unreachable_talent_positions']=[x for x in evidence['observed_unreachable_talent_positions'] if x['indexed_talent_id']!='predatory_instincts']
    natural={'talent_id':'natural_instinct','tree_key':'feral','row':4,'max_rank':2,
        'source_url':'https://theforeverera.com/en/talents/druid/natural-instinct/',
        'effect_domain':'melee_critical_damage_bonus_fraction','target':'melee_abilities',
        'rank_values':[0.10,0.20],
        'additional_effect_domain':'spell_healing_from_intellect_fraction',
        'additional_target':'healing_spells',
        'additional_rank_values':[0.12,0.25],
        'condition':'melee_critical_hit_or_spell_healing',
        'source_build':'1.60.1.70338'}
    evidence['observations'].append(natural)
    catalogue=[]
    for tree,names,caps in GROUPS:
        values=names.split('|');assert len(values)==len(caps)
        for name,cap in zip(values,caps):
            tid=slug(name)
            catalogue.append({'talent_id':tid,'name':name,'tree_key':tree,
                'max_rank':cap,'source_url':f'https://theforeverera.com/en/talents/druid/{name.lower().replace("'","").replace(" ","-")}/',
                **({'replaces_talent_id':'predatory_instincts'} if tid=='natural_instinct' else {})})
    assert len(catalogue)==52 and len({x['talent_id'] for x in catalogue})==52
    data={'schema':'forever_checkpoint_talent_catalogue_source_v1',
        'source_url':'https://theforeverera.com/en/talents/druid/',
        'source_build':'1.60.1.70338','source_as_of':'2026-10-11',
        'class_key':'druid','min_level':30,'source_authority':'client_derived_fan_site_not_raw_DB2',
        'catalogue':catalogue,'observations':evidence['observations'],
        'observed_unreachable_talent_positions':evidence['observed_unreachable_talent_positions']}
    OUT.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    return OUT
if __name__=='__main__':print(run())
