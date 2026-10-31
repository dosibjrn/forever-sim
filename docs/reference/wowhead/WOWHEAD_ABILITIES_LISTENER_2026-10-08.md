# Wowhead Forever spells & talents — now in the Listener

**Source baseline:** `mage_optimizer_v0.11.48.154_full.zip` (G38 complete). This is a source-data operator integration. **G39 is not marked done** and G40 is untouched. The software's internal version stays `.154` deliberately: no scorer/route semantics changed, so the version-fingerprinted Druid release snapshot remains valid.

## Where in the UI

Open the normal listener and expand **Optimizer service** (expanded by default). Under **Add item / Refresh all items** is an always-present **Wowhead · spells & talents** row:

- **Refresh all 9 class indexes** — headed Chrome/Playwright capture of 9 classes × 2 types, count checked. The active DB is not overwritten unless all 18 lists are verified and SQLite passes `quick_check`.
- **Fetch next 20 tooltips** — resume the latest verified batch; advance through the next missing 20 unique spell IDs, not the same first 20 again. Individual tooltip failures are retained as warnings while successfully verified pages are kept. Can be repeated; no full 2,663-page run required.
- **Source coverage** — latest batch ID; list count; index rows; tooltip details verified/unique IDs; capture progress, state and errors. These are *source facts*, not automatically executable engine effects or a talent tree.

The listener is an HTTP client; the optimizer service runs the capture. Both item and abilities captures use the existing persistent Chrome profile, and service admission rejects simultaneous jobs. No new parser was written: the existing `tools/capture_forever_abilities_sqlite.py` is reused and the detail-resume budget semantics corrected. The command-line `wowhead-abilities-capture.sh` remains a fallback.

## Initial imported data

Included snapshot from the uploaded files:

- `data/forever/catalogue/forever_abilities.sqlite`
- `data/forever/catalogue/wowhead_abilities_manifest_20261008T145657Z.json`
- 18/18 class lists, 2,724 total list entries, 2,663 distinct spell IDs, **0 spell detail pages**, 9 classes.

The original item DB `items_2026-09-29.sqlite` remains byte-for-byte unchanged (expected SHA-256 `d7d5a8519b227a761312bf4d1da56955b58184239a5a2ed7a06f84eb134dc854`).

## Routes and persistence

`GET /api/v1/abilities/refresh` returns `{catalogue, refresh}`; `POST /api/v1/abilities/refresh` with `{"mode":"index"}` or `{"mode":"details","max_details":20}` starts a background service task; the listener proxies via `POST /api/service/abilities/refresh` and reads via `/api/service`.

Jobs report `queued → capturing → verifying → publishing → completed/failed` (or `completed_with_warnings`). Status and log files are under `state/abilities_refresh/`. If the service restarts mid-capture, persisted status is reported as interrupted. New data is captured into a *private staging SQLite backup*; only a fully verified index is atomically published. Tooltips are also published only after existing class-list integrity checks pass. A failed index keeps the prior source DB.

## Setup

Keep running your normal `service-start.sh` / `run-all.sh` from the project root. Restart the service and listener after applying this patch so the new endpoint is available. The existing Chrome profile and `playwright` package are required, as for item refresh. Chrome must be available on the machine hosting the service. Do not run the separate CLI capture simultaneously.

These pages are scraped third-party source data, not verified Blizzard rules. The talent grid geometry, prerequisites, rank semantics, and executable class mechanics are separate work and must be confirmed before simulation.

## Validation (current machine)

- 31/31 completed focused API + listener + original item refresh + browser-capture tests PASS.
- Round-trip: Browser endpoint → Listener HTTP proxy → Optimizer service HTTP endpoint tested.
- Incremental detail pagination, incomplete staging rejection, and prior-DB preservation on capture failure tested.
- `compileall` and all listener inline JavaScript checked separately.
- A **new live Wowhead fetch from within the listener** was **not** run on this machine; the source input is your successfully completed 18-list capture. This UI integration does not claim G39 route closure.
