# Generic registry, publication and route-navigation regressions

Seven existing tests were moved **byte-for-byte** from the flat `tests/`
directory. They exercise:

- G47/G47b: source registry, capabilities and route authority
- G48/G48a: all-class publication availability and listener coverage
- G48b/G48c: backend-neutral native route navigation and decisions
- G48d: product-level generic all-class decision surface

No moved file imports another `tests.*` module or derives data paths from
the location of the test file. Source-code inspection uses repository-root
working-directory paths, as before.

Run from the repository root:

```bash
python -m pytest -q tests/generic/publication
```

These tests are still discovered by default `python -m pytest -q`.
No separate GitHub Actions workflow was added while runner-allocation
issue #42 remains unresolved. The layout smoke does not substitute for
executing real assertions or obtaining PROCESS P1–P7 evidence.
