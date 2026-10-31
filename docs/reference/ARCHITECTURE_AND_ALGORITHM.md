# Leveling Optimizer — current architecture and algorithm

> **Current architecture first.** This section describes the production Forever architecture as of v0.11.48.74.1.  The older Mage FAST/MC design notes are preserved below as an appendix because they still explain important scorer internals, but they are **not** the top-level orchestration contract anymore.

## 0. The system in one diagram

```text
ruleset/run context
  - ruleset
  - class
  - Forever build/as-of
  - objective/config
          │
          ▼
      ClassModel
  game/class semantics
          │
          ▼
   shared search_level()
  per-level orchestration
          │
          ▼
      LevelFrontier
  retained scored candidates
          │
          ▼
      solve_routes()
  generic candidate-graph DP
          │
          ▼
      DecisionResult
  one route/result authority
          │
          ▼
 decision_pipeline.publish_decisions()
          │
          ├── endpoint paths / regret / dual-spec
          └── listener / service publication
```

The important split is:

```text
ClassModel says WHAT a candidate means.
search_level() says HOW one level is searched.
solve_routes() says WHICH legal cross-level path wins.
DecisionResult says WHAT gets published.
```

The generic optimizer must not know spell names, talent field names, pets, forms, seals, Mage schools, or class-specific recovery tricks.

---

## 1. Ownership boundaries

### 1.1 ClassModel owns game semantics

`src/v2/class_model.py::ClassModel` is the stable class-plugin boundary.  A plugin may use any internal representation for talents, gear and policies; the kernel treats them as opaque values.

The intended class-facing operations are:

```python
initialize_item_options(ctx)
get_talent_candidates(ctx)
get_rotation_candidates(ctx)
optimize_policy(ctx)
evaluate(ctx) -> Evaluation
stat_weights(ctx, evaluation)
optimize_gear(ctx, stat_weights)

build_key(build)
build_points(build)
legal_one_point_transition(parent, child)
route_matches(build, route_definition)
```

Class-specific post-search adjudication is also behind the model boundary:

```python
rerank_repaired_pools(...)
adjudicate_per_level_candidate(...)
```

`runner_strategy()` is a capability declaration, not a class-name switch.

### 1.2 search_level() owns per-level orchestration

`src/v2/search_kernel.py::search_level()` owns the repeated optimizer shape:

```text
expand or accept candidate builds
      ↓
deterministic dedup
      ↓
policy / rotation selection
      ↓
evaluate
      ↓
stat weights
      ↓
gear update
      ↓
bounded fixed point
      ↓
CandidateResult / LevelFrontier data
```

It also owns candidate parallelism, deterministic result order and the current-level weighted objective contribution.

A class backend is allowed to be temporarily **bundled**.  `candidate_optimization_is_bundled()` is the compatibility seam for engines that still perform policy/gear/stat fixed-point work internally.  This prevents the generic kernel from optimizing the same dimensions twice.  New clean plugins should eventually return `False` and expose the operations separately.

### 1.3 solve_routes() owns the cross-level optimum

The path solver consumes retained `LevelFrontier` objects and opaque build semantics through `ClassModel` only.

It does **not** evaluate combat and it does **not** know class mechanics.

Conceptually:

```text
L10 frontier ──legal +1 point──> L11 frontier ──> ... ──> target
       \________________ generic shortest-path / DP _______________/
```

The same graph supports:

- unconstrained best route
- named endpoint/spec constraints
- preserved-spec regret
- respec constraints
- milestone endpoint paths

There must never be a second listener/publication-side route solver.

### 1.4 DecisionResult owns publication truth

The canonical chain is:

```text
LevelFrontier
    ↓
solve_routes()
    ↓
DecisionResult
    ↓
publish_decisions()
    ↓
listener / endpoint paths / regret
```

Presentation frontiers are diagnostics only.  They cannot independently drop, reconstruct or replace a legal route selected by the DP.

---

## 2. Current Forever class-plugin state

All supported Forever classes have explicit ClassModel types.  That does **not** mean all legacy internals have already been decomposed.

```text
Forever runner
    │
    └── active ClassModel
          ├── MageClassModel
          ├── HunterClassModel
          ├── DruidClassModel
          ├── PaladinClassModel
          └── WarriorClassModel
```

### Mage

Mage has an explicit `MageClassModel`, enters the shared `search_level()` kernel and owns Mage-only event adjudication hooks behind that interface.

However the mature Mage structural generator / policy search / gear work still predates ClassModel and is currently treated as a bundled candidate optimizer.  The architecture seam is correct; the internals are not yet fully split into every ideal hook.

### Hunter / Druid / Paladin / Warrior

These use explicit class model adapters but still delegate more heavily to their existing bundled engine scorer/fixed-point implementations through `EngineClassModel` compatibility behavior.

This is deliberate migration debt, not a reason to add class branches back to the generic optimizer.

### Migration rule

Peel one responsibility at a time from a bundled engine into the ClassModel hooks **only when useful for fidelity, testability or shared behavior**.  Do not perform a class-engine megarewrite merely to make the diagram prettier.

---

## 3. Two current search strategies, one architecture

Forever currently has two internal orchestration strategies:

```text
analytic_views
    current mature Mage path

continuity_beam
    current Hunter/Druid/Paladin/Warrior path
```

`forever_runner.py` selects between them through:

```python
model.runner_strategy()
```

not through:

```python
if class_name == "mage": ...
elif class_name == "hunter": ...
```

Both strategies must converge to the same canonical abstractions:

```text
LevelFrontier -> solve_routes() -> DecisionResult -> publication
```

Long term they may converge further internally, but **strategy uniformity is not required for architectural correctness**.  A class may need a different proposal generator while still obeying the same search/result contracts.

---

## 4. Shared cross-class contracts

### 4.1 Evaluation timing

Every backend publishes the same non-overlapping timing decomposition:

```text
kill/combat -> recovery -> between-pull travel
```

Canonical `Evaluation` exposes:

```text
score_s_per_100
kill_s_per_100
recovery_s_per_100
travel_s_per_100
mobs_per_hour
resource_metrics
diagnostics
```

A timing residual is machine-visible.  A scorer cannot silently publish a total assembled from incompatible timing authorities.

### 4.2 Recovery

Ordinary sit recovery has one shared ruleset-level authority:

```text
combat end state
   ↓
HP / mana deficits + passive regen + food/water/heal inputs
   ↓
solve_recovery()
   ↓
recovery_s + restored state
```

Class plugins provide the inputs/capabilities.  They do not reinvent generic eat/drink concurrency or the next-pull timing equation.

Class-only serial actions may remain outside the primitive, for example pet revive, shapeshift transitions, or Mage-specific cooldown resources.

### 4.3 Gear/stat fixed point

For unbundled plugins the generic kernel owns the bounded coordinate loop:

```text
policy -> evaluate -> stat weights -> gear -> repeat
```

If the bounded loop does not converge, publication uses the best state actually scored, never an unscored final gear proposal.

---

## 5. Forever build identity is part of simulation semantics

