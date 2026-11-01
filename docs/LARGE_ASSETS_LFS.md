# Large assets — Git LFS

**Verified public baseline (2026-11-01):** `forever-sim/main` contains 14 LFS pointers (11 SQLite databases and 3 historical JSON reports), with 85,792,142 hydrated bytes. An independent public checkout successfully hydrated all 14 and passed the 13/13 source-snapshot checks in [Actions run #41255246045](https://github.com/dosibjrn/forever-sim/actions/runs/41255246045). This migration is **complete**; do not treat pointers in the Git tree as missing payloads.

## Tracking policy

- Track `*.sqlite`, `*.sqlite3`, `*.db`, `*.bin`, `*.zip`, `*.npy`, `*.npz`, and `*.parquet` with Git LFS using the repository's `.gitattributes`.
- The three historic JSON exceptions are path-specific: `docs/validation/I15/LISTENER_LOCAL_I15_STATE_v0.11.48.103.json`, `evidence/wf325/WF325_BLIND_JOINT.json`, and `evidence/wf353/WF353_L30_DISCOVERED_STAGES.json`.
- Keep other JSON (configurations, evidence, manifests and requests) as reviewable Git text. Do **not** apply a blanket `*.json` LFS rule.
- Do not remove or rewrite evidence, source data or Git history to reduce the LFS count.

## New assets and verification

For a **new** large asset, verify that `.gitattributes` covers its path, run `git lfs install`, stage the asset with `git add`, and push its new commit with an authenticated LFS-capable client. An ordinary Git blob/pointer commit **does not prove** that an LFS payload was uploaded.

Verify with a **fresh** checkout (or a suitable GitHub Actions runner):

```bash
git lfs install
git lfs pull
git lfs ls-files
git lfs fsck
```

Check both pointer identity in Git and actual hydrated file bytes/checksums in the checkout. CI should use `actions/checkout@v4` with `lfs: true`; gate PASS still requires its own PROCESS-defined source, runtime and evidence validation.

## Provenance

The private read-only source snapshot was `dosibjrn/mage-level-sim` commit `3bd46df7e3b95a8a3bfdc7455de659341a905826`, published to the public repo in [commit `c04d089`](https://github.com/dosibjrn/forever-sim/commit/c04d0892060165663a937b0ece6c92cdb6591b7a). The historical recovery ZIP `feral_wf607_wf613_recovered_runtime.zip` was kept separately in the project file library and was **not** part of the 14 verified LFS entries. Historical migration instructions and earlier inventory are recoverable from Git history; no second conversion of the 14 existing files is required.
