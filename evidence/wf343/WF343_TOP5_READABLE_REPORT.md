# Druid L20 — source display % stat weights & Top 5 per slot

**Status: P3 FAIL** (remaining defense channels, procs/relics and other effects).

Items: 1175; slots: 18; uncertain items: 254.

Raw SQLite values: crit 14 = +1%; hit 10 = +1%; dodge 12 = +1%; defense is skill. No TBC scaling.

## Build-specific weights

Units: seconds saved per mob per ONE RAW SQLITE STAT unit (except weapon-speed as stated).

| Stat | weight | source/status |
|---|---:|---|
| agility | 0.0012555716324804678 | DISCRETE_SMOOTHED |
| armor | 0.0007311892381975227 | DISCRETE_SMOOTHED |
| attack_power | 0.0004530237575124385 | DISCRETE_SMOOTHED |
| crit | 0.00016179419911158517 | SOURCE_DISPLAY_PERCENT_MEASURED_100MOB |
| defense | 0.0001090204974173048 | PARTIAL_DEFENSE_SKILL_FIRST_ORDER_AVOIDANCE_PROXY |
| dodge | 0.00011356301814302584 | SOURCE_DISPLAY_PERCENT_MEASURED_100MOB |
| healing | UNKNOWN | UNSUPPORTED_RUNTIME_AXIS |
| hit | 0.00036241900600995046 | SOURCE_DISPLAY_PERCENT_MEASURED_100MOB |
| intellect | 3.9551645082624987e-05 | MEASURED |
| mp5 | UNKNOWN | INCONCLUSIVE_DISCRETE_PROBES |
| spell_power | 0.0 | MEASURED_ZERO_RANGE |
| spirit | UNKNOWN | INCONCLUSIVE_DISCRETE_PROBES |
| stamina | 0.0 | MEASURED_ZERO_RANGE |
| strength | 0.000906047515024877 | DISCRETE_SMOOTHED |
| wand_dps | UNKNOWN | UNSUPPORTED_RUNTIME_AXIS |
| weapon_dps | 0.00906047515024877 | MEASURED |
| weapon_speed | 0.0 | CONTEXTUAL_ZERO_FROM_SOURCE_FORM_FIXED |

## back — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Glowing Lizardscale Cloak | 6449 | 0.022157 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 20.0×0.000731189=0.014624, agility 6.0×0.00125557=0.0075334
| 2 | Cape of the Brotherhood | 5193 | 0.021633 | none |
  - Components: armor 21.0×0.000731189=0.015355, agility 5.0×0.00125557=0.0062779, stamina 3.0×0=0
| 3 | Sentry Cloak | 2059 | 0.020377 | none |
  - Components: armor 21.0×0.000731189=0.015355, agility 4.0×0.00125557=0.0050223, stamina 5.0×0=0
| 4 | Grave Shroud | 279865 | 0.019853 | none |
  - Components: armor 20.0×0.000731189=0.014624, strength 3.0×0.000906048=0.0027181, agility 2.0×0.00125557=0.0025111, stamina 5.0×0=0
| 5 | Spritekin Cloak | 16990 | 0.019646 | none |
  - Components: armor 20.0×0.000731189=0.014624, agility 4.0×0.00125557=0.0050223, stamina 3.0×0=0

## chest — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Defender's Leather Armor | 252434 | 0.096389 | none |
  - Components: armor 118.0×0.000731189=0.08628, strength 7.0×0.000906048=0.0063423, agility 3.0×0.00125557=0.0037667, stamina 5.0×0=0
| 2 | Panther Armor | 6670 | 0.078188 | none |
  - Components: armor 89.0×0.000731189=0.065076, agility 9.0×0.00125557=0.0113, strength 2.0×0.000906048=0.0018121
| 3 | Bloodied Chestwraps | 271212 | 0.076534 | none |
  - Components: armor 89.0×0.000731189=0.065076, agility 9.0×0.00125557=0.0113, intellect 4.0×3.95516e-05=0.00015821, stamina 4.0×0=0
