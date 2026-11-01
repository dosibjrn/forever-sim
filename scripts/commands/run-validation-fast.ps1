$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..'))
python tools/validate_fast.py
exit $LASTEXITCODE