Forever is a moving beta.  Therefore a result is not fully identified by `(class, level, build)` alone.

Every production run has explicit:

```text
forever_build_as_of = YYYY-MM-DD
```

The execution chain is:

```text
JobRequest / --forever-as-of
        ↓
WOW_FOREVER_BUILD_AS_OF
        ↓
shared tuning resolver
        ↓
all scorers / workers
```

Raw source facts and dated server tuning are separate authorities.  Example: the public Wrath rank row remains raw data; the Sep-24 ~50% base-damage change is a dated runtime tuning override.

Numeric caches and checkpoint compatibility include Forever build identity.  A checkpoint from another beta date may seed structural search where safe, but it must not silently resume numeric simulation under changed tuning.

---

## 6. Service/control plane is separate from optimization semantics

The durable service owns lifecycle, not game mechanics:

```text
client / listener / CLI
        ↓
HTTP API
        ↓
QueueStore + scheduler
        ↓
immutable attempt root
        ↓
optimizer process
        ↓
validated publication manifest
        ↓
atomic current-publication pointer
```

HTTP handlers do not run optimizer scoring.  The scheduler/executor owns optimizer processes.  Completed attempts remain immutable; publication is an atomic pointer/overlay operation.

This separation matters because the optimizer kernel should be equally usable from a service job, a bounded test, or a direct diagnostic run.

---

## 7. The architecture invariants

These are stronger than any particular file layout:

1. **No class-name dispatch in generic optimization orchestration.** Use ClassModel capabilities/hooks.
2. **One per-level orchestration authority.** New class search should enter `search_level()` rather than inventing another generic loop.
3. **One route authority.** `LevelFrontier -> solve_routes() -> DecisionResult`.
4. **Listener is a consumer, not a solver.** It renders published decisions; it does not reconstruct optimum paths.
5. **Timing buckets do not overlap.** Combat, recovery and travel have explicit semantics.
6. **Ordinary recovery has one shared mathematical authority.** Class-specific capabilities are inputs, not parallel solvers.
7. **Forever tuning is build-scoped.** Never silently edit a raw fact to emulate a dated beta patch.
8. **Caches/checkpoints are semantic artifacts.** Reuse requires compatible engine/build identity.
9. **Class engines may migrate incrementally.** Compatibility adapters are acceptable; new generic class-specific branches are not.
10. **DP stays ignorant of gameplay.** It sees candidate nodes, objective costs and legal transitions.

---

## 8. Remaining architectural debt

The major platform shape is complete.  Remaining work is mostly **decomposition**, not redesign:

- Mage mature structural/policy/gear internals are still bundled behind `MageClassModel`.
- Hunter/Druid/Paladin/Warrior adapters delegate even more bundled scorer work to legacy engines.
- `analytic_views` and `continuity_beam` remain separate proposal/orchestration strategies behind the same contract.
- Classic Mage intentionally remains on the historical implementation path until a migration can preserve persisted identities/cache fingerprints.
- Some class packages are still large; split files only where the change is behavior-neutral and testable.

The target is therefore **not** “rewrite everything into identical classes”.  The target is:

```text
stable generic optimizer skeleton
+ explicit class-owned mechanics
+ shared cross-class primitives where semantics are genuinely common
```

---

# Appendix A — historical Mage FAST/MC design and detailed scorer internals

The material below predates the generic ClassModel/search/DecisionResult refactor.  It remains useful for understanding the mature Mage proposal/scoring engines, MC bridge and older implementation choices.  Where it conflicts with Sections 0–8 above, **the current architecture above is authoritative**.

## 1. Mitä tämä järjestelmä oikeastaan optimoi?

Optimizer etsii World of Warcraft Classic Era -magelle leveling-polun tasoilta 11–59 niin, että ding 60 saavutetaan mahdollisimman pienellä arvioidulla kokonaisajalla.

Yksi ratkaisu ei ole vain “final talent build”, vaan sarja:

```text
level
  -> talent allocation
  -> combat policy / rotation
  -> mahdollinen respec
  -> seuraava level
```

Paikallinen scorer ilmoittaa jokaiselle `(level, talents, policy)`-kolmikolle arvion muodossa **seconds per 100 mobs**. Polun kokonaiskustannus on

```text
T(path) = Σ_level  score(level, build, policy) * level_weight(level)
```

missä nykyinen `level_weight` on arvio saman levelin mobien määrästä, joka tarvitaan seuraavalle tasolle:

```text
level_weight(L)
 = XP_to_next(L) / same_level_mob_XP(L) / 100
```

Level 59 on viimeinen ajastettu level; level 60 on tavoite.

Järjestelmässä on kaksi eri optimizeria, joilla on tarkoituksella eri tehtävä:

```text
FAST / smooth
    halpa deterministic proposal engine
    "mistä kannattaisi etsiä?"

MC
    stochastic search + validator
    "toimiiko se oikeassa simulaattorissa?"
```

Fast ei ole auktoriteetti. MC on.

---

## 2. Korkean tason arkkitehtuuri

```text
                    ┌──────────────────────────────┐
                    │ Shared Classic Mage engine   │
                    │ spells, talents, ranks,      │
                    │ movement, mana, policies     │
                    └──────────────┬───────────────┘
                                   │
               ┌───────────────────┴───────────────────┐
               │                                       │
               ▼                                       ▼
      ┌─────────────────┐                    ┌─────────────────┐
      │ FAST / smooth   │                    │ MC optimizer    │
      │ deterministic   │                    │ stochastic      │
      └────────┬────────┘                    └────────┬────────┘
               │                                      │
      per-level candidate search             native MC candidates
               │                                      │
      continuity repair                       precision ladder
               │                                      │
      exact candidate-graph DP                outer respec search
               │                                      │
      0/1/2-respec paths                     validation/replay
               │                                      ▲
               └────── Fast -> MC bridge ─────────────┘
                              │
                              ▼
                    candidate union in MC

MC universe =
    native MC proposals
  ∪ Fast proposals
  ∪ historical priors
  ∪ cross-water priors
```

`run-both` käynnistää yhden listenerin, ajaa ensin smooth Fastin, kirjoittaa Fast→MC-bridgen ja käynnistää sen jälkeen normaalin persistentin MC-searchin.

Fast ja MC eivät siis ratkaise samaa ongelmaa kahdesti rinnakkain. Fast toimii nykyarkkitehtuurissa **proposal generatorina MC:lle**.

---

## 3. Keskeiset moduulit

