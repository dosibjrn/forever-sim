param([Parameter(ValueFromRemainingArguments=$true)][string[]]$ExtraArgs)
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $repoRoot
& powershell -ExecutionPolicy Bypass -File (Join-Path $repoRoot 'run.ps1') @ExtraArgs
exit $LASTEXITCODE
