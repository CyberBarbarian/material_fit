param(
    [string]$StateDir = $env:MATERIAL_FIT_PERSISTENT_STATE_DIR
)

$ErrorActionPreference = "Stop"

if (-not $StateDir) {
    throw "StateDir is required. Pass -StateDir or set MATERIAL_FIT_PERSISTENT_STATE_DIR."
}

$stateDirFull = [System.IO.Path]::GetFullPath($StateDir)
$pidFile = Join-Path $stateDirFull "daemon.pid"
$readyFile = Join-Path $stateDirFull "ready.json"
if (Test-Path -LiteralPath $pidFile) {
    $pidText = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidText) {
        $process = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
        if ($process) {
            & taskkill /F /T /PID $process.Id | Out-Null
            $remaining = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($LASTEXITCODE -ne 0 -and $remaining) {
                throw "Failed to stop persistent queue process $($process.Id) (exit $LASTEXITCODE)."
            }
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $readyFile -Force -ErrorAction SilentlyContinue
