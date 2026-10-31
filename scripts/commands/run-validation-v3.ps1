$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..'))
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python tools/validate_v3_checkpoint_failure.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
