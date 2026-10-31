$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..'))
python -m pytest -q tests/release
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
