param(
    [string]$StateDir = $env:MATERIAL_FIT_PERSISTENT_STATE_DIR,
    [string]$WslDistro = "Ubuntu-24.04"
)

$ErrorActionPreference = "Stop"

if (-not $StateDir) {
    Write-Error "StateDir is required. Pass -StateDir or set MATERIAL_FIT_PERSISTENT_STATE_DIR."
    exit 2
}

$statePath = Resolve-Path -LiteralPath $StateDir -ErrorAction SilentlyContinue
if (-not $statePath) {
    exit 0
}

$stateDirFull = $statePath.Path
$full = [System.IO.Path]::GetFullPath($stateDirFull)
if ($full -notmatch "^([A-Za-z]):\\(.*)$") {
    exit 0
}
$drive = $Matches[1].ToLowerInvariant()
$rest = $Matches[2] -replace "\\", "/"
$stateWsl = "/mnt/$drive/$rest"

foreach ($name in @("worker.winpid", "server.winpid", "http.winpid")) {
    $pidFile = Join-Path $stateDirFull $name
    if (-not (Test-Path -LiteralPath $pidFile)) {
        continue
    }
    $pidText = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidText) {
        Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$scriptPath = Join-Path $stateDirFull "stop_wsl_worker.sh"
$script = @'
#!/usr/bin/env bash
set -uo pipefail
STATE="$1"
touch "$STATE/stop" 2>/dev/null || true
for name in worker.pid server.pid http.pid daemon_launcher.pid; do
  file="$STATE/$name"
  [ -s "$file" ] || continue
  pid="$(cat "$file" 2>/dev/null || true)"
  [ -n "$pid" ] || continue
  kill "$pid" 2>/dev/null || true
done
pgrep -f "$STATE/persistent_browser_worker.js|$STATE/persistent_capture_server.py" | while read -r pid; do
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
done
pgrep -f "python3 -m http.server .*remote_exact_snapshots.*webroot" | while read -r pid; do
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
done
pgrep -f "chrome-linux/chrome|chrome-headless-shell" | while read -r pid; do
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
done
sleep 0.5
for name in worker.pid server.pid http.pid daemon_launcher.pid; do
  file="$STATE/$name"
  [ -s "$file" ] || continue
  pid="$(cat "$file" 2>/dev/null || true)"
  [ -n "$pid" ] || continue
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$file"
done
pgrep -f "$STATE/persistent_browser_worker.js|$STATE/persistent_capture_server.py" | while read -r pid; do
  [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
done
pgrep -f "python3 -m http.server .*remote_exact_snapshots.*webroot" | while read -r pid; do
  [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
done
pgrep -f "chrome-linux/chrome|chrome-headless-shell" | while read -r pid; do
  [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
done
rm -f "$STATE/ready.json"
'@

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($scriptPath, ($script -replace "`r`n", "`n"), $utf8NoBom)
$scriptWsl = "/mnt/$drive/" + (($scriptPath.Substring(3)) -replace "\\", "/")
& wsl.exe -d $WslDistro -- bash $scriptWsl $stateWsl | Out-Null
exit 0