| 4 | Brawler's Leather Armor | 252490 | 0.075470 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 85.0×0.000731189=0.062151, agility 7.0×0.00125557=0.008789, strength 5.0×0.000906048=0.0045302, stamina 3.0×0=0
| 5 | Gloomshroud Armor | 1489 | 0.073262 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 94.0×0.000731189=0.068732, strength 5.0×0.000906048=0.0045302, stamina 8.0×0=0

## feet — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Defender's Leather Boots | 252441 | 0.076918 | none |
  - Components: armor 99.0×0.000731189=0.072388, strength 5.0×0.000906048=0.0045302, stamina 5.0×0=0
| 2 | Feet of the Lynx | 1121 | 0.058828 | none |
  - Components: armor 63.0×0.000731189=0.046065, agility 8.0×0.00125557=0.010045, strength 3.0×0.000906048=0.0027181
| 3 | Brawler's Leather Boots | 252439 | 0.055411 | none |
  - Components: armor 61.0×0.000731189=0.044603, agility 5.0×0.00125557=0.0062779, strength 5.0×0.000906048=0.0045302, stamina 4.0×0=0
| 4 | Footpads of the Fang | 10411 | 0.052136 | none |
  - Components: armor 61.0×0.000731189=0.044603, agility 6.0×0.00125557=0.0075334, stamina 6.0×0=0
| 5 | Trapper's Leather Boots | 252440 | 0.051039 | none |
  - Components: armor 61.0×0.000731189=0.044603, agility 5.0×0.00125557=0.0062779, intellect 4.0×3.95516e-05=0.00015821, stamina 5.0×0=0

## hands — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Defender's Leather Gloves | 252496 | 0.067238 | none |
  - Components: armor 87.0×0.000731189=0.063613, strength 4.0×0.000906048=0.0036242, stamina 4.0×0=0
| 2 | Gloves of the Fang | 10413 | 0.049179 | none |
  - Components: armor 52.0×0.000731189=0.038022, agility 6.0×0.00125557=0.0075334, strength 4.0×0.000906048=0.0036242
| 3 | Brawler's Leather Gloves | 252494 | 0.047400 | none |
  - Components: armor 53.0×0.000731189=0.038753, agility 4.0×0.00125557=0.0050223, strength 4.0×0.000906048=0.0036242, stamina 3.0×0=0
| 4 | Bristlebark Gloves | 14572 | 0.046668 | none |
  - Components: armor 52.0×0.000731189=0.038022, agility 4.0×0.00125557=0.0050223, strength 4.0×0.000906048=0.0036242
| 5 | Flamefist Grips | 270231 | 0.044125 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 51.0×0.000731189=0.037291, agility 4.0×0.00125557=0.0050223, strength 2.0×0.000906048=0.0018121

## head — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Brawler's Leather Hood | 252504 | 0.065615 | none |
  - Components: armor 76.0×0.000731189=0.05557, agility 8.0×0.00125557=0.010045, stamina 10.0×0=0
| 2 | Defender's Leather Hood | 252447 | 0.062819 | none |
  - Components: armor 76.0×0.000731189=0.05557, strength 8.0×0.000906048=0.0072484, stamina 10.0×0=0
| 3 | Trapper's Leather Hood | 252505 | 0.055887 | none |
  - Components: armor 76.0×0.000731189=0.05557, intellect 8.0×3.95516e-05=0.00031641, stamina 10.0×0=0
| 4 | Resilient Leather Mask | 211857 | 0.055570 | unmodeled_source_extra:resipct |
  - Components: armor 76.0×0.000731189=0.05557
| 5 | Totemic Leather Hood | 252448 | 0.055570 | none |
  - Components: armor 76.0×0.000731189=0.05557, spell_power 9.0×0=0, stamina 10.0×0=0

## legs — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Defender's Leather Pants | 252445 | 0.103844 | none |
  - Components: armor 124.0×0.000731189=0.090667, strength 9.0×0.000906048=0.0081544, agility 4.0×0.00125557=0.0050223, stamina 6.0×0=0
