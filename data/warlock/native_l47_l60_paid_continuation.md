# Warlock L47–L60 — original native-paid successor observations

**Evidence, not an optimized leveling route.** These are the 14 genuine 100-kill source-native/gsim successor measurements captured in [Actions run #42822112684](https://github.com/dosibjrn/forever-sim/actions/runs/42822112684), original [artifact #13767792611](https://github.com/dosibjrn/forever-sim/actions/runs/42822112684/artifacts/13767792611) (GitHub expiry **2026-11-13 13:15 UTC**). The checks below were performed directly against the recovered ZIP, without a fresh native replay.

- ZIP SHA-256: `2e0fbf2ad8ea1bfdeb997bae578bed62faaeaf81357565fa31a68c4fc32ccf0d` (archive contains original raw requests, native chain receipts, prepared requests, summaries, route and guide).
- All 14 native `best_apl` summaries report `COMPLETED_100_REAL_NATIVE_GSIM_KILLS`, **100/100** hostile kills and paid recovery. Each matching original `chain_native_world.json` reports `actual_2d_ack=true`, `continuous_native_actor=true` and 100 world target kills; each `source_request.json` SHA-256 matches the native summary and original `proposal.json` selected source SHA-256.
- Selected Rust binary SHA-256: `133c96ba50b7589036e062e18a3315e28ac2562064cb99e96d501fc4ee054458`. Reported levels are **separately paid adjacent-level measurements**, not a genuine continuous 10–60 leveling journey with XP/training/travel and sourced spec costs.

## What the executed builds actually used

- **Talent family:** one incremental Destruction-dominant path. Per-level `proposal.json` records `attempted=1`, i.e. one successfully native-prepared successor proposal (not a measured cross-tree winner).
- **Equipment:** the same 17-slot equipped-item ID list at every level, in original slot order; item IDs (zero indicates an empty/requested-zero slot): `260212, 22657, 22968, 19121, 0, 0, 20716, 22062, 22700, 22064, 275738, 275738, 0, 0, 22379, 19989, 275837`.
- **Ordered native APL:** `castSpell(6222)` when that DoT is not active → `castSpell(1014)` when that DoT is not active → `castSpell(1088)`. The spell IDs and conditions are copied from the actually executed source requests; no unmeasured APL alternatives are claimed.
- **Pet:** `warlock.options.classOptions={}` in each saved request; **no explicit pet selection is recorded**. Do not infer a selected or optimized pet from an empty options object.
- **Recovery:** native/gsim `decisions` recovery was paid, with requested health threshold 0.7 and mana threshold 0.25. No independently optimized food, pull overlap or recovery policy is shown.

## Original 100/100 source-linked measurements

| Level | Seconds / 100 mobs | Seconds / mob | Executed native talent string | Executed source request SHA-256 |
| ---: | ---: | ---: | --- | --- |
| 47 | 777.700 | 7.777 | `0-0-2555355133000000` | `a75562cec87f83491428fd36ec303d6518d19adc58d9106f3bb4a8431f94876a` |
| 48 | 777.700 | 7.777 | `0-0-2555355133100000` | `dd1f4963fb5b2fd0eacf4ea8466729d37e224a728a6a76a087adb4c84d589383` |
| 49 | 779.700 | 7.797 | `0-0-2555355133110000` | `5673af77fe83b23f7d9e2a77329aa83d18c254d7ca27122e6610551ec726ec7c` |
| 50 | 785.700 | 7.857 | `0-0-2555355133120000` | `016044c4b988d0798a7020eff1abaf4e966e50f58f9e4cd1e6f586aaae62504b` |
| 51 | 787.700 | 7.877 | `0-0-2555355133121000` | `10b7f1b5649815ac65f2ba1bfac5ec9859970d3007bffae19a164f299b7fa73b` |
| 52 | 793.700 | 7.937 | `0-0-2555355133121100` | `1cdb60e400b9e932fd2b8373929e84d7727c48759d4d687c541709e41d727ea8` |
| 53 | 793.700 | 7.937 | `0-0-2555355133121200` | `7f73bd306610eb1dc20e050244e9d134e8b2534dae62ef1a824243b129d68800` |
| 54 | 795.700 | 7.957 | `0-0-2555355133121300` | `4bb1617bc77bf9b5686e435578c998ea223dbecd63790bcf5584830c7b603b50` |
| 55 | 799.900 | 7.999 | `0-0-2555355133121310` | `70069618ff3e3bdf3b5400a9fc0ac0919234aeae2e0492bd65d58cd7b576ed8a` |
| 56 | 803.900 | 8.039 | `0-0-2555355133121320` | `bc68ec5d3f56e1a627e5fe5395443690e5bf4927c4cf61744973a12d7a456395` |
| 57 | 803.900 | 8.039 | `0-0-2555355133121330` | `5c7096f0932f9fd55e46a5f0b1080311df17e5bcece9bbc67fd15d7b2fdcd20e` |
| 58 | 699.700 | 6.997 | `0-0-2555355133121340` | `c6af7da19e9bf079664b526062b4fbfda8eca8096ed7c697ee2b0716679461f2` |
| 59 | 773.700 | 7.737 | `0-0-2555355133121350` | `aeb357e515affdf4c66ed6c319c239e091320952fec31d2c6a09b0c9e9fbd7d2` |
| 60 | 711.700 | 7.117 | `0-0-2555355133121351` | `16824834bfcb0b65e2d0a1800d796a16939c012553c264fbffcc8242e2294320` |

**Scope limitations:** No cross-tree Affliction/Demonology comparisons at levels 48–60, no measured item/pet/APL search, no stat weights and no globally fastest or route-wide build claim. The separate [L47 three-family comparison](native_l47_paid_family_guide.md) measured a bounded counterfactual scenario and **must not** be conflated with this adjacent-level source sequence or treated as a paid respec transition.

**Reuse:** Original source request and raw native 100-target receipts remain in the linked ZIP only while that GitHub artifact is retained. This committed summary preserves player-relevant selected request fields, 14 result identities and verification checks; it is **not a replacement for the complete raw native receipts** or the canonical M1 ledger. Source/pet/mechanics legality is decided by native Rust, not re-checked here.