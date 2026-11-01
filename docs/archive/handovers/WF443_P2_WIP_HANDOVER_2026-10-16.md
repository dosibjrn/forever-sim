# WF443 Druid L30 P2 — merged two WF442 branches, 2026-10-16

## Baseline / merge
- Apply **this single WF443 source delta onto WF441**. It **supersedes BOTH** WF442 parallel overlays. DO NOT layer WF442 first; files overlap and semantic branches differed.
- Rebased merged code from `/mnt/data/wf441work`, hash-comparing Library `WF442_P2_GENERIC_HEAL_CRIT_AVOIDANCE_SOURCE_COMPILER_WIP_ON_WF441.zip` against independently working WF442 source+SQLite. Parallel generic code and both new rank executors are included.
- P2 **RED**, accepted checkpoints **0/148**. PROCESS v2 and OVERALL v5 SHA256 unchanged: `f605840ba8321cf0494a2fe813a596fd873a800e1c4f9a05b65bf69281345a5d` and `841162fa6817c8c8b20e2804c5e77f9589d167765ad537bdad6daa508e1e5e5a`.

## Actual improvement
- 129/129 structurally reachable Druid L30 (26pt) rank executors, all rank witness build applications pass.
- Natural Reaction R1: sourced +Dodge and Bear-only incoming physical dodge -> Rage expected-value proc. No rage on magic, caster, or hit-profile double avoidance. Dual source build remains unverified.
- Improved Regrowth R1: +10 percentage points Regrowth direct heal crit; periodic HoT unchanged. Heal critical multiplier 1.5 is **separately sourced from Classic Era** via `https://www.warcrafttavern.com/wow-classic/guides/mana-management-optimization/` and flagged as NOT verified for Forever 70338; compiler refuses missing multiplier source.
- Parallel WF442 generic compiler integrated: `_compile_clause` for `critical_chance_bonus_pct`, `dodge_bonus_pct`, `avoidance_resource_proc_chance_pct`; generic IR resource proc and direct HealEffect critical handler, plus corresponding TDD. Both event projections coexist; no double counting by rule.
- Fixed old test assumptions: L20 base crit/dodge are not zero, Natural Instinct source explicitly says melee **abilities**, not auto attack. This fixes historical failures without changing source correctness.

## Validation
- P2 mechanisms, parent compatibility and both merged branches: **84/84 PASS**, `/mnt/data/WF443_MERGED_P2_REGRESSIONS.log`.
- Independent fixed-policy 100 mob **100/100** for Regrowth and Bear; `/mnt/data/WF443_100MOB_EVIDENCE.json`. Neither is a search optimum.
- SQL data ingested from pristine WF441, same source JSON SHA `ca8c45fec9fddf9028f5f5f0114385c98f401ffd4b66d6f09485c8e2159da09c` on replay. SQL integrity OK. P2 `--strict` exit **1** RED.
- Full legacy suite not green and longer optimizer run interrupted after failures. No accepted P2 yet.

## CRITICAL NEXT (one checkpoint, P2 until truly GREEN)
1. Resolve source version bridge 70338 vs 70374/70425 for rank mechanics and **Improved Regrowth 3/3 prerequisite**; Classic heal crit multiplier source bridge remains partial. NEVER pretend imported later facts are verified 70338.
2. Remaining 14 partial executable ranks: especially correlated discrete crit/dodge resource procs, Feral Charge enemy cast interrupt + facing, Swiftmend multiple HoTs and snapshot behavior, Leader of the Pack group aura, Tranquility party heals and aggro, source action cost/cooldown bridges.
3. Runtime parity must be proven rank by rank, not by presence of modifiers. Static P2 audit `green=False` remains intentional until all semantic evidence is available. 0/148 scoreboard, no P3 yet.
4. For future P3–P7, preserve user optimizer contract: 30s fast Top-N joint talent-gear-stat-weight-rotation search with PNP breadth/depth control, 300s deeper version, 100mob finalists only.