| 2 | Trapper's Leather Pants | 252501 | 0.076852 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 82.0×0.000731189=0.059958, agility 9.0×0.00125557=0.0113, strength 6.0×0.000906048=0.0054363, intellect 4.0×3.95516e-05=0.00015821
| 3 | Brawler's Leather Pants | 252500 | 0.076694 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 82.0×0.000731189=0.059958, agility 9.0×0.00125557=0.0113, strength 6.0×0.000906048=0.0054363, stamina 4.0×0=0
| 4 | Leggings of the Fang | 10410 | 0.072863 | none |
  - Components: armor 78.0×0.000731189=0.057033, agility 9.0×0.00125557=0.0113, strength 5.0×0.000906048=0.0045302, stamina 4.0×0=0
| 5 | Totemic Leather Pants | 252446 | 0.068270 | none |
  - Components: armor 82.0×0.000731189=0.059958, strength 9.0×0.000906048=0.0081544, intellect 4.0×3.95516e-05=0.00015821, spell_power 7.0×0=0, stamina 4.0×0=0

## neck — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Scout's Medallion | 20442 | 0.007533 | none |
  - Components: agility 6.0×0.00125557=0.0075334, stamina 2.0×0=0
| 2 | Erudite's Amulet | 277204 | 0.005022 | none |
  - Components: agility 4.0×0.00125557=0.0050223, stamina 6.0×0=0
| 3 | Mark of the Pack Leader | 285331 | 0.004728 | none |
  - Components: strength 5.0×0.000906048=0.0045302, intellect 5.0×3.95516e-05=0.00019776
| 4 | Snake Eye Kaleidoscope | 273088 | 0.002201 | INCONCLUSIVE_DISCRETE_PROBES, unmodeled_source_extra:arcres, unmodeled_source_extra:firres, unmodeled_source_extra:frores, unmodeled_source_extra:natres |
  - Components: agility 1.0×0.00125557=0.0012556, strength 1.0×0.000906048=0.00090605, intellect 1.0×3.95516e-05=3.9552e-05, stamina 1.0×0=0
| 5 | Sorcerer Collar | 273457 | 0.000079 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: intellect 2.0×3.95516e-05=7.9103e-05

## offhand — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Tork Wrench | 11855 | 0.001891 | none |
  - Components: strength 2.0×0.000906048=0.0018121, intellect 2.0×3.95516e-05=7.9103e-05
| 2 | Defective Samophlange | 274743 | 0.000198 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: intellect 5.0×3.95516e-05=0.00019776
| 3 | Seer's Fine Stein | 7608 | 0.000119 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: intellect 3.0×3.95516e-05=0.00011865
| 4 | Spellbinder Orb | 15926 | 0.000119 | none |
  - Components: intellect 3.0×3.95516e-05=0.00011865
| 5 | Expended Apothecary Vial | 281294 | 0.000119 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: intellect 3.0×3.95516e-05=0.00011865

## relic — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Idol of Ursine Rage | 206954 | 0.000000 | item_effect_tooltip_not_typed |
  - Components: no mapped stat effects
| 2 | Ferocious Idol | 208689 | 0.000000 | item_effect_tooltip_not_typed |
  - Components: no mapped stat effects
| 3 | Unbalanced Idol | 210195 | 0.000000 | item_effect_tooltip_not_typed |
  - Components: no mapped stat effects
| 4 | Idol of the Wild | 210534 | 0.000000 | item_effect_tooltip_not_typed |
  - Components: no mapped stat effects
| 5 | Mystic Mushroom | 249396 | 0.000000 | item_effect_tooltip_not_typed |
  - Components: no mapped stat effects

## ring1 — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Legionnaire's Band | 20429 | 0.008646 | none |
  - Components: agility 4.0×0.00125557=0.0050223, strength 4.0×0.000906048=0.0036242, stamina 2.0×0=0
| 2 | Signet of the Zhevra | 285330 | 0.007533 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: agility 6.0×0.00125557=0.0075334
| 3 | First Mate Band | 284715 | 0.005436 | none |
  - Components: strength 6.0×0.000906048=0.0054363, stamina 2.0×0=0
