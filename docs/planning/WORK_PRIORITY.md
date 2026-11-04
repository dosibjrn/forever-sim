# WORK PRIORITY — live M1 queue

Verified against GitHub `main` on 2026-11-04. Canonical ledger blob `5cab5f4e4ae87db153730bd3bb02149eae3cdde6`; only Merge records M1. Active gates P3–P6, P7.1–P7.5 (P1/P2 retired). **M1 measured: 2.2041% (float=0.0220405148); 23 PASS / 1,332 active pairs, 11 PARTIAL.** Diagnostic partial-inclusive coverage, not checkpoint certification. No Prio credit or ledger write.

## #1 Work1 — Priest L20 unrestricted P4/P5: first lethal native↔2D fight, then persistent 100-mob screen

**Owner:** Work1, existing [issue #817](https://github.com/dosibjrn/forever-sim/issues/817), Forever [draft PR #892](https://github.com/dosibjrn/forever-sim/pull/892) HEAD `2bd7200e14184be6c7de6c9bcc3c7810f9705d8a`, selected MythicSim fork [PR #10](https://github.com/dosibjrn/mythicsim-forever-engine/pull/10) pinned `63db5ec8517c2c42588f82d2b6121cb0368cab3e`. Gates `priest:20:unrestricted:P4` and `P5`: **not yet measured**; official [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303) BLOCKED.

**Last VERIFIED live evidence:** [selected native↔2D #41837791695](https://github.com/dosibjrn/forever-sim/actions/runs/41837791695) on prior HEAD `c9e334c`: two genuinely paid whole builds, each 20 source Smite ActionID 585 casts; selected world replay 32 ticks, 17 native damage/source events and valid ACK, but **zero kills** and **zero complete 100-mob screens**. No M1 gain.

**NEW, NOT YET VERIFIED on current HEAD:** PR #892 now changes the selected target from an artificial 10,000 HP/30s fixture to the already documented CMaNGOS Classic **484 HP / 90s proxy**, retains up to two paid candidate attempts after nonlethal ACK, and makes the existing source-health-world smoke demand a **real lethal native↔2D ACK**. The proxy is **not verified Forever creature HP**; the same explicit scenario must be used by native scoring and world execution. Exact current-HEAD workflow result was **not available** in this Prio review; do not call it PASS.

**Single immediate Work1 action:** run/check the existing `native-session-ack-regressions.yml` **source-health-world** focused job on exact PR HEAD `2bd7200e14184be6c7de6c9bcc3c7810f9705d8a` with selected native binary; inspect actual `native_2d_live_world_kills == 1`, source ActionID casts, valid ACK and request identity. If nonlethal, repair the real native/world cause on #892, not an invented gate check. Once lethal, extend **the same retained source-native actor** (HP/mana/resources/cooldowns, movement, recovery, world clock, kill ACK) to 100 consecutive distinct sourced mobs; no reset or post-hoc clock. Only a truly complete paid 100-mob result permits later independent cold 30/300-second P4/P5 verification and conditional Merge recorder. A single kill alone earns **no** M1.

**Conditional upside, unearned:** two eligible 2/6 partials could add +0.05005 percentage points; two full PASSes +0.15015 pp. This shared real-world path has potential reuse across other checkpoints and outranks a repeated zero-gain P3 probe.

## #2 Work2 — Mage L30 unrestricted P3: stop no-gain scheduling probes; repair a genuinely executable stat axis

**Owner:** Work2, existing [issue #818](https://github.com/dosibjrn/forever-sim/issues/818). Gate `mage:30:unrestricted:P3`. Official [#41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067): **PARTIAL 129/224**, 44 paid evaluations.

**New result:** [PR #902](https://github.com/dosibjrn/forever-sim/pull/902) **MERGED**; exact production HEAD `3387987b769d3b9f5c58d4aec4171bbffacb2f71`. [Selected real no-record #41841553378](https://github.com/dosibjrn/forever-sim/actions/runs/41841553378) SUCCESS technically, **FAIL 129/224 with 44 paid, unchanged**. Distinct source policies and `paid_search_winner` were reached; Spirit/MP5/Agility/AP paid probes stayed nonpositive. Positive Intellect/SP/Hit preserved. Stamina/Strength/Parry/weapon DPS remained `not_executable_in_source_ir`. [Source-paid #41841553649](https://github.com/dosibjrn/forever-sim/actions/runs/41841553649) and [maintenance #41841553446](https://github.com/dosibjrn/forever-sim/actions/runs/41841553446) SUCCESS. **No additional M1 credit and no official recorder for this unchanged count.**

**Single next Work2 action:** on a new branch from latest merged main, trace the selected Mage L30 real source/native stat mutation and the existing `executable_gear_stats` → `sensitivity_history` → P3 scorer path. Choose the first actually executable missing applicable axis (Stamina/Strength only if source/native supports it); if a native capability is specifically missing for this live P3 caller, make the smallest Rust-fork addition and tested exact pin. No Python GameIR/Warcraft stat rules, fake zero/epsilon, generic scheduling-only repeat or independent MythicSim audit. Focused transport regression, then **one changed-HEAD** no-record Mage L30 P3 against the selected binary, ≤44 paid; compare strictly with **129/224** and preserve SP/Int/Hit. Request one Merge recorder **only** if comparable count improves. If no authentic executable axis can be found, document the exact source refusal in #818 and move to another real active-gate opportunity rather than spend the same budget again.

**Conditional remaining ceiling, unearned:** 95/224 of this gate = +0.03184 percentage points. One additional comparable assertion = +0.0003352 pp.

## Merge — trusted recording only when real evidence changes

Priest: no official P4/P5 recorder before genuine complete 100-mob native↔2D paid screen and required executed source actions; a single lethal ACK is only an implementation milestone. Mage: PR #902's real 129/224 no-record is unchanged; **do not run an official recorder on that unchanged producer**, including in response to a stale `/m1-run` comment. Only Merge writes `docs/planning/M1_PASSES.tsv`.

## Deferred / rejected alternatives

Warrior L20 P3 [#891](https://github.com/dosibjrn/forever-sim/issues/891) official [#41829878857](https://github.com/dosibjrn/forever-sim/actions/runs/41829878857) BLOCKED before paid scoring; no unchanged rerun. Paladin L20 P3 154/210 unchanged after #887; Shaman L20 P3 93/204; Mage L20 P3 88/224. Druid L30/L40 unrestricted P6 already 200/200 PARTIAL with no fractional headroom absent full PASS. Do not substitute P1/P2, GameIR, HPS/TPS, architecture cleanup or MythicSim-rules validation for measured active-gate progress.
