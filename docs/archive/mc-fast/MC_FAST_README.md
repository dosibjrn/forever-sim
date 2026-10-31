# Mage Optimizer: MC + Fast listener

The repository can run the old stochastic optimizer (**MC**) and the new analytic optimizer (**Fast**) side by side. They use separate runtime state:

- MC: existing `state/` tracks/cache/checkpoints
- Fast: `state/v2/viewer.json`

The browser listener is shared:

- `http://127.0.0.1:8765/` — MC
- `http://127.0.0.1:8765/fast` — Fast

The header links switch between the two views.

## Git Bash / bash

```bash
./run-mc.sh
./run-fast.sh
./run-both.sh
```

`run-fast.sh` now defaults to production `--view smooth`. Hard remains available only for debug/reference. To run both analytic views explicitly:

```bash
./run-fast.sh --view both
```

Useful modes:

```bash
./run-mc.sh --optimize-only
./run-fast.sh --optimize-only
./run-fast.sh --listener-only
```

`run-both.sh` starts both optimizers plus one listener. Stop with Ctrl-C.

For the normal Frost-primary workflow, use:

```bash
./run-both.sh --frost
```

This filters the primary rotation family, not talent-tree spending; cross-tree support talents such as Arcane Subtlety remain legal.

## PowerShell

```powershell
.\run-mc.ps1
.\run-fast.ps1
.\run-both.ps1
```

## Fast UI

The Fast page shows live phase/progress, hard/smooth view status, search/repair/DP timings, best analytic path, 0..N respec-budget solutions, and per-level build/policy leaders.

Fast is deterministic candidate search. MC remains the stochastic validation/search engine; the two state trees do not overwrite each other.

## Windows / Git Bash hotfix notes

`run-fast.sh` disables MSYS path conversion for `/fast`, so Git Bash does not rewrite it as `C:/Program Files/Git/fast`.

On native Windows the Fast optimizer defaults to `--workers 1`. This avoids `multiprocessing.spawn` / handle duplication failures when launched through Git Bash. You can explicitly try `--workers 2` or higher later, but the default is intentionally the robust mode.

In combined Fast+UI mode the listener is launched in the background and the Fast optimizer stays attached to the terminal. This is deliberate on Windows.


## 2026-09-10 Fast-core fix

The Fast structural beam now uses an O(1) mechanics proxy; it does not run the
fight kernel at every partial talent allocation. Continuity is repaired with
three guaranteed legal tree spines plus bounded forward trails. This guarantees
that the 0-respec DP has at least one complete path while keeping candidate
pools bounded.

On the reference container, the Windows-style single-worker command
`python -m src.v2.runner --view hard --workers 1` completed levels 11..59 in
about 26.5 s (search 17.6 s, repair 7.7 s, DP 0.54 s). Runtime on another CPU
will differ.

After DP completes, `/fast` shows the actual selected legal path per level,
including the talent added or RESPEC marker. During search it explicitly labels
rows as independent leaders rather than implying they form a legal path.

## Production Fast view

`run-fast` and `run-both` now use **smooth** (`normal2`) by default. `--view hard` is retained only as a debug/reference mode. Fast proposals are guidance only; MC native candidates remain in the pool and stochastic replay decides authority.
