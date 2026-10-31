# WORK ORDER — Generic native Rust L60 matrix, 5s → 30s → 300s

**Owner intent, 2026-10-30:** Get as much as possible from the EXISTING gsim/Python optimizer + REAL MythicSim Rust, using MythicSim's native item database. **Try every class/spec cheaply first.** Understand gaps from actual execution; drive further work with small, reproducible, class-neutral unit-test blocks. **Do NOT make 2D a prerequisite.** After this works, 2D and levels below 60 are separate work.

## 0. Read this before coding

- **Work branch:** `work/native-rust-generic-l60-matrix-5-30-300`. It was branched from **PR #25 head `9abb3c8f2ed44fbfa32f2ce7d811cd76d83914e5`**, NOT from main, to reuse working WF678 Rust-backed joint-search, `apl_mutation.py`, and native evidence. PR #25 is currently OPEN; treat it as an explicit dependency. **Do not edit, overwrite or merge PR #25 or competing unrestricted Druid PR #26 as part of this task.**
- **Relevant code:** `integrations/mythicsim-rust/p75_joint_search.py`, `p73_talent_search_v2.py`, `p74_gear_search.py`, `p74_gear_validation.py`, `apl_mutation.py`, `rotation_search.py`; historical WF613 is documented in PR #12 archives, but recovered WF613 source is NOT required to start this branch.
- **Pinned true combat provider:** MythicSim Rust binary from the existing WF678 workflow `.github/workflows/wf678-p75-pr.yml`. **DO NOT replace with Go, a fake scorer, gsim combat, or a hand-written approximation.**
- **True Rust data:** pinned engine checkout (WF678 pins engine revision and binary checksums), `data/items.jsonl`, `data/enchants.jsonl`, `data/spells.jsonl`, `data/proto-schema.json`; optionally `data/consumables.jsonl` and `data/random-suffixes.jsonl`. Fetch/build or reuse pinned artifacts in CI. These are the **primary native combat/item authority**. gsim/Forever SQLite may add verified item/class-level restrictions or display metadata, but **a missing item in gsim's older Wowhead SQLite must not by itself delete a valid native Rust item**. Record any unverified equip restriction; don't silently admit illegal gear.
- **Source fixtures:** real saved MythicSim full requests in repository or pinned Rust engine `fixtures/forever-gaps/*.request.json`, `fixtures/healers/*.request.json` and other genuine fixtures where applicable. A fixture is an **engineering smoke input**, not automatically the externally saved spec leaderboard reference. Never invent an external DPS reference or reuse one spec's talents/APL as another spec's. A source inventory may be incomplete — that is a **row-level BLOCKED status**, not a reason to stop the entire sweep.
- **Authoritative matrix enumeration:** `config/validation/checkpoint_148.json` → `spec_profiles`; **9 classes, 28 fixed L60 spec profiles** (Druid four; eight others three each). The **9 unrestricted L60 profiles** are a follow-on, once their class-scoped objective and comparator are available. DO NOT hardcode an unrelated subset or silently mark 28 covered when only a few work.

## 1. Architecture: smallest viable glue, not a rewrite

```text
config/validation/checkpoint_148.json  (28 spec rows)
            + pinned native request fixtures / saved reference
            + MythicSim Rust DB: items, enchants, spells, schema
                             |
                    per-spec data adapter
          [identity, legal gear slots, talent schema, APL corpus,
             valid native request, objective unit]
                             |
        gsim-owned generic Python search kernel (existing WF678 strategy)
          free dimensions: gear | talents | APL | joint
          5s / 30s / 300s configurable budget
                             |
          one real pinned MythicSim Rust CLI evaluator
            screen (balanced RNG) → stochastic rerank
                    → independent stochastic holdout
                             |
             each of 28 rows: measured result OR explicit BLOCKED
```

**The search core must not import `talent_schema_druid`, test `class == 'druid'`, require 16 items, or assume specific talent-string lengths / Moonkin abilities.** Every class-/spec-dependent rule lives in data adapters, never in the search loop. Reuse `p75_joint_search`'s cold restart, elite mutation, paid search/evidence loop, deadline and RNG logic where sound. Reuse `apl_mutation.py` for *source-corpus-bounded* mutation, but never mix a different class/spec's spell IDs into a candidate. Build a thin adapter first instead of refactoring every existing search file.