| Kerros | Päämoduulit | Vastuu |
|---|---|---|
| Yhteinen mechanics engine | `classic_mage_leveling_optimizer_v10.py` | Spellit, rankit, talent-säännöt, mobit, mana, movement, policyt |
| Fast orchestration | `v2/runner.py` | Ajaa levelit, continuity-repairin, DP:n, snapshotit ja MC-bridgen |
| Fast structural search | `v2/local_search.py` | Halpa talent beam ja diversity-retention |
| Fast combat scoring | `v2/expected_engine.py` | Deterministic expected-value fight |
| Fast steady-state wrapper | `v2/analytic_scorer.py` | Smooth kill boundary, cooldown- ja Combustion-fixed point, policy search |
| Fast continuity | `v2/continuity.py` | Muuttaa independent per-level shortlistit legal path graphiksi |
| Fast path solver | `v2/path_dp.py` | Exact shortest-path DP annetussa candidate graphissa |
| Fast→MC | `v2/mc_bridge.py` | Level-seedit, full path challengerit, respec-hints |
| MC local search | `optimizer_core.py`, `pnp_cache.py` | Stochastic per-level poolit, precision ladder, cache, probes |
| MC outer search | `optimizer_core.py` | Talent continuity + respec search |
| MC lifecycle | `master_optimizer.py` | Persistent search, checkpoints, validation, promotion |
| UI | `listener.py`, `runtime_state.py`, `state_manager.py` | `/` = MC, `/fast` = Fast |

---

# FAST: miten ~40 sekunnin optimizer toimii?

## 4. Vaihe A — jokainen level ratkaistaan ensin itsenäisesti

Tasolla `L` käytettävissä on

```text
points = L - 9
```

talent-pistettä.

Fast ei ensin mieti levelien välistä jatkuvuutta. Se kysyy jokaisella levelillä erikseen:

> Jos saisin tällä levelillä valita minkä tahansa legalin `L-9` pisteen allocationin, mitkä näyttävät lupaavimmilta?

Levelit 11–59 voidaan tämän vuoksi laskea täysin toisistaan riippumatta.

Tämä on tärkeä arkkitehtuurivalinta: **global path problem pilkotaan ensin 49 pieneen local search -ongelmaan.**

---

## 5. Vaihe B — structural talent beam

Kaikkia legal talent allocationeja ei enumerateata.

Jokaisen levelin haku alkaa tyhjästä talent-puusta:

```text
depth 0: {}
depth 1: kaikki legal +1 point
depth 2: edellisen beamin kaikki legal +1 point
...
depth L-9
```

Jokaisen depthin jälkeen pidetään vain pieni beam, oletuksena noin 10 buildia.

Tässä vaiheessa ei ajeta varsinaista analytic fight scoreria. Jokainen partial allocation saa erittäin halvan O(1)-tyyppisen mechanics proxyn.

Proxy muodostaa erilliset rotation-lanet:

```text
Frostbolt
Fireball
Scorch
Arcane Missiles
mixed Fire, jos Improved Scorch tekee sen relevantiksi
```

Kullekin lasketaan karkea

```text
fight time + mana recovery time
```

kahdelle mob-luokalle:

```text
level + 1
level + 2
```

Proxy huomioi muun muassa expected damagen, cast timen, mana costin, regenin, juomisen sekä nykyisen control-aware korjauksen:

```text
effective range
-> engagement delay
-> mob closing speed
-> Frostbolt slow + Permafrost
-> time to melee
-> expected melee exposure
-> expected swings
-> pushback
-> Burning Soul resistance
```

Se ei aja varsinaista fight event loopia, Novaa/root-state machinea tai RNG:tä.

### Miksi beam ei romahda yhteen buildiin?

Retention ei ota vain numerollisesti parhaita.

Ensin suojataan parhaat rotaatio-archetypet, sitten talent-tree-familyt (`frost`, `arcane`, `fire`, `mixed`), ja vasta sen jälkeen täytetään jäljelle jäävä beam globaalisti parhailla.

Tämä on käytännössä vakuutus sitä vastaan, että halpa proxy tappaisi esimerkiksi deep Frost -haaran ennen kuin sen myöhemmät payoff-talentsit tulevat legaliksi.

---

## 6. Vaihe C — rich analytic score vain beam-finalisteille

Kun allocationissa on täydet `L-9` talent-pistettä, vasta silloin käytetään kallista deterministic analytic scoreria.

Tässä optimoidaan myös policy/rotation.

Policy search alkaa yhdellä halvalla anchorilla per spell family:

```text
pure Frostbolt
pure Fireball
pure Scorch
pure Arcane Missiles
```

Family saa laajemman policy searchin, jos joko sen anchor on riittävän lähellä parasta anchoria (nykyinen default noin 10 %) tai buildissa on riittävästi pisteitä kyseisessä talent treessä (nykyinen trigger 10 pistettä).

Fire-expansion voi tämän jälkeen tutkia kompaktia joukkoa esimerkiksi:

```text
pure Fireball
pure Scorch
FBa -> Sc ...
FBa -> FBa -> Sc -> Sc -> Sc ...
utility Fire Blast
R1 Frostbolt utility
Blink / Nova -variantit policy-basisin mukaan
```

Vanha ~54 Fire-cadence cross-product on olemassa reference/exhaustive-poluksi, mutta production search ei maksa sitä jokaiselle buildille.

---

# SMOOTH ANALYTIC SCORER

## 7. Yksi fight on deterministic event fight, ei DPS-kaava

Fastin nimi voi johtaa harhaan: rich scorer ei ole pelkkä

```text
mob HP / expected DPS
```

Se ajaa deterministic event fightin.

State sisältää muun muassa:

```text
time
mob HP
mana
distance
slow / root occupancy
Scorch stacks
Winter's Chill
Clearcasting probability
Ignite approximation
cooldown state
policy phase
```

Fight-loop valitsee policy-säännöillä seuraavan actionin, esimerkiksi Fire Blast execute, Nova, Blink, Arcane Missiles, R1 Frostbolt utility tai primary cast.

Projectile travel ja movement säilyvät oikeina tapahtumina. Tästä syystä esimerkiksi

```text
Fireball -> Fireball -> Scorch -> Scorch -> Scorch
```

voi käyttäytyä eri tavalla kuin yksinkertainen average DPS -lasku: Fireballit voivat olla ilmassa samalla kun Scorch-stackit syntyvät.

Satunnaisuus korvataan odotusarvoilla. Hit, resist, crit, procit jne. eivät heitä noppaa, vaan vaikuttavat expected damageen, expected manaan tai probabilistiseen stateen.

---

## 8. Mikä “smooth” oikeasti on?

Hard-mallissa deterministic fightilla on kova kill boundary:

```text
4 castia ei tapa
5. cast tappaa
```

Pieni expected-damage-ero voi siksi hypätä kokonaisen castin verran.

Smooth yrittää mallintaa sitä, että oikeassa stochastic fightissa välillä tarvitaan 4 ja välillä 5 castia.

Se arvioi primary direct damagen kumulatiivisen varianssin ja muuntaa sen suhteelliseksi HP-sigmaksi:

```text
sigma_rel ≈ sigma(cumulative damage) / mob_HP
```

Sen jälkeen jokaisesta workload-mobista ajetaan kaksi deterministic fightia:

```text
HP * (1 - sigma_rel)
HP * (1 + sigma_rel)
```

painoilla 50/50.

Koska workload itsessään on

```text
50 % level+1
50 % level+2
```

smooth-policy score muodostuu tyypillisesti enintään neljästä deterministic HP-skenaariosta per cooldown-state.

Tässä ei siis arvota RNG-sampleja. Tämä on pieni deterministic quadrature kill-boundaryn ympärillä.

