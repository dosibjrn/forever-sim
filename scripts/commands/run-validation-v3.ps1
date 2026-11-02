$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..'))
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python -m pytest -q -r s tests/test_v3_checkpoint_failure_semantics_v0114821.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
