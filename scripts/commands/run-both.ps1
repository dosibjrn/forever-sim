param(
    [ValidateSet('all','frost','fire','arcane')]
    [string]$School = 'all',
    [switch]$Frost
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $repoRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
if ($Frost) {
    if ($School -ne 'all' -and $School -ne 'frost') { throw "-Frost conflicts with -School $School" }
    $School = 'frost'
}

$listener = Start-Process python -ArgumentList @('-m','src.listener','--open-path','/fast') -PassThru -NoNewWindow
try {
    Write-Host "[both] phase 1/2: Fast analytic proposal search (school=$School)"
    & python -m src.v2.runner --view smooth --workers 1 --school $School
    if ($LASTEXITCODE -ne 0) { throw "Fast optimizer exited with code $LASTEXITCODE" }

    Write-Host "[both] phase 2/2: MC search (school=$School; native candidates + Fast challengers/priors)"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot 'run.ps1') -OptimizeOnly -School $School
    if ($LASTEXITCODE -ne 0) { throw "MC optimizer exited with code $LASTEXITCODE" }
}
finally {
    if (!$listener.HasExited) { Stop-Process -Id $listener.Id -Force -ErrorAction SilentlyContinue }
}
