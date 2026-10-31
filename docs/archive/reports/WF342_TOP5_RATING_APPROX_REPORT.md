# WF342 — Druid L20 provisio-Top 5 / slotti

**Ei lopullisesti hyväksytty P3:** Forever 70338:n rating-kertoimia, defensen koko combat tablea tai kaikkia item-proceja ei ole lähdevahvistettu.
Mallissa crit/hit/defense/dodge muunnetaan historiallisella (StatLogic/TBC) kertoimella ja sen vaikutus testataan oikealla 100 mobin CombatRuntimella.
L0-pisteet ovat säästyneitä sekunteja per mob per rating-yksikkö. Positiivinen arvo on parempi.
Top 5 on **provisionaalinen malliranking**, ei kaikkien itemien L2-ajojen tulos eikä lupaus todellisesta parhaasta.

## 100 mobin mallinnetut rating-weightit

| Stat | s/mob per +1 rating | Status |
|---|---:|---|
| crit | 0.001132559 | DISCRETE_SMOOTHED, historical analogue |
| hit | 0.001132559 | DISCRETE_SMOOTHED, historical analogue |
| defense | 0.006673794 | DISCRETE_SMOOTHED, historical analogue |
| dodge | 0.009136435 | DISCRETE_SMOOTHED, historical analogue |

## Kaikkien slottien Top 5 (provisionaalinen)

### back

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Glowing Lizardscale Cloak | 6449 | 0.022157 |
| 2 | Cape of the Brotherhood | 5193 | 0.021633 |
| 3 | Sentry Cloak | 2059 | 0.020377 |
| 4 | Grave Shroud | 279865 | 0.019853 |
| 5 | Spritekin Cloak | 16990 | 0.019646 |

### chest

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Defender's Leather Armor | 252434 | 0.096389 |
| 2 | Panther Armor | 6670 | 0.078188 |
| 3 | Bloodied Chestwraps | 271212 | 0.076534 |
| 4 | Brawler's Leather Armor | 252490 | 0.075470 |
| 5 | Gloomshroud Armor | 1489 | 0.073262 |

### feet

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Defender's Leather Boots | 252441 | 0.076918 |
| 2 | Feet of the Lynx | 1121 | 0.058828 |
| 3 | Brawler's Leather Boots | 252439 | 0.055411 |
| 4 | Footpads of the Fang | 10411 | 0.052136 |
| 5 | Trapper's Leather Boots | 252440 | 0.051039 |

### hands

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Defender's Leather Gloves | 252496 | 0.067238 |
| 2 | Fletcher's Gloves | 7348 | 0.054609 |
| 3 | Gloves of the Fang | 10413 | 0.049179 |
| 4 | Brawler's Leather Gloves | 252494 | 0.047400 |
| 5 | Bristlebark Gloves | 14572 | 0.046668 |

### head

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Brawler's Leather Hood | 252504 | 0.065615 |
| 2 | Defender's Leather Hood | 252447 | 0.062819 |
| 3 | Trapper's Leather Hood | 252505 | 0.055887 |
| 4 | Resilient Leather Mask | 211857 | 0.055570 |
| 5 | Totemic Leather Hood | 252448 | 0.055570 |

### legs

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Defender's Leather Pants | 252445 | 0.103844 |
| 2 | Trapper's Leather Pants | 252501 | 0.076852 |
| 3 | Brawler's Leather Pants | 252500 | 0.076694 |
| 4 | Leggings of the Fang | 10410 | 0.072863 |
| 5 | Totemic Leather Pants | 252446 | 0.068270 |

### neck

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Scout's Medallion | 20442 | 0.007533 |
| 2 | Erudite's Amulet | 277204 | 0.005022 |
| 3 | Mark of the Pack Leader | 285331 | 0.004728 |
| 4 | Snake Eye Kaleidoscope | 273088 | 0.002201 |
| 5 | Sorcerer Collar | 273457 | 0.000079 |

### offhand

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Tork Wrench | 11855 | 0.001891 |
| 2 | Defective Samophlange | 274743 | 0.000198 |
| 3 | Seer's Fine Stein | 7608 | 0.000119 |
| 4 | Spellbinder Orb | 15926 | 0.000119 |
| 5 | Expended Apothecary Vial | 281294 | 0.000119 |

