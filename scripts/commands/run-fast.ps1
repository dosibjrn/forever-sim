param(
    [switch]$OptimizeOnly,
    [Alias('listen')][switch]$ListenerOnly,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $repoRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
if (-not ($ExtraArgs -contains '--view') -and -not ($ExtraArgs | Where-Object { $_ -like '--view=*' })) { $ExtraArgs = @('--view','smooth') + $ExtraArgs }
$openPath = if (($ExtraArgs -contains 'forever') -or ($ExtraArgs | Where-Object { $_ -eq '--ruleset=forever' })) { '/decisions' } else { '/fast' }
if ($OptimizeOnly) { & python -m src.v2.runner @ExtraArgs; exit $LASTEXITCODE }
if ($ListenerOnly) { & python -m src.listener --open-path $openPath @ExtraArgs; exit $LASTEXITCODE }
$listener = Start-Process python -ArgumentList (@('-m','src.listener','--open-path',$openPath) + $ExtraArgs) -PassThru -NoNewWindow
try {
    & python -m src.v2.runner @ExtraArgs
    Write-Host '[fast] optimization complete; listener remains open (Ctrl-C to stop).'
    Wait-Process -Id $listener.Id
}
finally { if (!$listener.HasExited) { Stop-Process -Id $listener.Id -Force -ErrorAction SilentlyContinue } }