**Contract for pure lightweight core** (needed to make the accompanying TDD test green):
- Place `integrations/mythicsim-rust/native_matrix.py`.
- Export `enumerate_l60_profiles(registry, *, include_unrestricted=False) -> list[tuple[str,str]]` using registry class order and spec_profiles. `include_unrestricted=True` appends exactly 9 `(class_key, 'unrestricted')` entries.
- Export `search_native(*, profile_id, reference, propose, mutate, legal, evaluate, seconds, iterations, seed, clock)` for mockable **class-neutral** single-profile screening. `propose(rng)` and `mutate(candidate,rng)` return requests; `legal(candidate)` validates; `evaluate(candidate, *, iterations, seed, rng_mode)` returns finite numeric native metric; `clock()` is monotonic. Return dict with `profile_id`, `status` (`RAN` or named `BLOCKED_...`), `paid_candidates`, `best_candidate`, `best_score`, `elapsed_s`. No real Rust, file I/O or sleep in this pure core test. Production adapters provide callable implementations; native evaluator must call the actual Rust binary. **Missing reference must BLOCK without calling evaluator.**
- Add a separate CLI wrapper for the real matrix (e.g. `native_l60_matrix.py`) that loads the manifest, builds adapters, handles per-row exceptions, persists reports and orchestrates progression. Do **not** shoehorn all file I/O into the pure test interface.

## 2. Clear, independently reviewable work BLOCKS

### BLOCK A — Native fixture inventory and harness (target: 1–2 h)

1. Load all 28 profile keys from the registry; enumerate **all** nine classes. Write a manifest (JSON or JSONL) with status `REFERENCE_READY`, `SMOKE_FIXTURE_ONLY` or `BLOCKED_REFERENCE_MISSING`, and exact source path/hash, class oneof, spec identity, gear slots, talents, APL, encounter and scorer (`DPS`, `HPS`, or `TPS`). Do not infer reference from profile label.
2. Validate at least two genuine class-different native requests with the pinned Rust CLI, **without any search**; preserve original request and native stderr / status. Baseline one native score/record per available spec, where possible.
3. Record native input support failures (`RUST_UNSUPPORTED_REQUEST`, `UNSUPPORTED_SPELL`, etc.) as real blockers. A fixture's successful *preparation* isn't proof of the full request's semantics.
4. Keep an exact manifest of pinned engine binary SHA256, native DB hashes and input request hashes. Explicitly distinguish `SMOKE_FIXTURE` from `PINNED_RANKING_REFERENCE`.

**DONE:** 28-row manifest exists, all rows have source or a specific blocker; at least two distinct classes replay through real Rust. **No bogus 28/28 PASS.**

### BLOCK B — Native-only cross-class generic kernel (target: 2–4 h)

1. Implement `native_matrix.py` pure interface above. **Run `python -m unittest integrations/mythicsim-rust/tests/test_native_matrix_contract.py` green**. This attached test is intentionally RED until implemented; don't weaken/skip it.
2. Adapt WF678 to call it (or extract the candidate-evaluation loop into it) while retaining balanced search + separate stochastic finalist/holdout, reproducible seed, paid candidate logs, and no reference/winner warm start. Independent cold rediscovery remains legal.
3. Keep all class-specific gear/talent/APL logic in adapters. A user-configurable `free_dimensions` controls P7.2 (APL), P7.3 (talents), P7.4 (gear), P7.5 (joint). **First breadth pass may run JOINT only**, then use these four modes after smoke success. This is a native *diagnostic* matrix, not certified gate PASS.
4. Smoke fake evaluators are for genericity unit tests ONLY; real CI/matrix output always uses pinned native Rust.

**DONE:** 28 fake profiles with varying gear lengths, arbitrary class/spell IDs, reference immutability, no Druid-only dispatch, bounded clock, named missing-reference blocker; existing Balance WF678 contract tests unchanged/green.

### BLOCK C — Rust-DB-first gear, talent, APL adapters (target: 2–5 h + per-spec gaps)

