# G49d native browser-socket E2E gate

```bash
WOW_REQUIRE_NATIVE_BROWSER_E2E=1 pytest -q tests/test_g49d_native_browser_e2e.py -x
```

Requires unrestricted Chromium access to `http://127.0.0.1:<ephemeral_port>`.
Production browser app, localStorage, real listener HTTP and real optimizer
service HTTP are used. A test-only product-complete Druid L10 provider is
injected; production auto eligibility is unchanged. The costly result builder
is replaced by a small decision body, **not** the backend selector.

When this environment's Chromium returns `ERR_BLOCKED_BY_ADMINISTRATOR`, the
regular suite marks the gate **SKIPPED**, not PASS. Setting the strict environment
variable makes that condition FAIL. No Playwright HTTP request bridge or
`window.fetch` stub is used in this test.

G49 exit remains blocked until this test passes in a network-capable runner,
and the slow G48d all-class service/browser gate completes cleanly.
