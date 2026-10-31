# Rust BalancedRNG compile and 50-fight smoke — evidence

**Build gate: PASS**, probability-balanced combat and P7 acceptance **not yet certified**.

- WF636 CI: https://github.com/dosibjrn/mage-level-sim/actions/runs/40898989538 — PASS
- Pinned Rust upstream: `666fe17a42682068a3c8497d88d5fa3732cbdfb9`
- Modified source: `integrations/mythicsim-rust/wf636_apply_balanced.py` on `work/wf636-rust-balanced-backend`
- Artifact: `wf636-balanced-rust-linux-x64` from this CI run
- ELF Linux x86-64 SHA-256, verified locally: `8aca8c0c45849ad4e32e9fd73ffd32fb3d04a50627dd04c6c1975023a3f1604c`.
- Executable `forever-engine version` returned success.
- Exact same reconstructed Balance Druid request reduced to 50 iterations, seed 1179706472; Rust exit 0 in both modes:
  - `WOWSIM_RNG_MODE=stochastic`: 732.7657469839462 mean DPS, 45.09648364703939 stdev, average duration 118.47728137646 s.
  - `WOWSIM_RNG_MODE=balanced`: 762.9537114608602 mean DPS, 50 identical outcomes, 120 s duration. Result's `stdev` is NaN (identical sample outputs).
- The 50-run smoke does **not** demonstrate correct full hit-table balancing or parity. In particular, a fully identical fight sequence and constant fight duration reveal the current balanced RNG suppresses encounter-duration randomness. This needs deliberate validation before using it to select talent builds.
- Real source/compile logs are in the linked CI run. Full raw local smoke outputs have not yet been committed to this directory. Do not treat this README as equivalent raw logs.
- HOLD: no Rust probability-balancing gate PASS, no P7 certification, no optimizer integration.
