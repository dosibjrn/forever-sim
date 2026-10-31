# Balance Druid L60 — P7.3 WF663 outcome (owner-accepted 1% point-estimate tolerance)

## Frozen native search result
- Pinned external saved-reference DPS: **728.1936126415858**.
- Owner-accepted 1% point-estimate floor: **720.91167651517 DPS** (explicit exception to the PROCESS P7.3 exact-reference threshold).
- WF663 300-second budget; elapsed **263.0 s**; **7,255** paid candidates; zero native execution failures.
- Winner talent string: **5432220115501351--505001**.
- Frozen independent stochastic holdout: **729.388 DPS**, **4,000 fights**, above the saved external reference by approximately **0.164%**.
- Search: balanced RNG; finalist reranking: stochastic (10,000 fights per evaluated finalist); final holdout: stochastic and separately seeded.
- Actions evidence: https://github.com/dosibjrn/mage-level-sim/actions/runs/40968227205 (artifact `wf663-p73-native-evidence`).
- CI contract and preflight successful for WF662; native run WF663 successful.
- WF664 fixes the single Rust `private_interfaces` warning (`BalancedRng` visibility); subsequent CI validation belongs to that commit.

## Gate accounting, without silently relaxing policy
**Owner-accepted native DPS result: PASS.** This does **not** certify a full PROCESS P7.3 gate:
- PROCESS states P7.3 requires the same genuine live 2D + native pipeline; no live gsim 2D↔Rust ACK/causal trace is supplied by WF663.
- The owner-accepted 1% allowance is an explicit management decision, not a change to the canonical PROCESS P7.3 exact-reference acceptance rule.
- Statistical confidence and complete raw runs should be reviewed independently; do not claim formal confidence-based equivalence based on a point estimate alone.
- The WF663 artifact is stored by GitHub Actions rather than committed in this branch. Preserve its retention and provenance.

Next: independent P7.4 **gear discovery**, keeping saved reference talents and rotation frozen. Do not warm-start with reference gear, and do not claim that a native-only run proves the live 2D integration.
