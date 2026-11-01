param(
    [int]$Workers = 0,
    [int]$StartLevel = 11,
    [int]$EndLevel = 60,
    [switch]$NoListener
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $repoRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$common = @('--ruleset','forever','--start-level',"$StartLevel",'--end-level',"$EndLevel",'--view','smooth')
if ($Workers -gt 0) { $common += @('--workers',"$Workers") }
foreach ($cls in @('mage','paladin','druid')) {
    Write-Host "[forever] running $cls L$StartLevel->$EndLevel"
    & python -m src.v2.runner @common --class $cls
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if (-not $NoListener) {
    & python -m src.listener --open-path /decisions
}
