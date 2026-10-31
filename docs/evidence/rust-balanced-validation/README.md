# WF638 — 10,000-fight Rust Balanced RNG validation

## Actual execution (Linux x86-64)

Both runs used the **same** reconstructed Balance Druid `RaidSimRequest`, 10,000 iterations, seed 1179706472, 120±15s, with identical gear/talents, raid buffs, consumes and APL from WF633.

- Binary: CI `wf636-balanced-rust-linux-x64`, [workflow run 40898989538](https://github.com/dosibjrn/mage-level-sim/actions/runs/40898989538).
- Upstream source: `666fe17a42682068a3c8497d88d5fa3732cbdfb9`; balanced source modification committed in this branch.
- Command: `WOWSIM_RNG_MODE=<stochastic|balanced> ./forever-engine sim --request rust_request_reconstructed.json --gate`
- Both processes exit 0. Request SHA reported by Rust (both): `0023afdb69c13eac63e54411d9a22226e7d4e436b955ca5e7176718ee861286a`

| Property | stochastic | balanced |
| --- | ---: | ---: |
| Iterations | 10000 | 10000 |
| DPS mean | 728.1936126415858 | 762.9537114610237 |
| DPS standard deviation | 43.420319553486735 | NaN (constant outcomes) |
| DPS min | 564.3949947249073 | 762.9537114608593 |
| DPS max | 892.5425469650522 | 762.9537114608593 |
| Mean duration (seconds) | 119.93419465712509 | 120.0 |
| First iteration duration | 133.002693869 | 120.0 |

Balanced produces +4.7735% more DPS than stochastic; **do not infer an unbiased expectation from the balanced output**. 10,000 repeats of the same deterministic fight are not 10,000 independent estimates.

## Acceptance

- **PASS**: stochastic baseline exactly reproduces 728.1936126415858 DPS and reference standard deviation.
- **PASS**: both balanced and stochastic Rust executions complete.
- **FAIL / OPEN**: probability-balanced **categorical hit tables** and roll-site coverage are not implemented or audited in WF636.
- **OPEN**: test whether replacing continuous encounter-duration RNG with van-der-Corput `Float` produces acceptable duration integration (currently every fight is 120s).
- **OPEN**: evaluate accuracy vs stochastic on many independent scenarios and talent/gear variants, rather than equating zero variance with unbiasedness.

No P7 parity gate or completed BalancedRNG gate is claimed from these results.

The original raw Rust outputs are available in the session-generated local WF638 package; this Markdown is a summary, not a replacement for full logs.