| 4 | Bounty Hunter's Ring | 5351 | 0.003767 | none |
  - Components: agility 3.0×0.00125557=0.0037667, stamina 1.0×0=0
| 5 | Demon Band | 12054 | 0.003624 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: strength 4.0×0.000906048=0.0036242, stamina 2.0×0=0

## ring2 — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Legionnaire's Band | 20429 | 0.008646 | none |
  - Components: agility 4.0×0.00125557=0.0050223, strength 4.0×0.000906048=0.0036242, stamina 2.0×0=0
| 2 | Signet of the Zhevra | 285330 | 0.007533 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: agility 6.0×0.00125557=0.0075334
| 3 | First Mate Band | 284715 | 0.005436 | none |
  - Components: strength 6.0×0.000906048=0.0054363, stamina 2.0×0=0
| 4 | Bounty Hunter's Ring | 5351 | 0.003767 | none |
  - Components: agility 3.0×0.00125557=0.0037667, stamina 1.0×0=0
| 5 | Demon Band | 12054 | 0.003624 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: strength 4.0×0.000906048=0.0036242, stamina 2.0×0=0

## shirt — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Red Linen Shirt | 2575 | 0.000000 | none |
  - Components: no mapped stat effects
| 2 | Captain Sander's Shirt | 3342 | 0.000000 | none |
  - Components: no mapped stat effects

## shoulder — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Rugged Spaulders | 5254 | 0.063613 | unmodeled_source_extra:arcres, unmodeled_source_extra:firres, unmodeled_source_extra:frores, unmodeled_source_extra:natres |
  - Components: armor 87.0×0.000731189=0.063613
| 2 | Serpent's Shoulders | 5404 | 0.055999 | none |
  - Components: armor 68.0×0.000731189=0.049721, agility 5.0×0.00125557=0.0062779
| 3 | Tanned Shoulderpads | 270023 | 0.053377 | none |
  - Components: armor 73.0×0.000731189=0.053377, spell_power 3.0×0=0, stamina 9.0×0=0
| 4 | Forest Leather Mantle | 4709 | 0.046796 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 64.0×0.000731189=0.046796, stamina 4.0×0=0
| 5 | Prospector's Pads | 14566 | 0.046796 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 64.0×0.000731189=0.046796, stamina 4.0×0=0

## trinket1 — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Rune of Perfection | 21566 | 0.000000 | item_effect_tooltip_not_typed |
  - Components: stamina 4.0×0=0
| 2 | Rune of Duty | 21568 | 0.000000 | unmodeled_source_extra:arcres, unmodeled_source_extra:firres, unmodeled_source_extra:frores, unmodeled_source_extra:holres, unmodeled_source_extra:natres, item_effect_tooltip_not_typed |
  - Components: stamina 4.0×0=0
| 3 | Lookie's Spyglass | 273298 | 0.000000 | INCONCLUSIVE_DISCRETE_PROBES, item_effect_tooltip_not_typed |
  - Components: no mapped stat effects

## trinket2 — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Rune of Perfection | 21566 | 0.000000 | item_effect_tooltip_not_typed |
  - Components: stamina 4.0×0=0
| 2 | Rune of Duty | 21568 | 0.000000 | unmodeled_source_extra:arcres, unmodeled_source_extra:firres, unmodeled_source_extra:frores, unmodeled_source_extra:holres, unmodeled_source_extra:natres, item_effect_tooltip_not_typed |
  - Components: stamina 4.0×0=0
| 3 | Lookie's Spyglass | 273298 | 0.000000 | INCONCLUSIVE_DISCRETE_PROBES, item_effect_tooltip_not_typed |
  - Components: no mapped stat effects

## waist — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Defender's Leather Belt | 252430 | 0.057732 | none |
  - Components: armor 74.0×0.000731189=0.054108, strength 4.0×0.000906048=0.0036242, stamina 4.0×0=0
| 2 | Deviate Scale Belt | 6468 | 0.046287 | none |
  - Components: armor 51.0×0.000731189=0.037291, agility 5.0×0.00125557=0.0062779, strength 3.0×0.000906048=0.0027181, stamina 6.0×0=0