---

## 9. Cooldownit ja pitkän aikavälin steady state

Fire Blast, Frost Nova ja Blink voivat olla fightin alussa ready tai cooldownilla.

Production Fast ei normaalisti enumeratea kaikkia cooldownien yhteistiloja. Se käyttää first-order marginal -mallia:

```text
score ≈ baseline(all down)
      + u_FB    * delta(Fire Blast ready)
      + u_Nova  * delta(Nova ready)
      + u_Blink * delta(Blink ready)
```

Ready-fraction `u_i` ratkaistaan fixed pointilla sen perusteella, kuinka pitkä pull cycle on ja kuinka usein policy käyttäisi kyseistä cooldownia.

Täysi joint `2^k` cooldown-state -malli on edelleen olemassa validation-moodina.

Combustion ratkaistaan erillisellä pienellä fixed pointilla: arvioidaan long-run extra crit contribution, ajetaan scorer uudestaan ja iteroidaan konvergenssiin.

Clearcasting alkaa jokaisessa pullissa probability 0:sta kuten MC-mallissa; landed spellit kasvattavat seuraavan castin expected free-mana -todennäköisyyttä.

Lopputulos on yksi deterministic arvio:

```text
seconds / 100 mobs
```

yhdelle `(level, talents, policy)`-kolmikolle.

---

# FAST GLOBAL PATH

## 10. Independent shortlistit eivät vielä muodosta talent pathia

Jos jokaisen levelin paras build vain tulostettaisiin peräkkäin, tulos voisi olla esimerkiksi:

```text
L29 Frost
L30 Fire
L31 Arcane
L32 Frost
```

vaikka talentteja ei voi vaihtaa näin ilman respecejä.

Siksi Fast tekee erillisen **continuity repair** -vaiheen.

---

## 11. Continuity repair rakentaa bounded legal graphin

Repair ei yritä ottaa kaikkien shortlist-buildien kaikkia mahdollisia vanhempia. Se räjähtäisi nopeasti subset latticeksi.

Nykyinen ratkaisu tekee kolme guaranteed legal backbonea:

```text
Frost spine
Arcane spine
Fire spine
```

Jokainen spine on oikea no-respec talent progression tasolta toiselle.

Näiden lisäksi forward propagation saa lähtöpisteitä independent level leader -buildeista. Kustakin parentista generoidaan legal `+1 talent` -lapset, mutta vain pieni proxy-rankattu subset jatkaa aktiivisena seuraavalle levelille.

Näin candidate graph pysyy pienenä, mutta siinä on aina vähintään yksi täysin legal 0-respec path.

Kaikki graphiin uutena lisätyt allocationit rich-scoretaan ennen path DP:tä.

---

## 12. Exact path DP — mutta exact vain tässä graphissa

Kun jokaisella levelillä on pieni joukko rich-scorettuja `LevelNodeja`, varsinainen path solve on exact layered shortest-path dynamic programming.

DP-state on käytännössä:

```text
(level, candidate_build, respecs_used)
```

No-respec edge on sallittu vain jos:

```text
child = parent + täsmälleen yksi legal talent point
```

Respec-edge voi hypätä seuraavan levelin mihin tahansa candidate allocationiin ja kasvattaa `respecs_used` yhdellä.

Respecillä ei tällä hetkellä ole aika-/gold-kustannusta; optimointi käsittelee annetun määrän respecejä ilmaisina.

Transition cost on destination levelin XP-painotettu local score.

Siksi recurrence on konseptuaalisesti:

```text
C[L, child, r] =
    local_cost(L, child)
  + min(
        C[L-1, legal_parent, r],
        min_parent C[L-1, parent, r-1]   # respec
    )
```

Fast ratkaisee erikseen budgetit

```text
0 respec
1 respec
2 respec
```

jotta myös respecien marginaalinen hyöty näkyy.

Tärkeä semanttinen tarkennus:

> DP on exact candidate graphissa. Koko WoW-talent-avaruuden suhteen Fast ei ole exact, koska candidate generation on beam/heuristic.

---

# FAST -> MC

## 13. Mitä Fast julkaisee?

Fast kirjoittaa `state/v2/mc_bridge/`-puuhun kolme eri asiaa.

Per-level seed bank sisältää analytic talent allocationeja. Full-path challengerit sisältävät valmiit legal 0/1/2-respec-polut. Respec schedules sisältävät vihjeet siitä, missä Fastin parhaat polut respeccasivat.

Full Fast path muunnetaan MC:n replay-formaattiin. Jos Fast objective alkaa leveliltä 11, bridge rekonstruoi myös legalin level-10 talent-prefixin.

Fastin analytic hours tallennetaan metadataksi, mutta niitä ei hyväksytä MC:n BEST-scoreksi.

---

# MC: stochastic authority

## 14. MC tekee oman haun, Fast ei korvaa sitä

MC:n candidate universe on:

```text
native stochastic proposals
+ Fast level seeds
+ Fast full-path challengers
+ historical optimizer state
+ cross-water priors
```

Fast siis vain kasvattaa MC:n todennäköisyyttä aloittaa search hyvistä kohdista.

Jos Fast on väärässä, MC voi löytää täysin oman ratkaisunsa.

---

## 15. MC:n per-level precision ladder

MC rakentaa jokaiselle levelille stochastic `SnapshotState`-poolin.

Se ei aja kaikkia kandidaatteja heti 100 mobilla, vaan käyttää ladderia:

```text
1 -> 2 -> 4 -> 8 -> 16 -> 32 -> 64 -> 100 mobs
```

Sama candidate käyttää samaa level-kohtaista random-streamiä precision-stagejen yli, ja cache pystyy jatkamaan aiemmasta prefixistä.

Jokaisella stageilla:

```text
candidate generation
-> stochastic policy scoring
-> diversity retention
-> local probes
-> global jumps
-> pienempi survivor pool
```

Levelit etenevät precision-frontiereina: kukaan ei siirry esimerkiksi 2-mobiin ennen kuin kaikkien levelien 1-mob frontier on olemassa.

Stagejen sisällä CPU annetaan priorityn perusteella niille leveleille, joissa lisäprecision on juuri nyt arvokkainta.

SQLite-cache (`pnp_cache`) säilyttää simulation historyn ja continuation staten, joten samaa stochastic työtä ei tarvitse jatkuvasti aloittaa alusta.

---

## 16. MC:n outer path search

Kun per-level stochastic poolit ovat olemassa, MC rakentaa talent pathia niiden yli.

Tässäkin no-respec progression ja respecit muodostavat layered search -ongelman, mutta MC:n poolit ovat suurempia, noisyja ja persistent search laajenee epoch/tier kerrallaan.

Respec-probe levels ovat vain **exploration priority**. Respec on edelleen legal jokaisella levelillä.

Fastin respec-timingit, family phase boundaries ja läheiset cross-family racet priorisoivat pienen joukon leveleitä, joilla vaihtoehtoisia respec timingejä kannattaa tutkia tavallista aggressiivisemmin.