1. **Gear:** derive item IDs/slots from native Rust `items.jsonl` (and enchants), plus validated source restrictions if available. No universal 16-slot `SLOTS` constant. Support 1H/2H, offhand/shield, dual wield, ranged/relic, rings/trinkets/unique families, class armor/weapon use, enchants and disallowed combinations as far as pinned engine/source describes. Native Rust is final evaluator. Missing class restrictions → `BLOCKED_GEAR_LEGALITY` or keep gear fixed and mark `PARTIAL_DIMENSIONS`; do not silently call a partial search joint.
2. **Talents:** move `talent_schema_druid` behind `TalentAdapter`; parse/build legal 51-point allocations using *each class's verified tree schema* (from selected pinned source, not simply `src/classes/*/prepare/talents.rs` guessed as a tree). Respect prereqs and class-specific spell unlocks. If unavailable, run APL-only or fixed-talents with explicit `PARTIAL_DIMENSIONS` rather than inventing talent allocations.
3. **APL:** `apl_mutation.py` source spell/predicate corpus per spec. Don't mutate another spec's APL into this spec. Native rejection / not executable → categorized rejection. Missing full spellbook coverage must be recorded, not fabricated.
4. **Score:** real per-profile native metric and unit. Healer HPS and tank TPS can be *measured diagnostically*; do not compare those to DPS or issue PROCESS DPS PASS. Profiles without source-compatible metric are `BLOCKED_OBJECTIVE` (but other rows proceed).

**DONE:** at least two actual class-different complete *native legal* candidate mutations and evaluations; source hashes, legality rejection categories, all dimension status exported. No blanket per-class hardcode in core.

### BLOCK D — Run **5-second** breadth sweep first (target: 1–2 h harness + execution)

1. One CLI command for all 28: e.g. `python integrations/mythicsim-rust/native_l60_matrix.py --level 60 --budget 5 --free joint --all-specs --out out/native-l60-5s/`. Use the existing verified Rust build and DB; optional `--class`, `--spec`, `--max-parallel`, `--resume`, `--seed`.
2. **Budget:** 5s is a *per-profile active-search budget*; one-time Rust build/cache/hydration and manifest prep are recorded separately. Report actual wall-search seconds, native evaluation seconds and preparation. For later strict PROCESS 300s gate, use the canonical **whole cold-gate** wall-clock including setup/rerank/holdout. Never quietly report 5s as 300s PASS.
3. Ensure one baseline (if reference exists) and attempt at least one independently paid legal candidate within the short search. Zero legal paid candidates is `BLOCKED_NO_PAID_NATIVE_EVAL` or `BLOCKED_BUDGET_TOO_SMALL`, **not PASS**. At 5s/30s, holdout may be a cheap optional diagnostic; report whether run had an independent holdout. Do not call a screening score a holdout.
4. Write `matrix.json` + `matrix.md` and per-row artifacts: `class/spec`, request/engine hashes, source type, objective unit, free axes actually searched, chosen item IDs, talent allocation, APL hash, native baseline, best native score, score delta, #paid, #rejected by category, #engine errors, wall seconds, evidence path, exact status/blocker.
5. **Never fail the whole matrix if one class/spec is unsupported.** Report all 28. CI fails only on harness bugs, invalid evidence, missing rows, or a previously passing contract regression; unsupported rows remain explicit blockers.
6. Keep source fixtures and tiny manifests in Git; upload large raw candidate traces via GitHub Actions artifacts/LFS (real LFS push only), with SHA links. Avoid uncommitted manual input.

**DONE:** 28/28 reported rows, real native evidence for each `RAN` row, exact BLOCKED reasons for remainder; at least **two different classes** have paid legal Rust evaluations. No all-green bluffing.

### BLOCK E — Promote **5s → 30s → 300s**, only when useful

- A profile is eligible for **30s** if baseline and >=1 legal native paid candidate were measured in 5s, with a finite comparable metric and no unresolved correctness errors. **It need not beat the reference.** A profile with missing rules is NOT eligible; fix the precise blocker instead.
- A profile is eligible for **300s** if 30s completed using the same pinned schema/engine and produced at least one valid evaluated candidate. Promotion is based on *correct operation*, not arbitrary improvement/DPS target.
- Run the next stage for every eligible profile in parallel/shards. A fresh **independent cold search for each stage** (never use 5s or 30s winners as warm seeds when claiming cold P7 evidence); optional resume is for interrupted runs **within the same stage**, not cross-stage seeding. Preserve earlier results for comparison only.
- On 300s, add separately frozen >=1,000-fight stochastic holdout and correct PROCESS v2.10 numeric floors **only when a pinned true ranking reference and strongest accepted/compatible prior exist**. Without them, output `NATIVE_RESULT / P7_CERTIFICATION_BLOCKED`. Full PROCESS P7.2–P7.5 still additionally require live gsim-2D↔native integration, deliberately postponed.
- Run modes APL, talents, gear and joint as separate cold searches once generic search works. 28 profiles × 5s ≈ **140 seconds of active-search budget**, 28 × 30s ≈ 14 minutes, 28 × 300s ≈ 2h20m; these exclude preparation/holdout and assume all 28 runnable. Do not promise 5s will find a good optimum.
- **Unrestricted 9 class profiles**: only after fixed-spec rows run; reuse same engine/adapters with free spec/talent mode and compatible cross-spec objective/benchmark, and report missing objective comparability rather than pretending they are one of the 28.

