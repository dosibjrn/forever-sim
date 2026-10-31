"""Druid talent schema transcribed from pinned mage-level-sim source.

Source: src/rulesets/forever/classes/druid/talents.py on main 2026-10-29,
TALENT_SCHEMA_BUILD 1.60.1.70170, src/shared/talents/tree.py.
Stricter per-tier prior-row requirement + explicit WF482 Vengeance prerequisite.
The order is the simulator's talent-string order.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Talent:
    name: str
    maximum: int
    needed: int
    prerequisite: tuple[str,int] | None = None

B = [
 ('improved_wrath',5,0),('genesis',5,0),('moonglow',3,5),('improved_moonfire',2,5),
 ('natures_majesty',2,5),('natures_reach',2,5),('improved_entangling_roots',3,10),
 ('natures_splendor',1,10),('insect_swarm',1,15),('vengeance',5,15,('improved_moonfire',2)),
 ('improved_starfire',5,15),('overgrowth',2,20),('natures_grace',1,20),
 ('eclipse',3,20),('moonfury',5,25),('moonkin_form',1,30),
]
F = [
 ('ferocity',5,0),('heart_of_the_wild',5,0),('feral_swiftness',2,5),
 ('feral_instinct',3,5),('brutal_impact',2,5),('thick_hide',3,5),
 ('shredding_attacks',3,10),('savage_fury',2,10),('feral_charge',1,10),
 ('sharpened_claws',2,10),('shifting_power',1,15,('shredding_attacks',3)),
 ('mangle',1,15,('savage_fury',2)),('predatory_strikes',3,15),
 ('blood_frenzy',2,15,('sharpened_claws',2)),
 ('improved_shifting_power',2,20,('shifting_power',1)),
 ('leader_of_the_pack',1,20),('predatory_instincts',2,20),
 ('natural_reaction',5,25),('rend_and_tear',5,25,('predatory_strikes',3)),
 ('berserk',1,30,('leader_of_the_pack',1)),
]
R = [
 ('natures_focus',5,0),('furor',5,0),('naturalist',5,5),('subtlety',3,5),
 ('natural_shapeshifter',3,5),('reflection',3,10),('gift_of_nature',5,10),
 ('gift_of_earthmother',1,10),('tranquil_spirit',5,15),('improved_rejuvenation',3,15),
 ('swiftmend',1,15),('natures_swiftness',1,20),('living_spirit',3,20),
 ('improved_tranquility',2,20),('improved_regrowth',5,25),('wild_growth',1,30),
]
TREES=tuple(tuple(Talent(*item) for item in tree) for tree in (B,F,R))
LOOKUP={t.name:(ti,i,t) for ti,tree in enumerate(TREES) for i,t in enumerate(tree)}

def parse(s):
    parts=s.split('-')
    if len(parts)!=3:
        raise ValueError('Expected three tree strings')
    result=[]
    for raw,tree in zip(parts,TREES):
        if len(raw)>len(tree) or any(c not in '0123456789' for c in raw):
            raise ValueError('Bad encoded talent tree')
        result.append([int(c) for c in raw.ljust(len(tree),'0')])
    return result

def encode(ranks):
    return '-'.join(''.join(str(r) for r in ranks[ti]).rstrip('0') for ti in range(3))

def points(ranks):return sum(map(sum,ranks))

def legal_add(ranks,ti,i):
    talent=TREES[ti][i]
    if ranks[ti][i]>=talent.maximum: return False
    if sum(r for j,r in enumerate(ranks[ti]) if TREES[ti][j].needed<talent.needed)<talent.needed: return False
    if talent.prerequisite:
        pti,pi,_=LOOKUP[talent.prerequisite[0]]
        if ranks[pti][pi]<talent.prerequisite[1]: return False
    return True

def validate(ranks,*,moonkin=True,insect=True):
    if len(ranks)!=3 or any(len(row)!=len(schema) for row,schema in zip(ranks,TREES)): return False
    if points(ranks)!=51: return False
    if moonkin and ranks[0][15]!=1:return False
    if insect and ranks[0][8]!=1:return False
    for ti,tree in enumerate(TREES):
        for i,t in enumerate(tree):
            n=ranks[ti][i]
            if n<0 or n>t.maximum:return False
            if n and sum(r for j,r in enumerate(ranks[ti]) if tree[j].needed<t.needed)<t.needed:return False
            if n and t.prerequisite:
                pti,pi,_=LOOKUP[t.prerequisite[0]]
                if ranks[pti][pi]<t.prerequisite[1]:return False
    return True

if __name__=='__main__':
    s='5532220115501351--505'
    print('ref',points(parse(s)),validate(parse(s)),encode(parse(s)))