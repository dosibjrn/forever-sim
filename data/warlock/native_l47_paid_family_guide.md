## L47 Warlock — native-paid talent-family comparison

This compares **counterfactual talent builds** in one fixed hostile native/gsim 100-mob scenario with paid recovery; it is not full leveling time.

Original evidence: [native run](https://github.com/dosibjrn/forever-sim/actions/runs/42836075370) · [paid 100-mob candidate artifact](https://github.com/dosibjrn/forever-sim/actions/runs/42836075370/artifacts/13774186358).
Selected native binary SHA-256: `133c96ba50b7589036e062e18a3315e28ac2562064cb99e96d501fc4ee054458`. Paid predecessor observation: `paid-source-native-L46-06e8cbb7073ae903b109-best_apl`.

**Fastest in this scenario: Destruction** (7.777 s/mob). This does not establish a route-wide spec winner.

### Measured native 100/100 candidates

- **Destruction** (candidate #3): **7.777 s/mob**, 777.700 s / 100 hostile kills; native talents `00000000000000000-0000000000000000000-2555355133100000`; observation `source-cross-tree-L47-011d0a27799e1c24317d-03-best_apl`.
  - Original source SHA-256: `0f8d375d43b13deb75d4199a659edf08af11216d21afc5e0e1d16b46ccc8dc65`; executed source SHA-256: `0f8d375d43b13deb75d4199a659edf08af11216d21afc5e0e1d16b46ccc8dc65`.
  - Native summary in [original artifact](https://github.com/dosibjrn/forever-sim/actions/runs/42836075370/artifacts/13774186358): `../cross-tree/world/candidate_03_0f8d375d43b1/native_l47/summary.json`. Respec from paid predecessor required: **no** (cost unmeasured).
  - Executed source request in original artifact: `cross-tree/world/candidate_03_0f8d375d43b1/native_l47/best_apl/source_request.json`.
  - Selected pet: **not recorded**; equipped item IDs in slot order: 260212, 22657, 22968, 19121, 0, 0, 20716, 22062, 22700, 22064, 275738, 275738, 0, 0, 22379, 19989, 275837 (0 = empty).
  - Ordered native APL: cast spell 6222 if DoT 6222 absent; cast spell 1014 if DoT 1014 absent; cast spell 1088.
  - Native-paid recovery: `{"health_threshold": 0.7, "mana_threshold": 0.25, "recovery_policy": "decisions"}`; mode `decisions_food_water`; reported recovery time 336.6 s; pull policy: **not recorded**.
- **Affliction** (candidate #1): **8.854 s/mob**, 885.400 s / 100 hostile kills; native talents `25522323135211100-0000000000000000000-0000000000000000`; observation `source-cross-tree-L47-011d0a27799e1c24317d-01-best_apl`.
  - Original source SHA-256: `dd4481c16a066bc8a76dfd2b3008b5393467c24be348c410be5c0b3d73add2e3`; executed source SHA-256: `dd4481c16a066bc8a76dfd2b3008b5393467c24be348c410be5c0b3d73add2e3`.
  - Native summary in [original artifact](https://github.com/dosibjrn/forever-sim/actions/runs/42836075370/artifacts/13774186358): `../cross-tree/world/candidate_01_dd4481c16a06/native_l47/summary.json`. Respec from paid predecessor required: **yes** (cost unmeasured).
  - Executed source request in original artifact: `cross-tree/world/candidate_01_dd4481c16a06/native_l47/best_apl/source_request.json`.
  - Selected pet: **not recorded**; equipped item IDs in slot order: 260212, 22657, 22968, 19121, 0, 0, 20716, 22062, 22700, 22064, 275738, 275738, 0, 0, 22379, 19989, 275837 (0 = empty).
  - Ordered native APL: cast spell 6222 if DoT 6222 absent; cast spell 1014 if DoT 1014 absent; cast spell 1088.
  - Native-paid recovery: `{"health_threshold": 0.7, "mana_threshold": 0.25, "recovery_policy": "decisions"}`; mode `decisions_food_water`; reported recovery time 319.9 s; pull policy: **not recorded**.
- **Demonology** (candidate #2): **9.517 s/mob**, 951.700 s / 100 hostile kills; native talents `00000000000000000-2355233231221310000-0000000000000000`; observation `source-cross-tree-L47-011d0a27799e1c24317d-02-best_apl`.
  - Original source SHA-256: `b2dac9d9d2ebad76b651f630beb390a6c5f66d4248e92403f54f89ddab2c7124`; executed source SHA-256: `b2dac9d9d2ebad76b651f630beb390a6c5f66d4248e92403f54f89ddab2c7124`.
  - Native summary in [original artifact](https://github.com/dosibjrn/forever-sim/actions/runs/42836075370/artifacts/13774186358): `../cross-tree/world/candidate_02_b2dac9d9d2eb/native_l47/summary.json`. Respec from paid predecessor required: **yes** (cost unmeasured).
  - Executed source request in original artifact: `cross-tree/world/candidate_02_b2dac9d9d2eb/native_l47/best_apl/source_request.json`.
  - Selected pet: **not recorded**; equipped item IDs in slot order: 260212, 22657, 22968, 19121, 0, 0, 20716, 22062, 22700, 22064, 275738, 275738, 0, 0, 22379, 19989, 275837 (0 = empty).
  - Ordered native APL: cast spell 6222 if DoT 6222 absent; cast spell 1014 if DoT 1014 absent; cast spell 1088.
  - Native-paid recovery: `{"health_threshold": 0.7, "mana_threshold": 0.25, "recovery_policy": "decisions"}`; mode `decisions_food_water`; reported recovery time 323.7 s; pull policy: **not recorded**.

**Limitations:** Respec execution and cost, continuous L46→L47 ancestry, full L10–60 optimal route, stat weights and M1 gate certification are **not measured by this comparison**. Do not infer those from the observed 100-mob times.
