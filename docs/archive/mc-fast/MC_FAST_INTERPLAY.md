# Fast -> MC interplay

Fast is a proposal generator; MC remains the stochastic authority.

## What happens now

`./run-both.sh` (and `run-both.ps1`) runs the phases in this order:

1. Start the shared listener.
2. Run Fast analytic search first.
3. Fast writes `state/v2/mc_bridge/`:
   - `seeds/lvl_XX.json`: per-level analytic talent candidates,
   - `top_candidates.json`: complete legal 0/1/2-respec Fast paths,
   - `respec_schedules.json`: respec timing hints.
4. Start normal MC.
5. Before MC search starts, `run.sh` / `run.ps1`:
   - injects the Fast full paths into MC `top_candidates` as **unvalidated challengers**,
   - imports the Fast level seeds and respec schedules as guidance-only priors.
6. MC's existing startup replay stochastic-validates Fast full paths with the current simulator hash.
7. MC then continues its normal native search. Fast candidates do not replace native MC candidates.

So conceptually:

```
MC candidate universe = native MC proposals ∪ Fast proposals ∪ historical/cross-water priors
```

Fast analytic scores can never become authoritative MC BEST directly. A Fast path must pass the ordinary stochastic replay first.

## Commands

Fast only:

```bash
./run-fast.sh
```

This publishes/refreshes the bridge but does not start MC.

MC only:

```bash
./run-mc.sh
```

If a Fast bridge exists, MC automatically consumes it before starting. Otherwise MC behaves as before.

Integrated run:

```bash
./run-both.sh
```

On Windows/Git Bash this dispatches to the PowerShell launcher. Fast runs first (normally tens of seconds), then MC starts with Fast challengers already available.

## Safety / correctness contract

- Fast bridge values are proposal metadata only.
- Imported Fast numeric scores are never trusted by MC search authority.
- Full Fast paths are inserted as unvalidated cards.
- Current-hash stochastic replay is required before promotion to BEST.
- Per-level Fast candidates only widen/seed MC's existing search; they do not prune the native MC search space.

## Production Fast view

`run-fast` and `run-both` now use **smooth** (`normal2`) by default. `--view hard` is retained only as a debug/reference mode. Fast proposals are guidance only; MC native candidates remain in the pool and stochastic replay decides authority.