### relic

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Idol of Ursine Rage | 206954 | 0.000000 |
| 2 | Ferocious Idol | 208689 | 0.000000 |
| 3 | Unbalanced Idol | 210195 | 0.000000 |
| 4 | Idol of the Wild | 210534 | 0.000000 |
| 5 | Mystic Mushroom | 249396 | 0.000000 |

### ring1

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Ring of Defense | 12985 | 0.026695 |
| 2 | Slain Baron's Signet | 279867 | 0.013348 |
| 3 | Legionnaire's Band | 20429 | 0.008646 |
| 4 | Signet of the Zhevra | 285330 | 0.007533 |
| 5 | First Mate Band | 284715 | 0.005436 |

### ring2

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Ring of Defense | 12985 | 0.026695 |
| 2 | Slain Baron's Signet | 279867 | 0.013348 |
| 3 | Legionnaire's Band | 20429 | 0.008646 |
| 4 | Signet of the Zhevra | 285330 | 0.007533 |
| 5 | First Mate Band | 284715 | 0.005436 |

### shirt

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Red Linen Shirt | 2575 | 0.000000 |
| 2 | Captain Sander's Shirt | 3342 | 0.000000 |

### shoulder

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Rugged Spaulders | 5254 | 0.063613 |
| 2 | Serpent's Shoulders | 5404 | 0.055999 |
| 3 | Tanned Shoulderpads | 270023 | 0.053377 |
| 4 | Forest Leather Mantle | 4709 | 0.046796 |
| 5 | Prospector's Pads | 14566 | 0.046796 |

### trinket1

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Rune of Perfection | 21566 | 0.000000 |
| 2 | Rune of Duty | 21568 | 0.000000 |
| 3 | Lookie's Spyglass | 273298 | 0.000000 |

### trinket2

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Rune of Perfection | 21566 | 0.000000 |
| 2 | Rune of Duty | 21568 | 0.000000 |
| 3 | Lookie's Spyglass | 273298 | 0.000000 |

### waist

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Defender's Leather Belt | 252430 | 0.057732 |
| 2 | Deviate Scale Belt | 6468 | 0.046287 |
| 3 | Blackened Defias Belt | 10403 | 0.044714 |
| 4 | Screecher Belt | 16987 | 0.042194 |
| 5 | Brawler's Leather Belt | 252428 | 0.041550 |

### weapon

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Hammerbone | 270018 | 0.194257 |
| 2 | Smite's Mighty Hammer | 7230 | 0.193571 |
| 3 | Twisted Chanter's Staff | 890 | 0.185592 |
| 4 | Advisor's Gnarled Staff | 20425 | 0.178287 |
| 5 | Segmented Spider Leg | 271203 | 0.174389 |

### wrist

| Sija | Item | Item-ID | Mallipiste (s/mob) |
|---:|---|---:|---:|
| 1 | Forest Leather Bracers | 3202 | 0.033332 |
| 2 | Spare Part Bindings | 279875 | 0.033014 |
| 3 | Witherbite Bracers | 271202 | 0.032195 |
| 4 | Wolf Bracers | 4794 | 0.032076 |
| 5 | Bristlebark Bindings | 14569 | 0.031170 |

## Rajaukset

- Painoarvot ovat kiinteälle tunnetulle Cat/Claw-buildille; buildin muuttuessa painot pitää mitata uudelleen.
- 255 itemissä on ratkaisemattomia muita vaikutuksia tai vahvistamaton rating. Top 5 voi muuttua niiden mallinnuksen jälkeen.
- Defense antaa sekä Dodge- että incoming-miss-vaikutuksen; parry/block, incoming crit suppression ja defense-skill rounding ovat vielä avoimia.
- Client-version 1.60.1.70338 tarkka rating-muunnostaulukko on **vahvistamatta**. Historiallinen analogia ei ole kanoninen pelitieto.
- Vanilla-/SoD-rune-efektit eivät ole vapaasti haettavia, use_runes=false.
- Tuotannon strict L2 ei saa hyväksyä provisionaalista rating-mallia todisteeksi oikeasta combat rating -kertoimesta.

Lähteet: https://www.curseforge.com/wow/addons/statlogiclib ja https://warcraft.wiki.gg/wiki/Defense
