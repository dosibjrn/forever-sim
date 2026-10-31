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

$openPath = if (($ExtraArgs -contains 'forever') -or ($ExtraArgs | Where-Object { $_ -eq '--ruleset=forever' })) { '/decisions' } else { '/fast' }
if ($OptimizeOnly) {
    & python -m src.v2.runner @ExtraArgs
    exit $LASTEXITCODE
}
if ($ListenerOnly) {
    & python -m src.listener --open-path $openPath @ExtraArgs
    exit $LASTEXITCODE
}

$p = Start-Process python -ArgumentList (@('-m','src.v2.runner') + $ExtraArgs) -PassThru -NoNewWindow
try {
    & python -m src.listener --open-path $openPath @ExtraArgs
} finally {
    if (!$p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
}
