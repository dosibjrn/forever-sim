# Hunter mechanics regression tests

This is a normally collected test group for WoW Forever Hunter:

- Beast Mastery, Marksmanship and Survival talent rules, including L21–40 coverage
- Pet family capability, focus and active-skill calculations
- Equipment selection, source-backed item catalogues, fixed-point gear weights
- Summon Hawk, melee/trap policies and post-level-20 mechanics

Fourteen existing tests were **moved byte-for-byte**. Their imports reference
`src.*`, not other test modules; no source-relative `__file__` paths needed
adjustment. The extra `test_hunter_mechanics_layout.py` checks layout only.

Run the group with:

```bash
python -m pytest -q tests/mechanics/hunter
```

Default `python -m pytest -q` still discovers these tests. The separate
`tests/release/` directory remains opt-in. The lightweight CI workflow
collects this group and runs narrow pet-rule regressions, not all integration
or full P1–P7 gates. Collection PASS is not a gameplay certification.
