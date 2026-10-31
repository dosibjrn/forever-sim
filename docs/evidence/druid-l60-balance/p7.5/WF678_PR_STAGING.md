# Balance Druid L60 P7.5 — WF678 native search evidence

## First VERIFIED byte-exact PR HEAD WF678 native run — 2026-10-30 18:44 UTC

**Branch code and documentation HEAD:** [`48c45efb84bb6bac06e8d8fed83d243e0b58dfa7`](https://github.com/dosibjrn/mage-level-sim/commit/48c45efb84bb6bac06e8d8fed83d243e0b58dfa7). Both WF678 jobs explicitly checked out that **same exact SHA**, not GitHub's synthetic PR merge ref; the runner logs print `WF678 exact source commit: 48c45efb84bb6bac06e8d8fed83d243e0b58dfa7`. The [WF678 exact-head run #41108670861](https://github.com/dosibjrn/mage-level-sim/actions/runs/41108670861) completed **contracts SUCCESS + native-joint SUCCESS**. The new checkout contract first failed RED on [#41108615914](https://github.com/dosibjrn/mage-level-sim/actions/runs/41108615914) (2 expected / 0 found), then passed on this exact-head run.

- **4,000-fight frozen independent stochastic mean: 807.9191412484101 DPS**; rerank 805.0025139716159 DPS; **4,117** paid unique candidates, **0** native failures, **2** candidate legality rejections; **277.352805259 s** cold end-to-end (<300 s).
- Saved external reference: **728.1936126415858 DPS**. Frozen winner talents `5532222115501351-050101-1`, APL SHA256 `4cdb65d60e5e8a903200fba17456566c40b07965878d39d5d5802fcd8ad9aedd`. Saved source SHA256 `8cb0e76db54c407ffbfac2085f60c90d8763c80adc1d3fe26681d02dec5071a7`; Rust binary SHA256 `605cfa5231b9813646b32e24a1ef7046cd18b54a5b767ffff326593ef7d4c57e`.
- [Raw exact-head artifact #13002676953](https://github.com/dosibjrn/mage-level-sim/actions/runs/41108670861/artifacts/13002676953), upload-reported ZIP SHA256 `681bd69aea1b7392a95a6fa6322a01bb0a628068641fbfff14a0ce51a6ec8da6`.
- Companion [P7.4 native regression #41108670870](https://github.com/dosibjrn/mage-level-sim/actions/runs/41108670870) SUCCESS, **795.5105626598366 DPS** (separate cold run; 6,264 paid, no native failures). Earlier same-PR-associated [P7.4 #41101207738](https://github.com/dosibjrn/mage-level-sim/actions/runs/41101207738) reached **810.1099107086704 DPS**. **Neither run is independently certified as the strongest accepted-compatible prior**, so do not select a convenient comparator or report formal P7.5 numeric acceptance. [Gate-runtime #41108670823](https://github.com/dosibjrn/mage-level-sim/actions/runs/41108670823) SUCCESS.
- The native runner still correctly emits `status=NATIVE_P75_DIAGNOSTIC_NOT_PROCESS_GATE_PASS`, `comparator_status=BLOCKED_ACCEPTED_COMPATIBLE_PRIOR_UNVERIFIED` and `prior_floor_mean_numeric_check_only=null`.

**Full PROCESS v2.10 P7.5 is BLOCKED**, despite genuine native success: independently accepted strongest compatible prior, complete source item/enchant/effect parity and live gsim-2D↔Rust world/native/ACK causality are still missing. No P1–P7 checkpoint PASS; main scoreboard stays **0/148**. This documentation update does not alter the measured optimizer; do not claim its own subsequent SHA is tested until CI verifies it.

## Newest completed PR-associated CI (2026-10-30 17:52 UTC) and exact-head correction

**Do not conflate GitHub's PR synthetic merge checkout with the branch HEAD.**
The completed [WF678 PR run #41101207818](https://github.com/dosibjrn/mage-level-sim/actions/runs/41101207818) is associated with branch head [`11b3a74`](https://github.com/dosibjrn/mage-level-sim/commit/11b3a7487c0d13d713c0754746231bc3e126f886), but its old `actions/checkout` configuration used GitHub's default **`refs/pull/25/merge`** checkout. Both `contracts` and `native-joint` succeeded on that PR merge tree. This is a real native run, but it must **not** be called a byte-exact checkout of `11b3a74`.

- Frozen independent 4,000-fight stochastic **mean 806.0244632067363 DPS**; rerank 804.5468934803314 DPS; **6,500** paid unique candidates, **0** native errors, **2** candidate legality rejections; **273.900728052 s** cold end-to-end (<300 s).
- Same saved external reference **728.1936126415858 DPS**; source SHA256 `8cb0e76db54c407ffbfac2085f60c90d8763c80adc1d3fe26681d02dec5071a7`, Rust binary SHA256 `605cfa5231b9813646b32e24a1ef7046cd18b54a5b767ffff326593ef7d4c57e`.
- Winner talents `5532220115501351-151001-02`; winner APL SHA256 `b1f03804612e417ff5a252586cded666bbe8003b238209ba0fb4edbbc7c9950e`.
- [Raw evidence artifact #12998142923](https://github.com/dosibjrn/mage-level-sim/actions/runs/41101207818/artifacts/12998142923); upload-reported ZIP SHA256 `e285395231b507596c7961dc65c234143a2c56868c4264a59283b5acc00a763e`.
- Associated [P7.4 run #41101207738](https://github.com/dosibjrn/mage-level-sim/actions/runs/41101207738) also succeeded: **810.1099107086704 DPS** native diagnostic, 4,000-fight holdout, same reference and Rust binary, **not** independently accepted as the strongest compatible P7.1–P7.4 prior. Its provisional 99% floor is **802.0088116015837 DPS**; this P7.5 result exceeds it by **4.0156516051526 DPS**. This arithmetic is diagnostic, not formal prior acceptance. [P7.4 raw artifact #12999676844](https://github.com/dosibjrn/mage-level-sim/actions/runs/41101207738/artifacts/12999676844), upload ZIP SHA256 `0cc5515f5a50e52bccbc4daa72bb0ab47a1f743ceb977858a1b801fa48785700`.
- [Gate-runtime #41101207749](https://github.com/dosibjrn/mage-level-sim/actions/runs/41101207749) also succeeded. **0/148 full checkpoints** remains unchanged.

**Concrete exact-head fix:** [`4a54e92`](https://github.com/dosibjrn/mage-level-sim/commit/4a54e92582de3ce0d6636bedfcff42ee3037f0d4) adds a regression requiring both WF678 jobs to pin the event's actual head SHA. [`344084b`](https://github.com/dosibjrn/mage-level-sim/commit/344084b6cc93b39a38b97740f4dab92d5c07020e) updates both checkout steps to `github.event.pull_request.head.sha || github.sha` and asserts `git rev-parse HEAD`. **Do not claim these commits have passed a fresh exact-head native rerun until its GitHub Actions jobs finish.** Neither change modifies optimizer search semantics. The previous 807.919 DPS result remains a historical verified run, not a promise of the next cold search outcome.

**Formal PROCESS v2.10 P7.5 remains BLOCKED:** strongest independently accepted compatible prior, live gsim-2D↔Rust world→native→world ACK causality and full source/effect legality are not established. The report explicitly emits `BLOCKED_ACCEPTED_COMPATIBLE_PRIOR_UNVERIFIED`; no 95% confidence lower-bound gate is introduced.

## Earlier tested optimizer code head — 2026-10-30 17:30 UTC (19:30 Finland) (native diagnostic, NOT PROCESS gate PASS)

**Code SHA** [`f8912981439160da63bd71962cd84ac10107ff1a`](https://github.com/dosibjrn/mage-level-sim/commit/f8912981439160da63bd71962cd84ac10107ff1a), after finite <=300s CLI budget input validation. **[WF678 Actions #41098694311](https://github.com/dosibjrn/mage-level-sim/actions/runs/41098694311) SUCCESS**, both `contracts` and genuinely executed `native-joint`. Independent frozen **4,000-fight stochastic holdout mean = 807.9191412484101 DPS**, reranked finalist 805.0025139716159 DPS, **4,128** paid unique candidates, **0** native scoring failures, **2** candidate legality rejections, **277.140924678 s** end-to-end (including setup, search, rerank and holdout). Source corpus and actual winner identity remain identical to the earlier 807.919 reruns, while paid count/time vary across searches; do not equate separate runs.

[Exact-head raw artifact #12997661623](https://github.com/dosibjrn/mage-level-sim/actions/runs/41098694311/artifacts/12997661623), archive SHA256 `125e662dc77a5c5527bd8904b43b219328a9a373e9aa687b664a9b4c83c9449f`. Pinned Rust binary SHA256 `605cfa5231b9813646b32e24a1ef7046cd18b54a5b767ffff326593ef7d4c57e`; frozen reference SHA256 `8cb0e76db54c407ffbfac2085f60c90d8763c80adc1d3fe26681d02dec5071a7`. Frozen winner talents `5532222115501351-050101-1`, APL SHA256 `4cdb65d60e5e8a903200fba17456566c40b07965878d39d5d5802fcd8ad9aedd`.

The exact runner still emits `status=NATIVE_P75_DIAGNOSTIC_NOT_PROCESS_GATE_PASS` and `comparator_status=BLOCKED_ACCEPTED_COMPATIBLE_PRIOR_UNVERIFIED`. Native quantitative/holdout/time checks are **PASS**; full PROCESS v2.10 P7.5 remains **BLOCKED** (independently accepted strongest compatible P7.1–P7.4 prior; full source-legal item/enchant/effect parity; actual gsim-2D↔Rust causal/ACK integration, plus issue #10 shared optimizer/matrix scope). The saved 728.193613 external reference is exceeded; no accepted prior is supplied, so no formal 99%-of-accepted-prior comparison is reported.

**Current integration/review note (2026-10-30 17:43 UTC):** PR #23's P7.4 changes were integrated into `main` at `e22a5bb`; PR #25 is now **based on `main`**. Its integration-merge head [`4365b6c`](https://github.com/dosibjrn/mage-level-sim/commit/4365b6c2bad61c238c967b8c5665fff6664c83b5) preserves the measured optimizer implementation from `f891298`, and the PR review diff contains six files. **Do not attribute the `f891298` 807.919 DPS measurement to the integration-merge head without checking its own CI.** Exact integration-head [WF678 #41100943455](https://github.com/dosibjrn/mage-level-sim/actions/runs/41100943455), [P7.4 #41100943498](https://github.com/dosibjrn/mage-level-sim/actions/runs/41100943498) and [gate-runtime #41100943400](https://github.com/dosibjrn/mage-level-sim/actions/runs/41100943400) were **queued at 17:43 UTC**, not yet certified green. This evidence-document correction changes neither solver nor the saved request; full P7.5 PROCESS gate remains BLOCKED on accepted compatible prior and live 2D↔Rust causality.


## Latest post-enchant-validation code-head replay — 2026-10-30 (native diagnostic, not PROCESS gate certification)

The previous WF678 result below belongs to code `bf884fc`. Three new PR #25 commits `978363b` (RED test), `298c765` (candidate-enchant-aware validator/cache) and **`12a3ed41dfc014eb46074bc959aacebd512f01e4`** (actual candidate enchants passed to both search admission and winner audit) changed the legality path. A new pinned-Rust native run was therefore required; do not carry the earlier 806.55775 DPS forward as an exact-code-head result.

**Verified [exact-code-head Actions #41070594825](https://github.com/dosibjrn/mage-level-sim/actions/runs/41070594825): contracts SUCCESS + native-joint SUCCESS.** The frozen 4,000-fight stochastic holdout now measures **807.9191412484101 DPS** (rerank 805.002514), with **4,011 paid unique candidates**, **0 native scoring failures**, **2 candidate legality rejections**, **3,180 stochastic probes** and **277.611788 seconds** including setup/search/rerank/holdout (<=300s). The saved external Balance reference remains **728.1936126415858 DPS**. Pinned Rust binary SHA256 `605cfa5231b9813646b32e24a1ef7046cd18b54a5b767ffff326593ef7d4c57e`; saved reference SHA256 `8cb0e76db54c407ffbfac2085f60c90d8763c80adc1d3fe26681d02dec5071a7`.

[Full new raw evidence artifact #12985590213](https://github.com/dosibjrn/mage-level-sim/actions/runs/41070594825/artifacts/12985590213), ZIP SHA256 `3716881ea4f358e041488b0fce1afb3f7f2ea5beaaa5a43bd94d595d412563c1`. Frozen winner talents `5532222115501351-050101-1`; APL SHA256 `4cdb65d60e5e8a903200fba17456566c40b07965878d39d5d5802fcd8ad9aedd`. The code-head [P7.4 Rust regression #41070797244](https://github.com/dosibjrn/mage-level-sim/actions/runs/41070797244) also finished SUCCESS with **806.8320387595546 DPS** (source-legal native P7.4 diagnostic, **not independently certified strongest accepted prior**). Its raw [artifact #12983869812](https://github.com/dosibjrn/mage-level-sim/actions/runs/41070797244/artifacts/12983869812) has ZIP SHA256 `c26f988ca08069755c24598935cccf9f2f7fbf8e15519a829f8fa485b228caf5`.

The new P7.5 mean exceeds the native P7.4 diagnostic by **1.0871024888555 DPS**, and exceeds both the external reference and the provisional 99%-of-806.832 floor **numerically**. The P7.5 CLI correctly reports `comparator_status=BLOCKED_ACCEPTED_COMPATIBLE_PRIOR_UNVERIFIED` and `prior_floor_mean_numeric_check_only=null` because no accepted-compatible prior was supplied. **No full PROCESS P7.5 PASS or P1–P7 checkpoint is claimed**: strongest accepted prior provenance, full source legality and live gsim-2D↔Rust causality still need independent evidence. The previously published historical result is retained below for comparison.


## Historical pre-enchant-fix WF678 native result (2026-10-30)

The **historical exact-code-head** WF678 search at `bf884fcc7560825bc2aec736d4a80c66b4ce1cb5` finished successfully before the candidate-enchant validation fix. It is not the latest PR #25 code-head result; see the fresh replay above. It is also distinct from the earlier WF676 result.

| Measured property | WF678 result |
| --- | --- |
| Frozen independent stochastic holdout mean | **806.5577486279375 DPS** |
| Holdout sample | 4,000 iterations |
| Re-ranked finalist | 804.3294922495737 DPS |
| Native paid unique candidates | 4,810 |
| Native simulation failures | **0** |
| Pre-simulation candidate legality rejections | 2 |
| Stochastic screening probes | 3,804 |
| Strict end-to-end budget | **275.579150333 s / 300 s** |
| Saved external reference, same scenario | 728.1936126415858 DPS |
| Latest legal P7.4 native result (PR #23, WF670) | 795.51056266 DPS |
| Relative to latest legal P7.4 native result | **+11.0471859679 DPS (+1.39%)** |
| Native quantitative result | **PASS** (external reference and 99%-of-P7.4 numeric comparator both exceeded) |

- [Exact-head GitHub Actions WF678 run #40979176200](https://github.com/dosibjrn/mage-level-sim/actions/runs/40979176200): **contracts SUCCESS + native-joint SUCCESS**.
- [Full reproducible evidence artifact #12944501413](https://github.com/dosibjrn/mage-level-sim/actions/runs/40979176200/artifacts/12944501413), `wf678-balance-p75-validated-native`; ZIP digest `sha256:21db10a1dc00788357377e4fa8c89d68c3dae11aca4186de6da1dbcb5c51543f`.
- Gate-runtime CI was also successful on this commit.
- Native executable SHA256: `605cfa5231b9813646b32e24a1ef7046cd18b54a5b767ffff326593ef7d4c57e`.
- Saved reference request SHA256: `8cb0e76db54c407ffbfac2085f60c90d8763c80adc1d3fe26681d02dec5071a7`.
- Frozen winner talents: `5532220115501351-150101-02`.
- Frozen winner gear IDs (slot order): `226773, 19426, 227808, 272411, 19682, 21186, 21178, 228190, 252486, 19684, 234020, 275982, 272438, 22678, 20220, 23197`.
- Winner APL SHA256: `2776c933117a0fe979d29fba092f6519f52a99d0023b562212f5e9cb6c390016`.
- The artifact contains `report.json`, frozen winner request, gear identity audit, every successfully paid candidate's complete equipment/talents/APL and seeds, stochastic rerank finalists, rejected candidates, error log, and holdout JSON.

## What is implemented and tested

1. Independent cold joint gear × talents × APL discovery; no reference/past-winner population seeding. Legitimate independent rediscovery is allowed.
2. Pinned source + Rust `GearValidator` before each paid simulation, including item identity, equip slot, class/level, available known enchants, unique-limit categories and duplicate equipment checks.
3. General-purpose `apl_mutation.py` adds/removes legal-corpus cast actions, reorders priorities, substitutes recorded condition ASTs and changes typed comparison thresholds. It is **not just a shuffle**.
4. 300-second monotonic time budget including initialization, screens, reranking and independent frozen stochastic holdout; production legality validation does not rely on removable assertions.
5. Test coverage for source action allowlists, predicate mutation, cold setup, fallback preservation and a second class-like action corpus. The native and contract GitHub Actions jobs succeeded.

## Scope boundary — separate follow-up engineering, not an optimizer failure

The above is a **successful native Rust optimization run** and a quantitative PASS. It does **not by itself** constitute end-to-end PROCESS certification of gsim-2D↔Rust controller/ACK causality, or prove source-legal item/enchant/effect restrictions where authoritative rules are absent. Those integration and data-parity tasks are tracked separately; do not relabel a successful search as failed because they remain.

The numeric comparison uses the **latest known legal pinned-Rust P7.4 native holdout** from [PR #23](https://github.com/dosibjrn/mage-level-sim/pull/23), not the previously invalid WF669 797.362 DPS item combination. Whether this P7.4 result has the required *formally accepted strongest-prior provenance* is a separate PROCESS acceptance check; do not misrepresent the recorded number as an independently certified comparator.

The source-bounded generic APL operators have been implemented. [Issue #10](https://github.com/dosibjrn/mage-level-sim/issues/10)'s full shared Feral/Balance × P7.1–P7.5 search-core and regression matrix remains a broader follow-up, not a claim about this native Balance result.

## Historical experiment (kept only for provenance)

WF676: 813.6215750677441 DPS, 4,000-fight stochastic holdout, 5,573 paid candidates, 276.6287 s. [Run #40976782002](https://github.com/dosibjrn/mage-level-sim/actions/runs/40976782002), artifact `wf670-p75-joint-evidence` (12942727869). Older winner talents `5332220115501351--145002`. This was **before** the stronger P7.4 source/Rust gear validator and the expressive APL update. It is not substituted for the current WF678 result and should not be used to claim a higher current score.
