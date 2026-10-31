# PROJECT NORTH STAR — WoW leveling optimizer

This file is the persistent product intent for the project. Read it **before** the latest HANDOVER, BACKLOG, or release notes when continuing work in a new session.

Do not silently reinterpret these goals during implementation. If the user changes a goal, update this file explicitly and note the change in the next handover.

## Current checkpoint acceptance — 15 October 2026

**Authoritative acceptance process:** [`docs/validation/WF403_P1_P7_GATE_RED_GREEN_REFACTOR_CONTRACT.md`](docs/validation/WF403_P1_P7_GATE_RED_GREEN_REFACTOR_CONTRACT.md). The current goal is **148 checkpoints**, each with seven semantic gates P1–P7 (P7 compares the independently discovered legacy winner as an explicit new-runtime candidate). **Every gate must follow RED → GREEN → REFACTOR → post-refactor same-gate/cross-context recheck**; see the linked contract. This is a delivery method, not an eighth acceptance gate. Strict accepted remains **0/148** on the latest WF401-era evidence; historical two Druid acceptances await revalidation. Do not promote diagnostics or L0 source inventories to validated L2/global optima.

## Mission

Build a practical solo-leveling simulator/optimizer that answers **how to play and gear a character at each level to minimize real wall-clock leveling time**, not merely dummy DPS.

The simulator should eventually support multiple rulesets and classes while preserving trustworthy comparisons:

- rulesets: Classic Era and Forever
- classes in current Forever scope: **all nine** — Druid, Hunter, Mage, Paladin, Priest, Rogue, Shaman, Warlock, Warrior (every meaningful spec/profile, levels 1–60). The generic source registry now exposes nine bounded providers (.251), but Hunter/Paladin source mechanics and all-class talent/level coverage remain incomplete; registration is not DONE.
- CLI selection: `--ruleset ... --class ...`

The primary objective is sustainable leveling throughput under realistic combat, recovery, gear, and survival constraints.

## Core user stories

The persistent player questions are:

1. What is the best current spec/build at each level?
2. What is the best no-respec path to level 20, 30, 40, or 60?
3. At the configured dual-spec unlock level, which two paths are jointly optimal when switching is free level by level?
4. How much leveling time/throughput is lost when one spec, archetype, or explicit build is constrained?
5. What stat weights and rotation/policy does each simulated route want at each level?

Route identity is the destination or explicit constraint, not whichever tree
temporarily holds the most points.  A Ret/Prot endpoint route may rationally
share early Holy points.

The browser listener is a first-class output surface.  Decision artifacts must
remain available as bounded JSON/CSV and visually under `/decisions`; HTTP
requests must never execute optimization.

### 1. Per-level decisions

As a player, at each level I want to know:

- the best legal talent allocation / next talent choice
- the best combat profile for that build
- the best realistic gear archetype for that level
- the assumed gear stats
- the preferred pull size
- the priority policy / survival policy
- sustainable mobs/hour (and eventually normalized XP/hour where appropriate)
- marginal stat weights
- practical stat-mix guidance for choosing gear in game

These are first-class outputs, not debug-only diagnostics.

### 2. Tanky leveling must be evaluated on its natural playstyle

Do **not** judge Protection Paladin or Bear only by single-target kill speed.

The optimizer must be able to discover that a build is best played by pulling multiple mobs, using mitigation and recovery tools, then recovering and repeating.

Examples of behavior the model must eventually represent:

- Paladin: Seal/Judgement/Holy Strike/melee weaving, AoE when available, HoJ/BoP/Bubble when behind, discrete heals, then return to offense
- Bear: multi-mob survival/resource value, form-specific combat, heal/recover between packs where appropriate

The metric is sustainable wall-clock throughput, not raw DPS.

### 3. Search strategy, not GCD permutation sludge

Fast/smooth search should optimize **priority policies and thresholds**, not enumerate every trivial spell ordering such as `Consecration -> Judgement -> Holy Strike` versus `Judgement -> Consecration -> Holy Strike` at every decision point.

Branch on strategically meaningful choices:

- pull size
- gear setup
- mana reserve
- heal threshold / heal target
- when to spend HoJ / BoP / Bubble or equivalent survival tools
- whether an expensive AoE/resource action is worth using
- a small set of meaningful priority variants

Use canonical ordering and dominance/pruning for insignificant micro-permutations.

### 4. Survival and recovery are part of the objective

A policy that barely kills a pack but requires excessive recovery is not automatically optimal.

Track cycle-consistent state across pulls:

- HP
- mana / rage / energy where relevant
- cooldowns when continuity matters
- discrete healing actions and their cast time/cost
- eating/drinking/bandaging/racial recovery when modeled

A new pull must begin from the state produced by the previous pull + recovery. No magical full-HP/full-mana reset unless the recovery time explicitly pays for it.

