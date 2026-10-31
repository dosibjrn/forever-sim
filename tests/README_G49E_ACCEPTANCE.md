# G49 acceptance — local / CI gate (v0.11.48.182)

Run from the unpacked **full** release root. Python, pytest, Playwright and a
system Chromium/Chrome executable are required. The browser must be allowed
to reach `http://127.0.0.1:<ephemeral-port>`; no browser request interception
is used by the native gate.

```bash
# Linux (defaults to /usr/bin/chromium)
python scripts/g49_acceptance_gate.py --report G49_ACCEPTANCE_REPORT.json

# macOS, with Google Chrome installed
WOW_CHROMIUM_EXECUTABLE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  python scripts/g49_acceptance_gate.py --report G49_ACCEPTANCE_REPORT.json

# Run just the native test for diagnosis (does NOT close G49 by itself)
python scripts/g49_acceptance_gate.py --stage native --report G49_NATIVE_ONLY.json
```

The runner executes four **separate processes**: fast selection/fail-closed
regressions and snapshot-integrity preflight; real promoted-generic HTTP;
all-class L10/L20 payload, Chromium UI and real service HTTP; and finally
unbridged native browser -> listener -> optimizer-service E2E.

Each stage emits pytest JUnit XML to a temporary directory; the runner parses
**test counts, failures, errors and skips**, checks the exit code, enforces a
bounded timeout and emits JSON with the actual result. An absent XML report,
zero collected tests, any skip or a blocked native socket is **not PASS**.
The full gate returns exit code 0 **only if all four stages PASS**. Running a
single stage can return 0 when that stage passes, but the JSON explicitly
reports `acceptance_passed: false` and missing stages.

When Chromium reports `net::ERR_BLOCKED_BY_ADMINISTRATOR`, the native test is
forced to FAIL with `WOW_REQUIRE_NATIVE_BROWSER_E2E=1`, and the JSON classifies
it as `BLOCKED`. No CI or handover should label G49 complete on this runner.

The route snapshots are release-version-bound and canonical. Do **not** copy
an older JSON snapshot and edit its version: regenerate using the canonical
Druid and melee writer functions before running the gate. The fast preflight
fails stale snapshots without triggering a costly live solve.