Nykyinen cap estää Fast-seedejä muuttamasta kaikkia 49 leveliä “special probe” -leveleiksi.

---

## 17. MC replay ja authority

Fast full path tulee MC:lle ensin **unvalidated challengerina**.

MC rekonstruoi sen omaksi `OuterStateksi` ja ajaa nykyisen simulator-hashin stochastic fixed-policy replayn.

Oleellinen kohta on “fixed-policy”:

```text
Fast valitsi buildin + rotationin
MC mittaa juuri sen
```

Validation ei optimoi policyä uudestaan kesken mittauksen.

Näin Fastin analytic approximation voi ehdottaa jotain, mutta vain stochastic engine saa tehdä siitä validated candidate/BEST-ratkaisun.

MC:n native search jatkuu tämän jälkeen normaalisti.

---

# 18. `run-both` käytännössä

```text
1. start listener
2. run Fast smooth
3. Fast:
      per-level search
      continuity repair
      exact candidate-graph DP
      publish MC bridge
4. start MC
5. MC:
      inject Fast full paths as challengers
      import Fast per-level talent seeds
      import Fast respec timing hints
      replay/validate
      continue native anytime search
6. UI:
      /fast  analytic proposal view
      /      stochastic MC view
```

Fastin state ja MC:n state ovat erillisiä. Bridge on tarkoituksella yksisuuntainen proposal-interface, ei yhteinen mutable optimizer-state.

---

# 19. Miksi tämä ylipäätään toimii?

Koko järjestelmä perustuu kolmeen faktorisointiin.

Ensimmäinen on, että paikallinen combat performance voidaan arvioida hyvin nopeasti ilman stochastic sampleja, kun suurin osa RNG:stä korvataan odotusarvoilla. Fast voi siksi tutkia paljon enemmän rakennetta kuin MC samalla CPU-ajalla.

Toinen on, että hyvä global leveling path koostuu yleensä leveleittäin kohtuullisen hyvistä buildeista. Fast olettaa siis, että globaalisti tärkeät pathit voidaan rakentaa pienehköstä per-level candidate unionista. Continuity repair paikkaa sen, etteivät independent leaderit itsessään muodosta legal pathia.

Kolmas on, että Fastin ei tarvitse olla täysin oikeassa. Sen tarvitsee vain nostaa hyvät alueet MC:n candidate pooliin. Stochastic MC toimii viimeisenä turvaverkkona approximation biasille.

Tämä tekee kokonaisuudesta enemmän **proposal + verification** -järjestelmän kuin yhden monoliittisen optimizerin.

---

# 20. “Siis hetkinen…” — kohdat joista nousee parannusideoita

1. **Objective käyttää same-level mob XP:tä, mutta scorer taistelee L+1/L+2 mobeja vastaan.** Tämä on selkein tarkistettava oletus. Saman levelin build-ranking ei siitä muutu, mutta levelien keskinäinen painotus muuttuu, joten respec-timing ja absoluuttinen leveling-aika voivat muuttua. Jos workload todella tarkoittaa L+1/L+2 grindausta, objective-weightin pitäisi todennäköisesti käyttää saman workloadin expected XP/mob eikä same-level XP:tä.

2. **Structural beam pisteyttää partial buildin target-levelillä.** Esimerkiksi L50-searchin depth 10 -buildissa on vain 10 talent-pistettä, mutta sitä arvostellaan L50 spelleillä/mobeilla. Se on tarkoituksellinen heuristic, mutta deep-tree payoff voi näyttää huonolta ennen kuin tarvittavat prerequisite-pisteet ovat paikallaan. Family/lane retention peittää tätä ongelmaa, ei ratkaise sitä. Parempi ranking voisi käyttää optimistic completion boundia tai pientä rolloutia: “kuinka hyvä tästä buildista voi parhaimmillaan tulla jäljellä olevilla N pisteellä?”

3. **Global optimum voi pudota ennen DP:tä.** DP on exact vasta sen jälkeen, kun bounded candidate graph on rakennettu. Jos aidosti paras path tarvitsee levelillä buildin, joka ei ole independent top-K eikä continuity trailin child, DP ei koskaan näe sitä. Luonteva seuraava askel olisi DP-aware candidate generation: säilytä nodeja myös niiden future reachability/value-to-go:n perusteella, ei vain local scorella.

4. **Cooldown marginal approximation vaikuttaa ehkä turhan aggressiiviselta optimoinnilta.** Aktiivisia decision-cooldowneja on käytännössä korkeintaan Fire Blast, Nova ja Blink eli `k <= 3`. Full joint table olisi korkeintaan 8 statea, kun marginal käyttää enintään 4. Olisi hyvin testattavissa, maksaisiko production `joint` vain ~2x scorer-workin mutta poistaisi kokonaisen approximation-luokan. Ainakin finalistit voisi joint-rescorettaa ennen DP:tä.

5. **Smooth kill boundaryn sigma tulee pääasiassa primary direct damagesta.** Mixed Fire, DoT, Fire Blast, Ignite, root-dependent action count jne. eivät kaikki vaikuta variance-widthiin täydellisesti. Kaksi HP-pistettä on elegantti KISS-ratkaisu, mutta vielä principledimpi vaihtoehto voisi olla cast-count threshold probability: arvioidaan todennäköisyys tappaa N castilla vs N+1 castilla suoraan cumulative damage distributionista.

6. **Policy-family gating voi missata emergentin mixed policyn.** Fire-family laajenee pure Fireball/Scorch anchorien tai talent-point triggerin perusteella. On mahdollinen tapaus, jossa pure FBa ja pure Sc ovat >10 % jäljessä, mutta juuri `FBa/Sc` cadence on vahva Improved Scorchin/projectile timingin takia. Halpa mixed-Fire anchor Stage 1:een olisi melkein ilmainen vakuutus tätä vastaan. Sama ajatus voi koskea yhtä control-Frost anchoria.

7. **MC validation on edelleen pääosin fixed-N replay, ei automaattinen confidence race.** Repossa on `stochastic_race.py`, mutta normaali `run-both` ei tällä hetkellä näytä käyttävän adaptive 100→200→400→… elimination-racea lopullisena authority-loopina. Tämä on ehkä selkein seuraava iso quality improvement, koska aiemmin nähtiin, että 100-mob winner kärsii voimakkaasta winner’s cursesta. Fast + native MC finalist union pitäisi syöttää samaan adaptive paired confidence raceen.

8. **MC:n RNG ei ole aidosti common-random-numbers candidatejen välillä.** Sama seed auttaa, mutta eri policy/build voi kuluttaa RNG-streamiä eri määrän ja synkronia katoaa. Counter-based/event-keyed RNG voisi tehdä talent A/B -vertailuista aidosti paired: “mob #17, spell #4 hit roll” olisi sama satunnaisluku molemmille buildeille. Se voisi pienentää MC searchin delta-varianssia rajusti ilman lisämobeja.