| 3 | Blackened Defias Belt | 10403 | 0.044714 | none |
  - Components: armor 50.0×0.000731189=0.036559, attack_power 18.0×0.000453024=0.0081544
| 4 | Screecher Belt | 16987 | 0.042194 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 50.0×0.000731189=0.036559, attack_power 12.0×0.000453024=0.0054363, intellect 5.0×3.95516e-05=0.00019776, stamina 3.0×0=0
| 5 | Brawler's Leather Belt | 252428 | 0.041550 | none |
  - Components: armor 45.0×0.000731189=0.032904, agility 4.0×0.00125557=0.0050223, strength 4.0×0.000906048=0.0036242, stamina 3.0×0=0

## weapon — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Hammerbone | 270018 | 0.194257 | none |
  - Components: weapon_dps 20.44×0.00906048=0.1852, strength 10.0×0.000906048=0.0090605, stamina 7.0×0=0, weapon_speed 3.4×0=0
| 2 | Smite's Mighty Hammer | 7230 | 0.193571 | none |
  - Components: weapon_dps 19.71×0.00906048=0.17858, strength 11.0×0.000906048=0.0099665, agility 4.0×0.00125557=0.0050223, weapon_speed 3.5×0=0
| 3 | Twisted Chanter's Staff | 890 | 0.185592 | none |
  - Components: weapon_dps 20.44×0.00906048=0.1852, intellect 10.0×3.95516e-05=0.00039552, stamina 6.0×0=0, weapon_speed 3.4×0=0
| 4 | Advisor's Gnarled Staff | 20425 | 0.178287 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: weapon_dps 19.66×0.00906048=0.17813, intellect 4.0×3.95516e-05=0.00015821, stamina 8.0×0=0, weapon_speed 2.9×0=0
| 5 | Segmented Spider Leg | 271203 | 0.174389 | none |
  - Components: weapon_dps 17.5×0.00906048=0.15856, agility 9.0×0.00125557=0.0113, strength 5.0×0.000906048=0.0045302, weapon_speed 3.6×0=0

## wrist — weighted Top 5

| # | Item | Item ID | Known score | Uncertainty |
|---:|---|---:|---:|---|
| 1 | Forest Leather Bracers | 3202 | 0.033332 | none |
  - Components: armor 37.0×0.000731189=0.027054, agility 5.0×0.00125557=0.0062779
| 2 | Spare Part Bindings | 279875 | 0.033014 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 40.0×0.000731189=0.029248, agility 3.0×0.00125557=0.0037667, stamina 5.0×0=0
| 3 | Witherbite Bracers | 271202 | 0.032195 | INCONCLUSIVE_DISCRETE_PROBES |
  - Components: armor 37.0×0.000731189=0.027054, agility 4.0×0.00125557=0.0050223, intellect 3.0×3.95516e-05=0.00011865
| 4 | Wolf Bracers | 4794 | 0.032076 | none |
  - Components: armor 37.0×0.000731189=0.027054, agility 4.0×0.00125557=0.0050223, stamina 2.0×0=0
| 5 | Bristlebark Bindings | 14569 | 0.031170 | none |
  - Components: armor 35.0×0.000731189=0.025592, agility 3.0×0.00125557=0.0037667, strength 2.0×0.000906048=0.0018121

## Reference and item runtime spot-checks

```json
{
  "7348": {
    "item_name": "Fletcher's Gloves",
    "slot": "hands",
    "status": "COMPLETE",
    "measured_100mob_s_per_mob": 14.129452576870774,
    "displayed_crit_pct": 1.0,
    "displayed_hit_pct": 0.0,
    "defense_skill": 0.0,
    "full_L2_valid": false
  },
  "12985": {
    "item_name": "Ring of Defense",
    "slot": "ring1",
    "status": "COMPLETE",
    "measured_100mob_s_per_mob": 14.13025502773182,
    "displayed_crit_pct": 0.0,
    "displayed_hit_pct": 0.0,
    "defense_skill": 4.0,
    "full_L2_valid": false
  }
}
```