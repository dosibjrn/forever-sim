# Druid mechanics regression tests

This group contains **27 existing, byte-for-byte relocated** Forever Druid test
modules, covering Balance, Cat, Bear, talent schemas and modifiers,
rage/incoming damage, mana/healing/recovery, reference fixtures,
gear/catalogue and decision publication.

No moved module uses its `__file__` location to locate fixtures or imports
another `tests.*` module; imports remain absolute from the production
`src.*` packages. Historical skips (notably the retired independent
validator oracle) are preserved unmodified.

Run this group directly:

```bash
python -m pytest -q tests/mechanics/druid
```

Normal `pytest -q` still collects it. The slow `tests/release/` tests remain
opt-in. The scoped CI runs an AST/layout check, `pytest --collect-only` and
two narrow mechanics regression modules, not full P1–P7 acceptance gates.