9. **Fast julkaisee productionissa vain yhden water-moden kerrallaan, mutta MC defaulttaa `water-mode=both`.** Nykyinen `run-both` ajaa Fastin default `buy_water` -konfiguraatiolla ja MC vuorottelee buy/conjured-trackeja. Buy-water saa siis suorat Fast proposalit, conjured-water ei vastaavaa omaa analytic proposal settiä. Jos molemmat water-trackit ovat oikeasti kiinnostavia, Fast pitäisi ajaa kerran per water mode tai publishata molemmat bridgeen.

10. **`arcane_filler` on mallinnusabstraktio, ei oikea talent.** Se ratkaisee tier-gatingin halvasti, mutta tekee build-spaceen keinotekoisen dimension ja UI:sta hämäävän. Pitkällä aikavälillä olisi siistimpää mallintaa oikeat utility/filler-talentsit erikseen, vaikka niiden combat value olisi 0, jolloin legality ja talent-plan olisivat suoraan pelissä toteutettavia.

---

# 21. Mitä tekisin seuraavaksi?

Jos tarkoitus ei ole enää lisätä featureita vaan nostaa optimizerin luotettavuutta, kiinnostavin järjestys olisi:

```text
A. korjaa / validoi L+1/L+2 XP-weight mismatch
B. joint cooldown rescore Fast-finalisteille
C. lisää mixed-Fire anchor policy gatingiin
D. tee Fast candidate generationille future-potential / rollout -koe
E. kytke Fast + MC finalist union adaptive confidence raceen
F. vasta tämän jälkeen hienosäädä beam widthiä tai uusia search-heuristiikkoja
```

Näistä A on mahdollinen objective-bugi, B ja C ovat halpoja approximation-kovennuksia, D hyökkää Fastin suurimpaan rakenteelliseen heikkouteen ja E tekee MC:stä oikeasti sen stochastic authorityn, joksi arkkitehtuuri on tarkoitettu.

---

## 22. Yhden lauseen mental model

**Fast rakentaa nopeasti pienen mutta lupaavan legal talent-path graphin deterministic expectation-mallilla; exact DP löytää sen graphin parhaan 0/1/2-respec-polun; MC ottaa nämä polut omien stochastic kandidaattiensa sekaan ja mittaa, mikä niistä oikeasti kestää RNG:n.**

---

# v0.10 ruleset/class architecture

The simulator now resolves mechanics from three dependency layers:

```text
src/shared/
    ↑
src/rulesets/<ruleset>/shared/
    ↑
src/rulesets/<ruleset>/classes/<class>/
```

Dependencies may only point upward in that diagram: generic shared code must not know that Forever or Mage exists; ruleset-shared code must not import a class backend; class backends may compose both lower layers. `tests/test_architecture_boundaries.py` enforces these rules.

Runtime selection is explicit:

```text
--ruleset classic|forever
--class mage|paladin|druid
```

`src/game_context.py` owns selection and state namespacing. `src/engine_registry.py` maps the selected pair to an engine and exposes a lazy proxy so spawned workers resolve the same engine from inherited environment state.

Classic Mage is a deliberate migration exception in v0.10.x. Its physical implementation remains at `src/classic_mage_leveling_optimizer_v10.py` byte-identical to v0.9.5 because the legacy module identity and source fingerprint are compatibility inputs for persisted optimizer state. `src/rulesets/classic/classes/mage/` is therefore an ownership facade until a later explicit state/cache migration.

Forever class backends live under `src/rulesets/forever/classes/`. Shared Forever beta metadata belongs under `src/rulesets/forever/shared/`; mechanics that are genuinely ruleset-independent belong under `src/shared/`.

For experimental class packages the preferred internal ownership split is `profile.py` (capabilities/provenance/selection), `talents.py` (tree data and legality), `spells.py` (rank/availability data), `mechanics.py` (scoring/event mechanics), and a thin `engine.py` compatibility facade for the registry. Druid uses this core shape; Paladin extends it in v0.10.2 with `gear.py`, `policy.py`, and `survival.py` because pull-size/weapon-setup/survival are part of the leveling objective rather than presentation-only metadata. Mage remains a larger engine module until a behavior-neutral split can be protected by stronger parity fixtures.

The capability contract is intentionally asymmetric in this first release. Classic Mage remains full Fast+MC; Forever Mage reuses the mature Mage pipeline; Forever Paladin and Druid expose experimental solo-leveling Fast scorers and reject MC validation until their event-simulation backends satisfy the same replay/determinism contract.

### Experimental pack-policy search (Forever Paladin v0.10.2)

Paladin Fast scoring is a strategic expected-value search, not an action-permutation solver.  The inner scorer selects a small combination of pull size, representative gear setup, aura and priority/survival policy, then evaluates sustainable mobs/hour including combat, recovery and pull overhead.  Survival uses an expected-damage plus sigma envelope so the optimizer cannot repeatedly rely on a razor-thin expected HP outcome.

Experimental continuity retention preserves deep-tree commitment corridors before current-level and cumulative family leaders.  This is required for discontinuous tier unlocks: a route may be locally worse for several levels and become best only when the next talent row opens.
## v0.10.3 experimental class decision-output rule

Experimental leveling classes may expose a stable representative gear curve, but gear is not a combinatorial search dimension. For Forever Paladin, each visible per-level candidate carries the selected normal gear style, its concrete stat snapshot, pull size, sustainable rate and gameplay-aware marginal stat weights. A completed run additionally writes `level_decisions.csv`.

Stat weights have two interpretations: native-unit local derivatives and a 10%-of-current-normal-curve sensitivity used for practical stat-mix guidance. The latter is deliberately not called item-budget normalization because the Forever 69893 client exposes stat budget shares but not the server-side flat amount conversion.

## v0.11.24 shared analytical stat-gradient contract

Stat weighting is an optimizer concern, not a Mage feature. `src/v2/stat_weight_model.py` owns a class-agnostic contract: a class backend may expose `analytic_stat_gradient(level, talents, ...)`, returning the gradient of the continuous local objective surrogate in native stat units. The shared layer normalizes that gradient for the listener and CSV outputs. Backends that have not yet supplied a differentiable surrogate may temporarily expose their older marginal finite-difference diagnostics; callers no longer branch on class names.

The analytical gradient is deliberately a **surrogate gradient**, while the discrete/event scorer remains the validation authority. This separation is useful because the real leveling objective contains cast-count, policy, proc and gear breakpoints. A finite +/- stat probe can therefore report a zero local slope merely because neither probe crosses a discrete boundary. The continuous surrogate asks the actual gearing question -- which direction improves expected damage/resource/recovery performance locally -- and its predicted direction can then be checked against the discrete simulator over realistic item-sized changes.

Forever Mage is the first backend on this contract. Its local gradient includes closed-form Intellect -> spell-crit sensitivity, audited rank-specific Spell Power coefficients, and continuous Spirit recovery elasticity, plus a bounded mana-capacity term when the selected route actually spends time waiting for mana. The contract is intentionally generic so Paladin/Druid analytical surrogates can plug into the same path without changing runner, listener, or artifact schemas.


## v0.10.4 Forever Paladin mechanics-hardening layer

