#!/usr/bin/env python3
"""Migrate pinned combat boolean random comparisons to the common typed RNG wrapper.
This intentionally does not change the separate Mage standalone rng.hit/rng.crit
streams: they are not part of the Fight/SimRng interface.
"""
from pathlib import Path
edits={
"src/core/fight.rs":[
 ('self.random("FixedAura") < fixed.uptime','self.proc(fixed.uptime, "FixedAura")'),
 ('self.random("FixedAura") < fixed.chance_per_tick','self.proc(fixed.chance_per_tick, "FixedAura")')],
"src/core/fight/melee.rs":[
 ('self.random("Physical Crit Roll") < self.physical_crit_chance(spell)','self.proc(self.physical_crit_chance(spell), "Physical Crit Roll")')],
"src/core/fight/healing.rs":[
 ('self.random("Healing Crit Roll") < self.heal_crit_chance(spell)','self.proc(self.heal_crit_chance(spell), "Healing Crit Roll")'),
 ('self.random("Healing Crit Roll") < chance','self.proc(chance, "Healing Crit Roll")')],
"src/core/fight/damage_taken.rs":[
 ('self.random("Magical Crit Roll") < crit.max(0.0)','self.proc(crit.max(0.0), "Magical Crit Roll")')],
"src/core/fight/heals.rs":[
 ('fight.random("Party Hit") < 1.0 - (-rate * window).exp()','fight.proc(1.0 - (-rate * window).exp(), "Party Hit")'),
 ('self.random("Healing Crit Roll") < self.heal_tick_crit_chance(spell)','self.proc(self.heal_tick_crit_chance(spell), "Healing Crit Roll")')],
"src/classes/druid/items.rs":[
 ('fight.random(&label) <= self.proc_chance','fight.proc(self.proc_chance, &label)')],
"src/classes/warrior/items.rs":[
 ('fight.random(&self.rng_label) > self.proc_chance','!fight.proc(self.proc_chance, &self.rng_label)')],
"src/classes/warlock/talents/nightfall.rs":[
 ('fight.random(&self.rng_label) > self.proc_chance','!fight.proc(self.proc_chance, &self.rng_label)')]
}
for name,items in edits.items():
    f=Path(name);s=f.read_text()
    for before,after in items:
        assert before in s,(name,before)
        s=s.replace(before,after)
    f.write_text(s)
print('Migrated',sum(len(v) for v in edits.values()),'boolean decision patterns')
