# Generic search, frontier and policy regressions

Tests here exercise class-neutral legal candidate enumeration, source-backed
policy discovery, resource-aware priority selection, bounded search, generic
talent/gear frontiers and paid evaluation contracts.

The `wf_gen*` and `wf374*` regressions cover real source-driven action,
resource and pack-policy choices. These are **production-behavior regressions**,
not formal P1–P7.5 checkpoint certification. New tests belong here when their
subject is generic search behavior rather than a particular class, service
endpoint or gate.

Keep tests independent of their directory location: import production code by
`src.*`, resolve any repository-root files explicitly, and avoid imports from
other test modules. In particular, **audit `Path(__file__).resolve().parents[...]`
before moving a test**; a changed nesting level can silently point fixtures
outside the repository. Migration must also update any explicit CI/tool path.

Run from the repository root:

```bash
python -m pytest -q tests/generic/search
```

The suite also holds unchanged ClassModel/path-DP, V2 path-score and
stochastic path-validation input contracts, moved from the flat `tests/` root.
Those test modules use `src.*` imports and do not resolve paths relative to
their own files.

The directory is included in normal `pytest` collection
(`pytest.ini` sets `testpaths = tests`). Formal gate acceptance and M1 progress
remain owned by their production gate runners and Merge.

The retained V2 analytic scorer and analytic-frontier regressions are collected
here rather than in the flat `tests/` root; their test bodies are unchanged.
The focused PR job exercises these modules and the relocation layout check.