Forever Paladin now consumes a ruleset-level ordinary-world-mob fixture from
`src/rulesets/forever/shared/mobs.py`.  The fixture keeps the prior average raw
DPS assumption but decomposes melee attackers into fast/light, normal and
slow/heavy swing families and applies the existing 50/50 player+1/player+2
level objective.  This lets block, Redoubt, Ret Aura, absorbs and pushback see
attack frequency without inventing a Forever-specific mob damage multiplier.

The Paladin Fast model also treats Judgement as Seal-preserving, uses a 3-second
Shield Specialization ICD expected-renewal rate, and only grants Improved Seal
of Fury mana when the current absorb is expected to be fully consumed before
replacement.  Seal of Fury replacement/stacking behavior is still explicitly
provisional.

Experimental output distinguishes talent ownership from play style:
`talent_family` describes where talent points are concentrated, while
`combat_profile` describes the currently selected action/gear profile.  These
must not be conflated; a Protection-family allocation may rationally use a 2H
profile at some levels.

## v0.10.5: resource-continuous experimental policies and cross-class contract

Forever Paladin Fast now treats HP and mana as repeatable pack-cycle state. Survival healing is integer-cast work with explicit action/mana cost; resource pressure selects among canonical ability cadences rather than arbitrary continuous duty factors or spell-order permutation search.

Cross-class comparison lives in `src/v2/class_comparison.py`. It consumes already-produced per-class snapshots and emits common-level JSON/CSV rows. Raw throughput is always accompanied by `MODEL_FIDELITY`; the comparison layer does not turn heterogeneous backends into a hidden confidence score or declared winner.


## v0.10.6 deterministic combat timeline layer

`src/shared/combat/events.py` now provides a ruleset-agnostic stable event queue. Forever Paladin uses it in `event_replay.py` as a diagnostic validator for explicit GCD/cooldown/auto-swing/mana/mob-swing timing. The validator is intentionally below optimizer authority until heal/emergency and shield-resource timelines are complete; this preserves the Fast -> deterministic replay -> MC fidelity ladder from `PROJECT_NORTH_STAR.md`.

## v0.11.0 bounded decision layer

The optimizer now emits a separate bounded decision frontier after experimental
search.  This layer retains enough machine-readable path state to answer
milestone endpoint and constraint/regret questions without turning the browser
into an optimizer or serializing the exhaustive search graph.

```text
experimental search
  -> decision_frontier.json
      -> endpoint_paths.json / spec_regret.json
      -> dual_spec.json
      -> optional spec_matrix.json
      -> read-only /api/decisions and /decisions
```

Named and ad-hoc constraints operate only on preserved candidates.  If the
corridor is absent, the result is explicitly unresolved and requires a future
opt-in constrained rerun.  This boundary is important: HTTP remains bounded
read/reshape work, and a missing beam route never becomes a fabricated optimum.

## v0.11.1 decision workbench and configurable dual spec

Dual-spec unlock is runtime data (`--dual-spec-unlock-level`), not an
architecture constant.  The bounded joint solver chooses a primary preserved
path before unlock and may choose either of two distinct preserved paths at
every level after unlock.  Its output records the chosen slot and compressed
level phases, so rank-driven Fire/Frost-style crossovers can be represented
without pretending the whole leveling range has one winning spec.

Endpoint analysis also emits a compact named-route regret point at every
available level and compresses each milestone path into player-facing change
events.  `spec_matrix` schema v2 stores multiple route/target matrices per
class and caches identical `(level, talent ranks)` probes during batch runs.
The `/decisions` workbench draws regret and stat trends, exposes route change
points, and submits bounded custom-constraint queries.  An unresolved query
returns copyable wide-rerun and repeat-query commands; HTTP still never starts
optimization.

## v0.11.25 Paladin analytical backend + listener timing contract

The optimizer-level stat-weight API remains class agnostic. Forever Paladin now implements `analytic_stat_gradient()` in its own mechanics backend, returning the same objective-gradient contract as Mage. The shared layer normalizes derivatives; it contains no Paladin branches.

Paladin's smooth local surrogate freezes the selected talents, weapon style, pull size, priority policy, aura and canonical mana plan. Closed-form damage derivatives cover Strength/AP, weapon DPS and Holy Spell Power; Holy Strike/Judgement terms are scaled by the selected cadence. Intellect contributes through spell crit and a bounded mana-capacity elasticity; Spirit contributes through smooth recovery elasticity. Deterministic pack/event scoring remains the route authority.

Paladin gear is still represented by a continuous normal-leveling field rather than a combinatorial item inventory. Current real Forever items calibrate the low-level weapon/shield frontier. Listener output decomposes the exact aggregate gear used by combat into audited literal rows plus explicitly modeled remainder slots; summed slot stats are regression-tested against the aggregate.

The listener timing contract is now explicit for experimental classes: `seconds_per_mob`, `kill_seconds_per_mob`, `recovery_seconds_per_mob`, and `travel_seconds_per_mob`. Travel is rendered separately when non-zero, so displayed components reconcile to the total.

Raw analytical weights use native stat units. Equal-item-budget projection is deliberately a separate future layer because +1 weapon DPS, +1 Strength, +1 Intellect and +1 Spell Power do not consume equal itemization budget.

## v0.11.26: native gradients vs empirical equal-item-budget values

The optimizer now keeps two deliberately separate stat-value layers. The analytical class backend returns native-unit partial derivatives of the objective. The shared stat-weight layer may then project those derivatives onto an equal-item-budget axis using a backend-supplied exchange model. For Forever, the first exchange model is data-driven from designed role-peer crafted items at the same profession / slot / item level / required level. The observed max-min stat spans are level-normalized and pooled robustly. This is an empirical approximation; the raw gradient remains authoritative for local calculus and for scoring literal item vectors.

Literal gear selection does **not** multiply an item by budget-normalized weights. When comparing two real sampled items, their actual stat vectors are dotted directly into the native analytical gradient. Budget normalization is only needed to answer the counterfactual player question "if a comparable itemization chunk were spent on stat A rather than stat B, which direction is worth more?"

Paladin's sampled body-item layer is level-local. Each level may choose a new representative sampled role-peer item per comparable anchored slot; no inventory state is propagated from L(n) to L(n+1). The fully searched continuous baseline remains a candidate, and the analytical reroll is validated in a local gameplay neighborhood. This keeps the gear layer cheap while avoiding stale-item lock-in.

## Listener gear audit contract (v0.11.27)
Continuous/modelled gear is permitted internally, but presentation must expose its numeric stat vector. Paladin gear snapshots therefore publish both `combat_totals` (the aggregate consumed by combat) and `slot_totals` (the sum of displayed slot rows), plus a reconciliation delta. A listener surface must not reduce a modeled slot to provenance-only text.

## v0.11.28 — same-slot continuous gear field

A continuous gear field may interpolate or cautiously extrapolate sparse real-item samples, but a modeled slot must be anchored by samples of that same slot. Cross-slot aggregate remainder redistribution is forbidden. The shared `project_slot_from_samples()` primitive implements exact-anchor, interpolation, bounded back-extrapolation, and growth extrapolation while preserving explicit provenance. Missing same-slot evidence remains missing rather than being silently synthesized.

