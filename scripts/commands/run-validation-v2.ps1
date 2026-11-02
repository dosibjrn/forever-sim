$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..'))
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:REQUIRE_CHROMIUM = '1'
python -m pytest -q -r s tests/test_v2_restart_persistence_v0114820.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