**DONE:** stage-specific report and independent seed/evidence for every eligible profile, with explicit stage promotion decisions and source/engine hashes.

### BLOCK F — Stop / capture next gaps, do not expand scope invisibly

- At each block boundary, publish `GAPS.md` (or machine-readable `gaps.json`) grouped by root cause rather than class: `NO_NATIVE_REQUEST`, `RUST_UNSUPPORTED`, `MISSING_TALENT_TREE`, `INVALID_GEAR`, `UNSUPPORTED_APL`, `OBJECTIVE_MISMATCH`, `ITEM_IDENTITY`, `BUDGET`, `ENGINE_ERROR`, `HOLDOUT_NOT_RUN`. Each gap has *exact profile(s), a failing native request/test, path, next tiny fix*.
- Fix highest shared-root-cause blocker **only if it unlocks multiple rows without class-specific hacks**; keep targeted PRs/commits. Don't build a new class simulator or manually paper over Rust-unsupported items.
- **Out of scope until this succeeds:** 2D↔Rust causal ACK, L20/L30/L40, 100-mob chainpull scoring, full spec rankings, redefinition of P7 PASS, changes to `PROCESS.md`/`OVERALL_PLAN.md`, rewriting old Go/Rust histories, a sweeping item-DB migration.

## 3. Lightweight generics test grid (required)

| Test | Should enforce |
|---|---|
| `inventory_28` | 9 classes, **exactly 28** fixed spec rows from registry |
| `inventory_37` | optional unrestricted adds 9 rows (no duplicate IDs) |
| `fake_28` | all 28 independently call the **same search function**, with fake data/adapters and differing gear-slot counts |
| `no_druid_assumption` | arbitrary class/spec/weapon shape and arbitrary spell IDs survive the pure optimizer; source adapters own legality |
| `reference_immutable` | full saved reference remains unchanged through search |
| `missing_reference_block` | missing true input yields named BLOCKED; fake evaluator not called |
| `budget_5_30_300` | 5/30/300 allow promotion only on runnable legal paid native results; no warm-start between separate stages |
| `native_two_classes` | **integration test**, not fake: actual same pinned Rust executable evaluates at least two distinct class native requests with item DB and records different class identity |
| `WF678_regression` | original Balance WF678 native search tests and exact saved reference still pass after refactor |
| `whole_matrix_report` | every row present once; statuses and raw native artifacts not replaced by a synthetic scorer |

**Before working on Rust:** The accompanying `integrations/mythicsim-rust/tests/test_native_matrix_contract.py` defines the first TDD surface and is **intentionally RED** until `native_matrix.py` exists. Make it green with the simplest class-neutral implementation. If implementation makes a better interface necessary, update BOTH interface and tests explicitly and explain why; do not simply skip or xfail tests.

## 4. Required output / PR acceptance

- One coherent implementation PR from this branch **after code and tests**, based on PR #25 dependency. This present branch starts as **work order + red test only; not a finished optimizer**.
- Link actual GitHub Actions run(s) with pinned Rust binary SHA256 and native DB manifest checksum; **never claim work executed if only unit tests were run**.
- Show a compact table with **all 28** `class/spec | fixture | dimensions searched | paid | baseline | best | delta | status/blocker` and per-class coverage subtotal.
- Include 5s run first, then 30s / 300s only where actually ready. Report measured progress even if many rows are blocked. Post exact next blocker, not general "support lacking".
- No fake PASS for any P7 gate, no 2D requirement in this iteration, no changes to canonical PROCESS v2.10. A native proof is valuable independently of formal P7 certification.
