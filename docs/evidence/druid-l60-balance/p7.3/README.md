# WF649 — Druid 60 Balance P7.3 native Rust talent discovery

## Verdict

**Native Rust discovery and >=99%-of-reference stochastic DPS: PASS.**
**Full P7.3 PROCESS gate: NOT CERTIFIED — live gsim-2D ↔ Rust causal world/action/ACK evidence absent.**
This evidence intentionally does not relabel Rust-only execution as live 2D production integration.

## Canonical saved reference

- Saved MythicSim report: `https://api.mythicsim.com/api/forever/ranking-sims/d9d85974-a1f7-4700-ab22-2335d767a944/report`
- Original `request` recovered over HTTPS by GitHub Actions WF648 (run `40923300963`, artifact `wf648-exact-balance-request`), **not reconstructed**.
- Raw pretty-printed source request bytes SHA-256: `e99b06e5aa891a941ac077643a4209ab8582c810b678df4ec2d47ac48c6c646a`.
- Canonical JSON request SHA-256 (sorted keys, compact JSON): `8cb0e76db54c407ffbfac2085f60c90d8763c80adc1d3fe26681d02dec5071a7`.
- Pinned Rust engine commit: `666fe17a42682068a3c8497d88d5fa3732cbdfb9`, binary SHA-256 `b055c25697ee4121a6a82f1ceb0fbfb53d61561f31c161a5680111c538632afb`.
- Standalone 10,000-fight Rust baseline: **728.1936126415858 DPS**, exact parity with saved external mean.
- Original talents: `5532220115501351--505`; reference gear 16 items and 10 APL priority actions frozen.

## 300-second independent attempts

| Property | Attempt 1 (initial optimizer) | Attempt 2 (independent corrected optimizer) |
|---|---:|---:|
| Seed | 647003 | 647004 |
| End-to-end wall seconds | 285.42816 | 285.41727 |
| Native Rust paid candidates | 8456 | **9691** |
| Native execution errors | 0 | **0** |
| Screening fights each | 100 | 100 |
| Best screening DPS | 702.927746 | **729.999412** |
| Independent stochastic holdout fights | 4000 | **4000** |
| Holdout DPS | 699.829867 | **725.420977** |
| Holdout SD | 41.350901 | **43.023112** |
| Reference tolerance floor (99%) | 720.911677 | **720.911677** |
| Native floor verdict | FAIL | **PASS** |

Attempts were independent cold starts; the saved reference talent vector was excluded from paid search. Attempt 2 expanded the talent budget across all three source talent trees rather than trapping the search in a narrow tree split. Attempt 1 output was *not* used to seed Attempt 2. Prepull, encounter, buffs/debuffs, consumes, gear (SHA-256 `ea438dcc1fa7a1b90c70fa8016197f2d087b91b0b38287f2f6582638628d4021`) and APL (SHA-256 `a9c790f13e9c59da358cbb771e1835ffba78735b92935595e28af5c9f0539d51`) remained unchanged across candidates.

## Selected candidate — Attempt 2

- Talent string: **`5522220115501351--41501`**.
- Tree totals: **40 Balance / 0 Feral / 11 Restoration**.
- Search score: **729.9994117896213 DPS** (100 fights, fixed search seed).
- Freeze made before holdout evaluation; independent holdout random seed: `1300647011`.
- Holdout mean: **725.4209773756572 DPS**, n=4000, SD=43.023111567481536.
- Mean vs external mean: -2.7726352659286 DPS (-0.381%).
- Mean vs 99%-of-reference floor: **+4.509300860487315 DPS**.
- One-sided 95% normal-approx lower confidence bound for `holdout mean − 0.99 × external mean`, accounting for independent 4000- and 10000-fight reference SEs: **+3.1857019028226685 DPS**. Formula `difference - z_0.95 * sqrt(SD_holdout^2/4000 + 0.99^2 * SD_reference^2/10000)`, with `z_0.95=1.6448536`.
- The search must not be re-seeded or resumed with this winning vector for a future gate's cold attempt.

## Reproduce

```bash
python -m unittest -v test_p73_native_search
python p73_talent_search_v2.py \
  --binary ./forever-engine \
  --reference ./saved_728_request.json \
  --outdir ./new_attempt \
  --seconds 300 --screen-iterations 100 --holdout-iterations 4000 --seed 647004
```

The archive includes `forever-engine` for Linux x86-64, frozen saved original request, both executable optimizer revisions, source-derived Druid talent schema, unit tests, original Rust baseline result, complete paid candidate logs, frozen winner input, full independent native holdout output, and machine-readable `report.json` for each attempt.

### Limitations

1. This is **native Rust** only, *not* a live interactive `gsim-2D↔Rust` P7.3 execution; complete gate remains unproven.
2. Talent legality is based on the project's source-backed `TALENT_RULES` (Druid schema build 1.60.1.70170), plus evidence-backed prerequisite for Vengeance; the reference runtime is newer and exact talent-data parity was not independently recertified.
3. Searches independently use RNG-selected legal builds. The search `WOWSIM_RNG_MODE=balanced` flag is passed but we did not separately prove the pinned Rust binary honors that flag; 4000-fight holdout uses stochastic RNG and an independent seed.
4. The screening uses 100 combat iterations, so screening values are noisy; winner is judged only by frozen holdout.

## WF650 corrective diagnosis (not a new certified P7.3 PASS)

The previously chosen WF649 winner `5522220115501351--41501` is a **screening winner, not a demonstrated optimum**. Replaying with the identical 10,000-fight Rust seeds establishes:

| Build | Seed 1179706472 | Seed 1300647011 |
|---|---:|---:|
| Saved reference 41/0/10 | 728.1936126 | 728.3027356 |
| WF649 selected 40/0/11 | 724.7037036 | 725.0237762 |

The selected build loses 3.49 and 3.28 DPS respectively. Fixed-seed 10,000-fight replays of the historical top 25 screening results revealed **exact DPS ties** for several irrelevant Restoration-rank substitutions, and an unselected `5332220115501351--415002` candidate scored 728.62251 DPS on the same seed (only +0.43 DPS vs reference; not a statistically proven real improvement). Thus the 100-fight screen suffered winner's curse and did not identify the strongest historical candidate.

**Fix:** The cold optimizer now reserves wall time to independently re-evaluate the top 40 screened candidates at **10,000 fights each** under a different, predeclared seed; it freezes the highest-ranked finalist **before** a further separate-seed 4,000-fight holdout. This is a real code change, not retroactive alteration of WF649's evidence. GitHub Actions tests cover the reranking stage. Full live 2D↔Rust causal evidence remains missing; do not promote the old P7.3 verdict to a certified gate.
