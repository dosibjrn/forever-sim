# Auxiliary command launchers

The original secondary command wrappers moved from the repository root in
[issue #14](https://github.com/dosibjrn/mage-level-sim/issues/14), phase 2A.

Run them from any working directory. Examples:

- `bash scripts/commands/run-validation-fast.sh`
- `bash scripts/commands/run-release-smoke.sh`
- `bash scripts/commands/service-start.sh`
- `bash scripts/commands/wowhead-capture.sh`
- `powershell -File scripts/commands/run-validation-v1.ps1`

All wrappers now locate the repository root relative to their own file.
Arguments, environment configuration and Python execution targets remain
unchanged. These are real commands that may start browsers or services;
CI uses an inert Python stub rather than invoking their side effects.

| Group | Relocated launchers |
| --- | --- |
| Validation | `run-validation-fast.{sh,ps1}`, `run-validation-v1.{sh,ps1}`, `run-validation-v2.{sh,ps1}`, `run-validation-v3.{sh,ps1}`, `run-validation-v4.sh`, `run-validation-v5.sh` |
| Smoke | `run-release-smoke.{sh,ps1}`, `run-listener-smoke.sh` |
| Service | `service-start.sh`, `service-stop.sh` |
| Captures | `talentsforever-capture.sh`, `wowhead-abilities-capture.sh`, `wowhead-capture-adaptive.sh`, `wowhead-capture.sh` |

## Alternate simulator runners — phase 2B

Ten alternate launchers were also relocated here. Their CLI flags and
Python targets stay the same; each resolves the repository root from its own
location regardless of the invoking working directory.

| Previously | Now |
| --- | --- |
| `run-fast.{sh,ps1}` | `scripts/commands/run-fast.{sh,ps1}` |
| `run-both.{sh,ps1}` | `scripts/commands/run-both.{sh,ps1}` |
| `run-forever.{sh,ps1}` | `scripts/commands/run-forever.{sh,ps1}` |
| `run-v2.{sh,ps1}` | `scripts/commands/run-v2.{sh,ps1}` |
| `run-mc.{sh,ps1}` | `scripts/commands/run-mc.{sh,ps1}` |

For example: `bash scripts/commands/run-both.sh --school frost` or
`pwsh -File scripts/commands/run-fast.ps1 -OptimizeOnly`.
`run-both.sh` still delegates to PowerShell on Git Bash, using its new path.

Release smoke wrappers run the **explicit** `tests/release/` suite. Standard
`pytest` ignores that folder; launch it deliberately with
`bash scripts/commands/run-release-smoke.sh` or its PowerShell counterpart.

Root `run.sh` and `run.ps1` are the **unchanged stable entry points**.
Update shortcuts or external callers using the removed alternative root paths.
