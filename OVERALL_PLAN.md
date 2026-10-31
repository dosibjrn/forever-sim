# WoW Forever — OVERALL PLAN v5 (APPROVED)

**Date:** 2026-10-15  
**Status:** **APPROVED, IMMUTABLE.** The user approved this exact product scope and DONE DONE definition on 2026-10-15 ("Je, W"). Historical v4.2 and the original v5 proposed text remain unmodified.  
**Purpose:** Define WHAT is built, the end-state and precisely when DONE DONE occurs. No gate implementation procedure or changeable milestone ordering belongs here; those live in PROCESS and milestone plans.

## Product goal

Build a generic, source-driven WoW Forever 1–60 solo leveling simulator/optimizer for all nine classes. Given class, level, legal constraints and a pinned Forever ruleset, automatically discover and explain the best **known executable** combination of talents, equipment, combat/rotation policy, pull strategy and paid recovery/survival. Optimize comparable **real elapsed time per mob/route**, not only DPS, arbitrary XP proxies, or a preset guide build.

A user must be able to inspect actual selected gear with item identities and scored alternatives; talent ranks and next talent; the actual legal actions/rotations and their measured score; stat weights; encounter, survival and recovery; and why the chosen configuration beat benchmark alternatives. The engine must be generic; game facts come from canonical pinned source data rather than class-specific hardcoded winner builds.

## Current first DONE DONE target — 148 certified checkpoints

**148/148 checkpoints independently accepted under the approved PROCESS's P1–P7 gates**:

- Nine classes × levels **20, 30, 40, 60** unrestricted = **36**.
- Druid **four** spec/profile constraints × four levels = **16**.
- Other eight classes **three** spec/profile constraints × four levels = **96**.
- **Total 36 + 16 + 96 = 148.**

Each accepted checkpoint includes a source-legal actual whole-build decision, real 100 consecutive-mob combat/recovery and comparable independent 30s/300s and old-optimizer challenger as required by PROCESS. No checkpoint is accepted on isolated action inventory, item metadata, unit-test green, unproven search candidate, or incompatible proxy benchmark. A checkpoint can be *diagnostic* without counting as DONE.

**Definition of first-phase DONE DONE:** exactly **148/148 accepted** in the machine-readable register with compatible current proof; 0 false-green entries. Final scorecard and reproducible artifacts published. This is the current working finish line; the historical 540 metric is not substituted for it.

## Broader product destination beyond the 148-checkpoint finish line

Eventually enable coherent outputs for **all nine classes × levels 1–60** (**540** class-level reports) and legal continuous 1–60 routes, including irrevocable talent choices, spell ranks, gear availability/acquisition, training/travel, cooldown and resource state across pulls, recovery and survival. Routes must be playable, not simple concatenations of independent per-level local winners. Explicit dual-spec/respec only under sourced rules. Track this separately from the 148/148 current checkpoint scoreboard; do not move the initial goalposts unilaterally.

## Immutable product constraints

1. No invented source facts, effect coefficients or talent spells; missing coverage clearly disclosed.
2. No class/spec winner presets or omitted legal action by unsupported-whitelist logic. The system searches source-derived alternatives and measures actual executable policies.
3. Optimize continuous actor and paid recovery/survival, with honest simulator fidelity/uncertainty.
4. Comparisons are on consistent character level, target/encounter, ruleset version, scenario and scorer; legacy references held out from search.
5. The final result must be inspectable and independently reproducible.
6. Completion is a counted validated *user-facing capability*, not release number, elapsed engineering hours, test count or source-scrape volume.

## Subordinate editable execution instruments

**MILESTONE PLAN:** decomposes the objective into the smallest number of outcome-sized verifiable milestones, orders the critical path, revises estimates and dependencies when evidence changes.

**MILESTONE IMPLEMENTATION PLAN:** chooses concrete implementation slices, reuse/refactor strategies, time budgets, validations, caching, automation and which action each W should perform. Optimize for **minimum total useful W cycles, model tokens and elapsed wall time**. Replan freely when a better path is supported, while preserving PROCESS and OVERALL PLAN verbatim.

A milestone report can be updated by agents. A sacred-process or overall-goal change **cannot** be smuggled through a milestone update. New Process or Overall Plan versions require the user's explicit request/approval; preserve this document as-is once approved.

## Current known planning state

As of the source records inspected 2026-10-15, strictly certified coverage was **0/148**, with earlier Druid L20/L30 results retained as diagnostic/previous-contract evidence rather than deleted. Those states are temporal bookkeeping, not permanent plan definitions. The current priority set by user is Druid L20 → Druid L30 → Mage L30; subsequent order and slices belong in the editable milestone plan.

## Approval record

- This v5 text was drafted following the user's explicit governance instructions on 2026-10-15.
- **Approved explicitly by user 2026-10-15:** "Je, W" in reply to the assistant asking "Hyväksytkö Overall Plan v5:n uudeksi pyhäksi lähtötasoksi?". This approved copy is frozen; do not modify without new explicit permission.