Fast/smooth may use expected-value mechanics; final validation can use a discrete/stochastic event backend where supported.

### 5. Gear should be useful, not combinatorial

Do **not** build an exhaustive loot/inventory optimizer unless explicitly needed later.

Use a realistic **normal attainable gear curve** per meaningful gear type, derived/calibrated from ordinary quest, dungeon, crafted, and world-drop gear.

Current Paladin examples:

- `2h_normal`
- `1h_shield_normal`

Relevant stats include, when applicable:

- STR
- AGI
- STA
- INT
- SPI
- Spell Damage / Spell Power
- Healing
- armor
- weapon DPS
- weapon speed
- shield armor
- block value

Stat weights should guide the stat mix of the normal curve. A couple of explicit calibration iterations are preferable to adding item-choice dimensions to the optimizer.

Raw `+1 stat` weights are not automatically equal item-budget weights. If the exact server-side item-budget conversion is unknown, say so; expose local sensitivities (for example +10% of the normal-curve amount) instead of inventing precision.

### 6. Build and playstyle are separate decisions

A talent family does not force a gear/combat profile.

Examples:

- a Protection-heavy Paladin may still prefer 2H at a particular level
- a Ret-heavy Paladin may prefer 2 mobs rather than 1

Output should distinguish at least:

- `talent_family`
- `combat_profile`
- gear setup
- pull size
- policy

Do not hard-code `Protection == shield` or equivalent class assumptions.

### 7. Cross-class comparison is a product goal

The simulator should be able to compare Mage vs Paladin vs Druid at the same level under the same normalized leveling assumptions.

Cross-class reports should show at least:

- sustainable throughput
- pull size
- recovery burden
- survival margin
- gear assumptions
- stat guidance
- model fidelity / capability flags

Do not present a cross-class ranking as equally trustworthy when one class has a mature event model and another is still an experimental smooth proxy. Fidelity must be visible next to the result.

### 8. Ruleset/class architecture must remain clean

Desired dependency direction:

```text
shared/
  <- rulesets/<ruleset>/shared/
       <- rulesets/<ruleset>/classes/<class>/
```

Generic shared code must not contain `if ruleset == forever` style knowledge.

Ruleset-specific but class-independent mechanics belong under the ruleset's `shared/` package. Class-specific talents, spells, mechanics and profile data belong under that ruleset/class package.

## Classic Era parity freeze

Until the refactor is explicitly declared **done done**, Classic Era Mage behavior is parity-frozen.

- Do not opportunistically fix pre-existing Classic mechanics bugs during structural refactoring.
- Record discovered pre-existing bugs in BACKLOG instead.
- Bugs introduced by the refactor itself must be fixed immediately.
- Preserve state/cache compatibility where promised.
- The canonical Classic Mage engine SHA is a release gate while this freeze is active.

Current expected canonical SHA-256:

`97ec2a664c5c1cb167d6f3a62b0524732d2e2793678a749411cc3ad22a01b5a4`

## Modeling philosophy

Use layers of fidelity deliberately:

1. **Fast / smooth deterministic model** for broad build/talent/policy exploration.
2. **Discrete action/event replay** for mechanics where ordering, survival windows and resource peaks matter.
3. **Monte Carlo / stochastic validation** for finalists when the class backend supports replay correctly.

Do not label an expected-value proxy as MC-validated. Unsupported backends must fail clearly rather than silently producing authoritative-looking output.

## Data/provenance rules

- Prefer one build-scoped dataset per ruleset snapshot.
- If data comes from mixed beta builds, expose that in machine-readable provenance and docs.
- Unknown mechanics should be explicit approximations/fallbacks, not silent guesses.
- Avoid false precision, especially with beta server-side values not present in client data.
- A verified beta level cap is **confidence/provenance metadata, not an architecture gate**. If the model has an explicit fallback/approximation above the verified cap, L40/L60 planning may run there, but outputs must visibly label the unverified range as provisional. Never replace a requested L40/L60 answer with a hard block merely because verification currently ends earlier.

## Current class direction

### Forever Mage

Use the mature Mage simulation stack where applicable, with Forever-specific talent/spell data isolated under the Forever ruleset. Continue adding new Forever spell state/mechanics without modifying the parity-frozen Classic engine.

### Forever Paladin

Current main development focus.

North-star model:

- multi-pull envelope
- realistic normal gear curves
- priority policy rather than fixed rotation
- survival controller
- cycle-consistent HP + mana
- discrete heals/actions
- Seal/Judgement/Holy Strike/melee mechanics
- defensive tools used when falling behind
- eventually deterministic event replay, then MC validation

### Forever Druid

Port the same concepts once the Paladin abstraction is sound:

- normal gear curve
- pull envelope
- Cat/Bear-specific resource/action model
- survival/recovery
- per-level stat guidance
- eventual event validation

