# Druid L60 Feral Cat — P7.1–P7.5 historical acceptance and recovered evidence

**Status: historical owner-accepted Feral P7 subgate records recovered; independent formal evidence certification OPEN (issue #32).** This PR records the previously accepted **Feral Cat P7 subgates**, not new reruns or certification of the full P1–P7 checkpoint. Do not conflate owner approval with a new Rust run: all preserved P7.1–P7.5 production evidence below uses the historical live gsim-2D ↔ MythicSim Go backend.

## Evidence / gate matrix

| Gate | Recorded outcome | Historical measurable evidence | Artifacts |
|---|---|---|---|
| **P7.1** reference replay | PASS (historical Go hybrid) | External reference 811.023726 DPS; 3,000 end-to-end fights, 819.606699 DPS; one-sided 95% lower delta +7.5703 DPS; 3/3 live causal world tests | `WF607_P71_OFFICIAL_RECHECK.json`, `WF602_P71_3000_E2E.json` |
| **P7.2** rotation cold search | PASS (historical Go hybrid) | 298.0659 s; 618 paid candidates; 187 final fights; 825.168987 DPS; lower 95% delta +10.5711 DPS; 238 2D ACKs | `WF607_P72_OFFICIAL_RECHECK.json`, `WF603_P72_COLD_300S.json` |
| **P7.3** talents cold search | PASS (WF606) | 260.2932 s; 575 paid candidates; winner 824.283608 DPS; 400 final fights; lower 95% delta +10.8776 DPS; 259 2D ACKs | `WF606_P73_FINAL_GATE.json` |
| **P7.4** gear cold search | PASS (WF607) | 256.0313 s; 584 candidates; winner 845.521953 DPS; 400 final fights; lower 95% delta +31.9961 DPS | `WF607_P74_FINAL_GATE.json` |
| **P7.5** joint cold search | **Historical owner closure; revised numeric check conditionally above floor, independent certification OPEN** | WF613 295.0887 s; 2,558 paid unique candidates, no simulator errors; 1,000-fight stochastic holdout 848.76436 DPS (sd 30.18223). Historical comparison to WF613's 853.93055 DPS prior P7.4 candidate: 100%-of-prior lower delta −7.49963 DPS (FAIL under old rule). Revised 99% floor = 845.39124 DPS; point-estimate margin +3.37312 DPS; adjusted one-sided 95% lower bound ≈ +1.03968 DPS. This supports the revised **conditional numeric result only**, subject to independent strongest accepted-compatible prior verification; matching encounter/runtime/scoring and holdout provenance require independent evidence review. | `WF613_P75_COLD_300S.json`, `WF613_P75_HOLDOUT_1000.json`, `WF613_HANDOVER.md` |

**Reference ID:** `c31e596c-a30c-4b99-8789-0848fede6ea6`. Older artifact revisions are preserved in local archive files, not all committed to this repository. Do not present the table as newly executed tests or a verified Rust run.

## Recovered implementation provenance

Original archive names located in user's stored project library:
- `WoW_Forever_Cat_L60_P7_WF607_LOCAL_2026-10-28.zip` — Feral local runtime, P7.1–P7.4 Go hybrid code and raw results.
- `WF607_DRUID60_FERAL_CAT_P71_P74_ALL_PASS_2026-10-28.zip` — historical gate evidence.
- `WoW_Forever_WF609_Mage_Level_Sim_Integrated_FULL.zip` — integrated simulator source.
- `WF611_P75_JOINT_SEARCH_FAIL_2026-10-28.zip`, `WF612_ADAPTIVE_JOINT_SEARCH_FAIL_2026-10-28.zip`, `WF613_COMPATIBILITY_REPAIR_P75_FAIL_2026-10-28.zip` — development history for the joint optimizer.
- `WF614_SEQUENTIAL_REPAIR_SOURCE_2026-10-29.zip`, `WF615_CONDITIONAL_REPAIR_WIP_2026-10-29.zip` — later repair development.

Recovered runtime modules include `p72_cold_search.py`, `p73_cold_search.py`, `p74_wf607_cold_search.py`, `wf612_adaptive.py`, `wf613_repair.py`, `p75_joint_search_wf612.py`, `encounter_options.py`, `wf598_exact_replay.py` and the native Go executable. P7.5 had a legacy module-path/API dependency on `p74_gear_search`, requiring an adapter; this **does not** establish Rust parity. Source-legal search and simulator integration remain subject to the original artifacts and PROCESS.

## Acceptance boundaries

1. This PR is evidence/status documentation for **owner-accepted Feral P7 subgates**, and does **not** certify P1–P6 or change the 0/148 full-checkpoint scoreboard.
2. WF607's accepted P7.4 result is **845.52195 DPS (400 fights)**, but WF613 separately reports a stronger P7.4 stochastic competitor at **853.93055 DPS**. These are not interchangeable: strongest *compatible* prior result determines the P7.5 threshold. Using the more stringent 853.93055: 848.76436 vs 0.99 × 853.93055 = 845.39124 DPS; adjusted lower confidence bound ≈ +1.03968 DPS. Confirm comparability and data lineage in [issue #32](https://github.com/dosibjrn/mage-level-sim/issues/32) before independently certifying the gate. Preserve the original WF613 historical FAIL; report the revised mean-based numeric comparison **conditionally**, not as newly certified full PASS.
3. No assertion of new Feral or Balance Rust P7.1–P7.5 runs; those require separate reproducible evidence.
4. No code for an incomplete Balance gate is promoted here.
5. The audit code, recovered original members and owner decisions may merge as an *evidence-recovery improvement*. Complete original paid candidates, holdout, source and causal logs and stronger-prior acceptance remain [issue #32](https://github.com/dosibjrn/mage-level-sim/issues/32) before formal certification. Do not infer a new native Go/Rust run or a 148-checkpoint PASS from this merge.

## WF613 original-archive identity audit (2026-10-30)

[SHA-pinned lineage manifest](recovered/WF613_ARCHIVE_LINEAGE_VERIFIED.json) records a fresh read-only audit of the original 832,023-byte WF613 ZIP, not a new combat run. The original 300-second cold-search bytes, generator source, independent holdout precommit, all 1,000 stochastic fights, frozen winner and 110 world↔Go causal ACKs link by their recorded SHA256/config identities. The audit is now executable via `tools/audit_feral_p7_holdout.py`, with tampering regressions in `tests/test_audit_feral_p7_holdout.py`.

**Important unresolved comparator:** the stronger **853.9305466 DPS** P7.4 mean is present in WF612/WF613 as a precommitted prior value, but the inspected WF607/WF613 ZIPs do not contain its independently accepted raw P7.4 result. WF607's documented accepted P7.4 mean is **845.5219526 DPS**. Do not elevate the stronger prior to an accepted-compatible comparator merely because WF613 repeats it. Thus the v2.10 numeric comparison is *conditional*, the historical original FAIL remains intact, and the user-approved P7 closure is a separate decision. Original raw files still require durable GitHub publication for independent PR review.

## Integrator follow-up (PR #12 review)

- Keep Feral historical Go-hybrid recovery strictly separate from Balance native Rust P7.2 PR #17 and merged governance PR #18.
- The stronger WF613-reported 853.93055 DPS prior result is used in the non-inferiority computation; reconcile its accepted status and settings against the WF607 845.52195 DPS gate row, **do not** silently substitute the lower value.
- The user-approved P7 CLOSED decision is preserved, but **formal gate certification remains blocked** until reviewed source, raw WF613 1000-fight holdout, paid candidate trace and per-gate live causal logs are committed and independently inspectable.
- The archive importer now rejects POSIX absolute paths, Windows drive/UNC paths, backslash member names, and traversal components.
