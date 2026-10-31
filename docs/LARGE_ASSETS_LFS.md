# Large assets — Git LFS storage policy and migration

**Current status:** `.gitattributes` is configured, but pre-existing normal Git
blobs are **not** converted merely by adding attributes. Do not label these
assets as migrated until the LFS pointers have been committed **and the actual
objects have been uploaded and fetched back successfully**.

**P0 prerequisite (public `forever-sim`, issue #25):** the public main snapshot
is still incomplete as of 2026-11-01: ten SQLite payloads and two large JSON
payloads remain absent. First finish the authenticated, audited source-state
transfer and verify the *hydrated bytes* and hashes against the approved source
SHA. Do **not** start a public-main LFS conversion from a partial snapshot or
mistake Git LFS pointer text for a working SQLite database. Keep the historical
private repository read-only. The separate LFS conversion is issue #5, **after**
P0 parity and a successful public manual runner smoke.

## Assets and scope

- All current tracked SQLite databases (`*.sqlite`), future `*.sqlite3`,
  `*.db`, `*.bin`, `*.zip`, `*.npy`, `*.npz`, `*.parquet`: LFS.
- Three unusually large historical JSON dumps are path-specific LFS files:
  `docs/validation/I15/LISTENER_LOCAL_I15_STATE_v0.11.48.103.json`,
  `evidence/wf325/WF325_BLIND_JOINT.json`,
  `evidence/wf353/WF353_L30_DISCOVERED_STAGES.json`.
- All other JSON (config, ordinary run evidence, manifests) **remains text in
  Git** for diffability and review. No broad `*.json` LFS rule.
- **Historical private-source inventory**, not a claim about public main:
  14 tracked candidates / 85,792,142 bytes (11 SQLite databases + 3 large
  historical JSONs). Recalculate and verify the public inventory after P0.
- Untracked historical recovery file:
  `feral_wf607_wf613_recovered_runtime.zip` (10,635,591 bytes)
  is in the project file library, **not yet in GitHub or Git LFS**.
  Its compiled CLI may alternatively be retained as a pinned CI artifact.

## Convert the already-tracked files (separate worker branch)

**Do this only after P0 source/data parity and the public manual runner smoke.**
Requires a local clone of `dosibjrn/forever-sim` or an environment with
authenticated `git lfs push`. Use a clean worktree based on the verified public
main commit containing these attributes:

```bash
git fetch origin
git switch -c work/lfs-migrate-existing origin/main
git lfs install
git status --short                     # must be clean before continuing

# Re-apply the newly introduced LFS clean filters to tracked paths.
git add --renormalize .

# Only the intended LFS assets should be staged. Never include unrelated
# code/evidence or an accidental generated source edit.
git diff --cached --name-status
git diff --cached --check
git commit -m "Data: convert existing large tracked assets to Git LFS"
git push -u origin work/lfs-migrate-existing
```

**Verification before PR merge:**

1. On GitHub, check the new commit stores *LFS pointers*, not original binary
   contents: `git show HEAD:data/forever/catalogue/forever_abilities.sqlite`
   begins with `version https://git-lfs.github.com/spec/v1`, an
   `oid sha256:...` and `size ...`. Verify this for **all 14 candidates**.
2. Fresh checkout using `git lfs pull` or `actions/checkout@v4` with
   `lfs: true`; the actual file bytes (not pointers) must be present. Match
   each file's SHA-256 to its pointer `oid` and byte size to its `size`.
3. Run CI including real P1/P2 gates: in particular the canonical
   `forever_abilities.sqlite` must still be readable by SQLite.
4. Confirm Git LFS objects are visible in the remote, uploaded without errors.
   Only then merge the dedicated *data-only* PR.
5. This is **history-preserving**. Existing historical Git blobs are not
   removed from old commits; eliminating old history requires a separately
   approved history rewrite, which is **not authorized**.

For the recovered Feral 10.6 MB ZIP, add it from a local authenticated
checkout with `git lfs track '*.zip'` already active, then
`git add docs/evidence/druid-p7/archives/feral_wf607_wf613_recovered_runtime.zip`,
`git commit` and `git push` to its own branch. Avoid using the normal
GitHub Contents API: it writes a regular Git blob and does not upload the
required remote LFS object.

## Cloning and CI

```bash
git lfs install
git clone https://github.com/dosibjrn/forever-sim.git
cd forever-sim
git lfs pull
git lfs ls-files
```

Until P0 is accepted, this public checkout may lack the twelve source payloads
listed above. `git lfs pull` cannot restore objects that were never published.
The historical `mage-level-sim` repository is an audit-only source, **not** a
new work branch or LFS-conversion target.

After the public runner smoke succeeds, enable only reviewed gate workflows.
Every CI job requiring LFS-backed catalogues must explicitly use
`actions/checkout@v4` with `lfs: true` and prove the hydrated SQLite bytes are
readable; do not infer this from a checkout setting or a green compile.
Keep engine binary distribution via pinned GitHub Actions artifacts whenever
possible.

See [repository structure](REPOSITORY_STRUCTURE.md).
