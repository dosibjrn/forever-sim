param(
  [switch]$OptimizeOnly,
  [Alias('listen')][switch]$ListenerOnly,
  [int]$Workers = 0,
  [ValidateSet("both","buy_water","conjured_water")]
  [string]$WaterMode = "both",
  [ValidateSet("all","frost","fire","arcane")]
  [string]$School = "all",
  [switch]$Frost,
  [string[]]$ImportStateDir = @()
)
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
if ($Frost) {
  if ($School -ne 'all' -and $School -ne 'frost') { throw "-Frost conflicts with -School $School" }
  $School = 'frost'
}
$optimizerArgs = @('--water-mode', $WaterMode, '--school', $School)
$defaultImportStateDir = Join-Path $PSScriptRoot 'state-hide-2026-07-09-1907'
if (Test-Path -LiteralPath $defaultImportStateDir -PathType Container) {
  $optimizerArgs += @('--import-state-dir', $defaultImportStateDir)
} else {
  Write-Warning "Optional old state not found: $defaultImportStateDir (continuing without it)"
}
if ($Workers -gt 0) { $optimizerArgs += @('--workers', "$Workers") }
foreach ($p in $ImportStateDir) { $optimizerArgs += @('--import-state-dir', $p) }
$fastBridgeDir = Join-Path $PSScriptRoot 'state\v2\mc_bridge'
$fastBridgeTop = Join-Path $fastBridgeDir 'top_candidates.json'
if (-not $ListenerOnly -and (Test-Path -LiteralPath $fastBridgeTop -PathType Leaf)) {
  try { & python -m src.v2.mc_bridge --inject }
  catch { Write-Warning "Fast->MC challenger injection failed: $_" }
  $optimizerArgs += @('--import-state-dir', $fastBridgeDir)
}
if ($OptimizeOnly) {
  python -m src.master_optimizer @optimizerArgs
  exit $LASTEXITCODE
}
if ($ListenerOnly) {
  python -m src.listener
  exit $LASTEXITCODE
}
$opt = Start-Process python -ArgumentList (@('-m','src.master_optimizer') + $optimizerArgs) -PassThru -NoNewWindow
try { python -m src.listener }
finally { if (!$opt.HasExited) { Stop-Process -Id $opt.Id } }