## v0.11.48.0 — Optimizer Service P1 durable control plane

The platform track starts by separating durable **control state** from optimizer execution. `src/service/` owns an immutable `JobRequest`, SQLite/WAL `QueueStore`, job event history and queue lifecycle controls. The store survives browser/CLI/process restarts and is intended to become the single authority consumed by the later scheduler and HTTP API.

P1 deliberately does not launch Fast/MC work. The next slice adds a daemon/scheduler that leases one queued job at a time and creates immutable `state/runs/<job-id>/<attempt-id>/` output roots. Canonical listener publication remains unchanged until the atomic publication slice.

## v0.11.48.4 — Optimizer Service P3b resumable immutable attempts

A service resume never reopens or mutates an old attempt directory. The scheduler selects only a strict `resume`-compatible checkpoint (same ruleset/class/endpoint, level scope, objective, source snapshot, engine semantic hash, policy-space version, config and validation modes), verifies its SHA-256, and copies it into the same relative state location under a **new** attempt root. `seed_only` artifacts are explicitly not numeric resume state.

For MC/master-optimizer jobs, the minimal controller state (`state/runtime/controller.json`) and user config are staged with the checkpoint so the new process continues the exact in-flight experiment/epoch instead of constructing a new one. Checkpoint references are path-portable: local runs may keep project-relative references, while service attempt roots outside the repository use absolute references.

The remaining P3 boundary is publication, not execution: attempts still write only below their immutable run root. P3c will atomically promote a completed, validated result to canonical listener state while preserving the previous last-good publication until the replacement is fully ready.


## v0.11.48.5 — Optimizer Service P3c atomic canonical publication

Completed service attempts remain immutable. Publication creates a durable manifest that points at the completed attempt's `state/` root, then commits that generation by one atomic replacement of `state/service/publication_current.json`. Validation happens before the pointer swap, so a missing/incomplete result cannot displace the previous last-good generation.

Publications form an overlay chain instead of copying or mutating the prior state tree. Listener reads resolve newest-to-oldest publication roots and finally fall back to the historical project `state/` layout. This lets a Mage-only publish update Mage artifacts without deleting previously published Paladin/Druid artifacts, while avoiding full-state copies for large MC attempts. The Decisions listener and constrained-route reads consume the publication resolver. P4 will put queue/status/publication reads behind the HTTP service API and make browser/CLI clients thin.


## v0.11.48.6 — Optimizer Service P4a HTTP control/read API + replayable event stream

`src.service.http_api` exposes the durable queue/store through a thin localhost HTTP API. HTTP handlers only mutate/read `QueueStore`; they never launch optimizer work. Queue/job controls, attempts, checkpoints and publication history are available as JSON. Global job events are cursor-addressable by SQLite `seq`, and `/api/v1/events/stream` exposes the same ordered stream as SSE with `Last-Event-ID`/`after` replay semantics, so a UI can reconnect without rebuilding state from process-local memory.

P4a intentionally preserves direct CLI compatibility. P4b will make CLI/listener control/status clients consume this API rather than duplicating control-plane access.

## v0.11.48.6 — Optimizer Service P4a HTTP control/read API

The service now exposes the durable QueueStore through a compute-free localhost HTTP API. `src/service/api.py` owns only control-plane and read operations: job enqueue/list/get, queue controls, attempts, checkpoints, publication history, and job events. No HTTP handler imports or executes optimizer scoring/search code.

Job events are available both as bounded JSON reads and as a bounded Server-Sent Events stream (`/v1/jobs/<id>/events/stream?after=<seq>&timeout=<seconds>`). The stream polls only SQLite event history and caps each request at 30 seconds, so browser/CLI clients can follow durable state without owning optimizer lifetime.

P4 is split deliberately: P4a establishes the stable API contract; P4b migrates CLI and listener control/status reads to a shared HTTP client while retaining an explicit local/direct mode for recovery and tests. Optimizer execution remains exclusively in the daemon/scheduler.

## v0.11.48.66 — Evaluation becomes a real kernel contract

The platform contract is no longer only a dataclass declaration. Both mature Mage
publication and experimental-class publication pass through the shared `Evaluation`
shape, and timing uses one non-overlapping semantic:

`kill/combat -> recovery -> between-pull travel`

Class code owns the amount of combat/recovery and may expose a movement-speed
multiplier; the optimizer/publisher owns the timing buckets and their consistency.
A published candidate whose total does not equal those buckets is now machine-visible
as an inconsistent result rather than silently rendered as if the fields came from
one authority.

The next platform increment should move candidate generation/evaluation orchestration
behind `ClassModel` so Mage/Hunter/Druid/Paladin all feed the same per-level frontier
builder before the already-generic route DP.


## v0.11.48.67 — generic per-level search kernel

`src.v2.search_kernel.search_level()` is now the shared per-level orchestration
primitive.  It treats builds as opaque values and asks `ClassModel` to expand
legal children, identify transitions and evaluate candidates.  The kernel owns
deterministic first-parent-wins deduplication, candidate parallelism, weighted
level cost and the generic policy/evaluate/stat-weight/gear fixed-point sequence.

New class plugins should expose those operations independently.  The temporary
`EngineClassModel` compatibility adapter declares its candidate optimization
bundled because existing Hunter/Druid/Paladin/Warrior score calls still contain
some policy/gear fixed-point work internally; this prevents double optimization
while their implementations are peeled behind explicit hooks.

The non-Mage Forever continuity runner now calls the generic kernel instead of
implementing its own talent expansion + worker scoring loop.  Mage still uses
its mature `local_search` path and is the next orchestration migration.  The
route DP remains a later consumer of retained per-level frontiers; it does not
participate in class mechanics or per-level candidate scoring.


## v0.11.48.70 Forever execution boundary

Forever runner selection is now capability-driven rather than class-name-driven. `runner.py` dispatches by ruleset to `forever_runner`; the active `ClassModel` declares `runner_strategy()` and owns any class-specific post-search adjudication hooks. Hunter/Druid/Paladin use explicit bundled compatibility adapters while their scorer internals are peeled apart incrementally.

Decision publication is shared across both current search strategies: canonical retained `LevelFrontier` objects feed `solve_routes()` once, producing `DecisionResult`, and `decision_pipeline.publish_decisions()` writes endpoint/regret artifacts. A diagnostic/presentation frontier must never become a second route authority.

## v0.11.48.71 — shared recovery + bounded fixed-point authority

Cross-class recovery has one ruleset-level sit authority: `solve_recovery()`. Class plugins provide deficits, passive regeneration and optional healing/consumable inputs; class-only serial actions such as pet revive, shapeshift transitions or Mage cooldown resources stay outside that primitive. Backends publish `recovery_solver_id` so fidelity audits can verify which authority produced the resource-recovery bucket.

The generic per-level fixed-point coordinator also owns max-iteration publication semantics. A non-converged discrete coordinate walk may propose a worse gear state on its final iteration; the published result is therefore the best objective state actually scored within the bounded walk, never the arbitrary terminal proposal.