Do not force Druid into Paladin-specific mechanics; reuse only genuinely generic abstractions.

## Output contract / north-star report

A completed per-level decision report should be able to answer, in human terms:

> At level N, what talents should I have, what kind of gear/stats should I favor, how many mobs should I usually pull, how should I prioritize actions and survival tools, how fast is that sustainable strategy, and what changes at the next level?

For cross-class reports:

> At level N, under comparable assumptions, how do Mage, Paladin and Druid differ in sustainable leveling throughput and playstyle, and how trustworthy is each estimate?

## Anti-goals

Unless the user explicitly changes scope, avoid:

- exhaustive per-item inventory/loot-route optimization
- brute-force GCD permutation search
- hiding model uncertainty behind precise-looking numbers
- coupling generic shared mechanics to a specific ruleset/class
- changing Classic Era behavior during the parity freeze to make Forever work
- optimizing benchmark/runtime at the expense of semantic correctness

## Definition of done for a checkpoint

Before sharing a versioned checkpoint ZIP:

- normal tests green from the exact staging bytes
- applicable release/MC gates green
- Classic parity SHA unchanged while freeze is active
- relevant class smoke(s) complete
- runtime state/cache artifacts removed from the ZIP
- HANDOVER updated with exact current state, known approximations, results and next work
- this North Star remains present in the archive

## Continuation protocol

When starting a new session or after context loss:

1. Read `PROJECT_NORTH_STAR.md` first.
2. Read the newest `HANDOVER_v*.md`.
3. Read `BACKLOG.md` for known-but-deferred issues.
4. Check `VERSION`, current worktree/staging name, and latest release notes.
5. Re-run the smallest relevant baseline/parity gate before modifying code.
6. Continue the highest-value next work from the handover **without redefining the product goal from implementation details**.
7. If the user's intent changes, update this file explicitly.

Work work.

## Source-audit rule (v0.11.5)

For Forever class data, prefer current Wowhead Forever spell pages for explicit public spell/rank facts. Keep beta-client fixtures with provenance, but do not silently mix contradictory rows. A verified data row is not the same as an implemented combat mechanic: listener/model fidelity must say when a talent/spell/proc is known but not yet executed by the scoring kernel. Unknown values stay unknown; do not borrow Classic/TBC values merely to complete a table.

## Data-driven Forever ruleset contract (v0.11.42)

Forever should converge toward **source-defined data + a generic rules interpreter**, not a growing collection of class/name-specific numeric rules.

- Exact Wowhead Forever spell/talent/helper IDs are the durable external identity when confidently resolved.
- Client-derived public exports may supply roster/tree/icon/spellbook discovery and build-scoped facts, but every provider keeps separate provenance; mixed builds must never be collapsed into a fake single build.
- Runtime consumes a pinned, fingerprinted, offline fixture. Network refresh is an explicit build/audit operation only.
- Generic source-exposed effects should be interpreted by shared mechanics code once audited. Class code owns policy/state that is genuinely class-specific, not duplicate copies of source numbers.
- Hidden/helper entities, server-side scripts and ambiguous mechanics are explicit relations/overrides/unresolved records. Never infer a convenient behavior merely because an entity name matches.
- Coverage must distinguish exact-ID resolution, modeled behavior, and explicit unresolved status. “Known to exist” is not “implemented”, and “explicitly unresolved” is not a zero-valued mechanic.
- New classes should primarily require source data plus thin class policy/state adapters; shared engine branches for named classes are a migration smell.

The long-term acceptance condition is traceability: a player-facing build/action/talent decision can identify which pinned source entities and which generic/override mechanics produced it.

## v0.11.7 Druid rotation milestone

Druid solo-leveling decisions must be driven by ranked, resource-aware rotations rather than a synthetic class DPS curve.  Cat now models Energy/Combo Points and normal-mob finisher choice; Balance now models DoT maintenance, ranked fillers, Eclipse alternation and Nature's Grace.  Remaining unverified mechanics must stay labeled instead of being guessed from another ruleset.

## Listener completion / visual correctness gate

The browser listener is a product surface, not merely an API demo. For listener work, passing unit tests is necessary but not sufficient.

- A selected-level view must visibly render the real available talent, scorer, timing, rotation, stat-weight and gear data from the canonical decision artifacts.
- Contradictory totals, placeholder-only panels, or blanks that hide available data are release blockers for the affected listener feature.
- Visual/design references define structure and presentation only; they are never a license to invent stats, items, talents, IDs or icons.
- Real talent/spell/item icons require auditable provenance. Missing provenance must degrade honestly to text rather than guessed art.
- Material listener changes require a rendered `/decisions` smoke in addition to automated tests.

See `PROJECT_STATE.md` for the current acceptance checklist and known defects.
