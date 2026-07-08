param(
    [string]$StateDir = $env:MATERIAL_FIT_PERSISTENT_STATE_DIR,
    [string]$RemoteArtifactRoot = "",
    [string]$WebRoot = "",
    [string]$HostName = "127.0.0.1",
    [int]$CapPort = $(if ($env:CAP_PORT) { [int]$env:CAP_PORT } else { 8787 }),
    [int]$HttpPort = $(if ($env:HTTP_PORT) { [int]$env:HTTP_PORT } else { 18080 }),
    [string]$ChromeGlMode = $(if ($env:CHROME_GL_MODE) { $env:CHROME_GL_MODE } else { "egl" }),
    [int]$TimeoutSec = $(if ($env:CAP_TIMEOUT_SEC) { [int]$env:CAP_TIMEOUT_SEC } else { 240 }),
    [int]$PollMs = $(if ($env:CAP_POLL_MS) { [int]$env:CAP_POLL_MS } else { 10 }),
    [string]$NodeModules = "",
    [string]$ExactNodeBinWsl = "/home/alltr/.cache/material_fit_remote/runtime_exact/tools/node-v20.19.3-linux-x64/bin/node",
    [string]$ExactNodeModulesWsl = "/home/alltr/.cache/material_fit_remote/runtime_exact/playwright/node_modules",
    [string]$ChromeExe = "/home/alltr/.cache/material_fit_remote/ms-playwright/chromium-1228/chrome-linux/chrome",
    [object]$ChromeHeadless = $true,
    [object]$CleanBeforeStart = $true,
    [string]$WslDistro = "Ubuntu-24.04"
)

$ErrorActionPreference = "Stop"

function Convert-ToBool {
    param([object]$Value)
    if ($Value -is [bool]) {
        return $Value
    }
    if ($null -eq $Value) {
        return $false
    }
    $text = ([string]$Value).Trim()
    if ($text -eq "" -or $text -ieq "false" -or $text -eq "0" -or $text -ieq "no") {
        return $false
    }
    return $true
}

function Resolve-RequiredPath {
    param([string]$PathText, [string]$Name)
    if (-not $PathText) {
        Write-Error "$Name is required."
        exit 2
    }
    $resolved = Resolve-Path -LiteralPath $PathText -ErrorAction SilentlyContinue
    if (-not $resolved) {
        Write-Error "$Name does not exist: $PathText"
        exit 2
    }
    return $resolved.Path
}

function ConvertTo-WslPath {
    param([string]$WindowsPath)
    $full = [System.IO.Path]::GetFullPath($WindowsPath)
    if ($full -notmatch "^([A-Za-z]):\\(.*)$") {
        throw "Only drive-letter Windows paths are supported for WSL mapping: $WindowsPath"
    }
    $drive = $Matches[1].ToLowerInvariant()
    $rest = $Matches[2] -replace "\\", "/"
    return "/mnt/$drive/$rest"
}

function Quote-Bash {
    param([string]$Text)
    return "'" + ($Text -replace "'", "'\''") + "'"
}

if (-not $StateDir) {
    Write-Error "StateDir is required. Pass -StateDir or set MATERIAL_FIT_PERSISTENT_STATE_DIR."
    exit 2
}

$CleanBeforeStart = Convert-ToBool -Value $CleanBeforeStart
$ChromeHeadless = Convert-ToBool -Value $ChromeHeadless

$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
if (-not $RemoteArtifactRoot) {
    $RemoteArtifactRoot = Join-Path $repoRoot.Path "artifacts\remote_repro_audit_20260707_202817"
}
if (-not $WebRoot) {
    $WebRoot = Join-Path $RemoteArtifactRoot "remote_web_current_exact\web_localpkg_20260702_212056"
}
if (-not $NodeModules) {
    $NodeModules = Join-Path $repoRoot.Path "artifacts\real_laya_run\node_modules"
}

$artifactRootFull = Resolve-RequiredPath -PathText $RemoteArtifactRoot -Name "RemoteArtifactRoot"
$webRootFull = Resolve-RequiredPath -PathText $WebRoot -Name "WebRoot"
$nodeModulesFull = Resolve-RequiredPath -PathText $NodeModules -Name "NodeModules"
$workerSourceDir = Join-Path $artifactRootFull "remote_run_persistent_state_exact"
if (-not (Test-Path -LiteralPath (Join-Path $workerSourceDir "persistent_capture_server.py"))) {
    $workerSourceDir = Join-Path $artifactRootFull "success_run\persistent_worker_state_inspection_only"
}
$serverSource = Resolve-RequiredPath -PathText (Join-Path $workerSourceDir "persistent_capture_server.py") -Name "persistent_capture_server.py"
$workerSource = Resolve-RequiredPath -PathText (Join-Path $workerSourceDir "persistent_browser_worker.js") -Name "persistent_browser_worker.js"

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$stateDirFull = (Resolve-Path -LiteralPath $StateDir).Path
$queueDir = Join-Path $stateDirFull "queue"
$resultDir = Join-Path $stateDirFull "results"
$logDir = Join-Path $stateDirFull "logs"
$readyFile = Join-Path $stateDirFull "ready.json"
$stopFile = Join-Path $stateDirFull "stop"
$serverScript = Join-Path $stateDirFull "persistent_capture_server.py"
$workerScript = Join-Path $stateDirFull "persistent_browser_worker.js"
$managedFile = Join-Path $stateDirFull "managed_processes.json"

New-Item -ItemType Directory -Force -Path $queueDir, $resultDir, $logDir | Out-Null

$stopScript = Join-Path $PSScriptRoot "stop_remote_style_laya_worker_wsl.ps1"
if ($CleanBeforeStart -and (Test-Path -LiteralPath $stopScript)) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -StateDir $stateDirFull -WslDistro $WslDistro | Out-Null
    Remove-Item -LiteralPath (Join-Path $queueDir "*.request.json") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $queueDir "*.tmp") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $resultDir "*.result.json") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $resultDir "*.tmp") -Force -ErrorAction SilentlyContinue
}

Remove-Item -LiteralPath $readyFile, $stopFile -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $serverSource -Destination $serverScript -Force
Copy-Item -LiteralPath $workerSource -Destination $workerScript -Force
$exactRuntimeAvailable = $false
try {
    $exactCheck = "test -x " + (Quote-Bash $ExactNodeBinWsl) + " -a -d " + (Quote-Bash $ExactNodeModulesWsl)
    & wsl.exe -d $WslDistro -- bash -lc $exactCheck >$null 2>$null
    $exactRuntimeAvailable = ($LASTEXITCODE -eq 0)
} catch {
    $exactRuntimeAvailable = $false
}

$workerText = Get-Content -Raw -Encoding UTF8 -LiteralPath $workerScript
if (-not $exactRuntimeAvailable) {
    $workerText = $workerText -replace "require\('playwright'\)", "require('playwright-chromium')"
}
$wslPathPatch = @'
function windowsPathToWsl(value) {
  if (typeof value !== 'string') return value;
  const match = value.match(/^([A-Za-z]):[\\/](.*)$/);
  if (!match) return value;
  const drive = match[1].toLowerCase();
  const rest = match[2].replace(/\\/g, '/');
  return `/mnt/${drive}/${rest}`;
}
function translateWindowsPaths(value) {
  if (Array.isArray(value)) return value.map(translateWindowsPaths);
  if (value && typeof value === 'object') {
    const out = {};
    for (const [key, item] of Object.entries(value)) out[key] = translateWindowsPaths(item);
    return out;
  }
  return windowsPathToWsl(value);
}
function normalizeReferenceUrls(command) {
  const refs = command && command.browser_score && command.browser_score.reference_images;
  if (Array.isArray(refs)) {
    for (const ref of refs) {
      if (ref && typeof ref === 'object' && ref.path) delete ref.url;
    }
  }
  return command;
}
'@
$workerText = $workerText -replace "async function processRequest\(page, fileName\) \{", ($wslPathPatch + "`nasync function processRequest(page, fileName) {")
$workerText = $workerText.Replace("  const command = request.command;", "  const command = normalizeReferenceUrls(translateWindowsPaths(request.command || {}));")
$workerText = $workerText.Replace("    const captureCount = fs.readdirSync(command.output_dir).filter(name => {", "    const captureDir = captureCommand.output_dir || command.output_dir;`n    const captureCount = fs.readdirSync(captureDir).filter(name => {")
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($workerScript, $workerText, $utf8NoBom)

$stateWsl = ConvertTo-WslPath -WindowsPath $stateDirFull
$webWsl = ConvertTo-WslPath -WindowsPath $webRootFull
$fallbackNodeModulesWsl = ConvertTo-WslPath -WindowsPath $nodeModulesFull
$nodeModulesWsl = if ($exactRuntimeAvailable) { $ExactNodeModulesWsl } else { $fallbackNodeModulesWsl }
$nodeBin = if ($exactRuntimeAvailable) { $ExactNodeBinWsl } else { "/home/alltr/.nvm/versions/node/v24.15.0/bin/node" }
$headlessValue = if ($ChromeHeadless) { "1" } else { "0" }

$startScript = Join-Path $stateDirFull "start_wsl_worker.sh"
$startScriptText = @'
#!/usr/bin/env bash
set -euo pipefail
STATE="$1"
WEB="$2"
NODE_MODULES="$3"
HOST="$4"
HTTP_PORT="$5"
CAP_PORT="$6"
CHROME_GL_MODE="$7"
CHROME_HEADLESS="$8"
CHROME_EXE="$9"
TIMEOUT_SEC="${10}"
POLL_MS="${11}"

QUEUE_DIR="$STATE/queue"
RESULT_DIR="$STATE/results"
LOG_DIR="$STATE/logs"
READY_FILE="$STATE/ready.json"
STOP_FILE="$STATE/stop"
mkdir -p "$QUEUE_DIR" "$RESULT_DIR" "$LOG_DIR"
rm -f "$READY_FILE" "$STOP_FILE"

nohup python3 -m http.server "$HTTP_PORT" --bind "$HOST" --directory "$WEB" > "$LOG_DIR/http_server.log" 2> "$LOG_DIR/http_server.err.log" &
echo $! > "$STATE/http.pid"
nohup python3 "$STATE/persistent_capture_server.py" --host "$HOST" --port "$CAP_PORT" > "$LOG_DIR/persistent_capture_server.log" 2> "$LOG_DIR/persistent_capture_server.err.log" &
echo $! > "$STATE/server.pid"

export STATE_DIR="$STATE"
export QUEUE_DIR="$QUEUE_DIR"
export RESULT_DIR="$RESULT_DIR"
export READY_FILE="$READY_FILE"
export STOP_FILE="$STOP_FILE"
export LOG_DIR="$LOG_DIR"
export WEB_URL="http://${HOST}:${HTTP_PORT}/index.html"
export CAP_PORT="$CAP_PORT"
export HTTP_PORT="$HTTP_PORT"
export CHROME_GL_MODE="$CHROME_GL_MODE"
export CHROME_HEADLESS="$CHROME_HEADLESS"
export CHROME_EXE="$CHROME_EXE"
export CAP_TIMEOUT_SEC="$TIMEOUT_SEC"
export CAP_POLL_MS="$POLL_MS"
export NODE_PATH="$NODE_MODULES"
export PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/material_fit_remote/ms-playwright"
export PATH="$HOME/.nvm/versions/node/v24.15.0/bin:$PATH"
NODE_BIN="$HOME/.nvm/versions/node/v24.15.0/bin/node"
if [ ! -x "$NODE_BIN" ]; then
  NODE_BIN="$(command -v node)"
fi
echo "$NODE_BIN" > "$LOG_DIR/node_path.log"
"$NODE_BIN" -v >> "$LOG_DIR/node_path.log" 2>&1

nohup "$NODE_BIN" "$STATE/persistent_browser_worker.js" > "$LOG_DIR/daemon_stdout.log" 2> "$LOG_DIR/daemon_stderr.log" &
echo $! > "$STATE/worker.pid"
'@
[System.IO.File]::WriteAllText($startScript, ($startScriptText -replace "`r`n", "`n"), $utf8NoBom)
$httpStdout = Join-Path $logDir "http_server.log"
$httpStderr = Join-Path $logDir "http_server.err.log"
$serverStdout = Join-Path $logDir "persistent_capture_server.log"
$serverStderr = Join-Path $logDir "persistent_capture_server.err.log"
$workerStdout = Join-Path $logDir "daemon_stdout.log"
$workerStderr = Join-Path $logDir "daemon_stderr.log"
Remove-Item -LiteralPath $httpStdout, $httpStderr, $serverStdout, $serverStderr, $workerStdout, $workerStderr -Force -ErrorAction SilentlyContinue

$httpService = Join-Path $stateDirFull "http_service.sh"
$serverService = Join-Path $stateDirFull "capture_service.sh"
$workerService = Join-Path $stateDirFull "worker_service.sh"
$nodeBinDir = $nodeBin -replace "/[^/]+$", ""
$httpServiceText = "#!/usr/bin/env bash`nexec python3 -m http.server $HttpPort --bind $(Quote-Bash $HostName) --directory $(Quote-Bash $webWsl)`n"
$serverServiceText = "#!/usr/bin/env bash`nexec python3 $(Quote-Bash "$stateWsl/persistent_capture_server.py") --host $(Quote-Bash $HostName) --port $CapPort`n"
$workerServiceText = @"
#!/usr/bin/env bash
export STATE_DIR=$(Quote-Bash $stateWsl)
export QUEUE_DIR=$(Quote-Bash "$stateWsl/queue")
export RESULT_DIR=$(Quote-Bash "$stateWsl/results")
export READY_FILE=$(Quote-Bash "$stateWsl/ready.json")
export STOP_FILE=$(Quote-Bash "$stateWsl/stop")
export LOG_DIR=$(Quote-Bash "$stateWsl/logs")
export WEB_URL=$(Quote-Bash ('http://' + $HostName + ':' + $HttpPort + '/index.html'))
export CAP_PORT=$CapPort
export HTTP_PORT=$HttpPort
export CHROME_GL_MODE=$(Quote-Bash $ChromeGlMode)
export CHROME_HEADLESS=$headlessValue
export CHROME_EXE=$(Quote-Bash $ChromeExe)
export CAP_TIMEOUT_SEC=$TimeoutSec
export CAP_POLL_MS=$PollMs
export NODE_PATH=$(Quote-Bash $nodeModulesWsl)
export PLAYWRIGHT_BROWSERS_PATH="`$HOME/.cache/material_fit_remote/ms-playwright"
export PATH="$(Quote-Bash $nodeBinDir):`$PATH"
echo $(Quote-Bash $nodeBin) > $(Quote-Bash "$stateWsl/logs/node_path.log")
$(Quote-Bash $nodeBin) -v >> $(Quote-Bash "$stateWsl/logs/node_path.log") 2>&1
exec $(Quote-Bash $nodeBin) $(Quote-Bash "$stateWsl/persistent_browser_worker.js")
"@
[System.IO.File]::WriteAllText($httpService, ($httpServiceText -replace "`r`n", "`n"), $utf8NoBom)
[System.IO.File]::WriteAllText($serverService, ($serverServiceText -replace "`r`n", "`n"), $utf8NoBom)
[System.IO.File]::WriteAllText($workerService, ($workerServiceText -replace "`r`n", "`n"), $utf8NoBom)
$httpServiceWsl = ConvertTo-WslPath -WindowsPath $httpService
$serverServiceWsl = ConvertTo-WslPath -WindowsPath $serverService
$workerServiceWsl = ConvertTo-WslPath -WindowsPath $workerService

$httpProc = Start-Process -FilePath "wsl.exe" -ArgumentList @("-d", $WslDistro, "--", "bash", $httpServiceWsl) -WindowStyle Hidden -PassThru -RedirectStandardOutput $httpStdout -RedirectStandardError $httpStderr
Set-Content -LiteralPath (Join-Path $stateDirFull "http.winpid") -Value $httpProc.Id -Encoding ASCII
$serverProc = Start-Process -FilePath "wsl.exe" -ArgumentList @("-d", $WslDistro, "--", "bash", $serverServiceWsl) -WindowStyle Hidden -PassThru -RedirectStandardOutput $serverStdout -RedirectStandardError $serverStderr
Set-Content -LiteralPath (Join-Path $stateDirFull "server.winpid") -Value $serverProc.Id -Encoding ASCII
Start-Sleep -Seconds 2
$workerProc = Start-Process -FilePath "wsl.exe" -ArgumentList @("-d", $WslDistro, "--", "bash", $workerServiceWsl) -WindowStyle Hidden -PassThru -RedirectStandardOutput $workerStdout -RedirectStandardError $workerStderr
Set-Content -LiteralPath (Join-Path $stateDirFull "worker.winpid") -Value $workerProc.Id -Encoding ASCII

$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    if (Test-Path -LiteralPath $readyFile) {
        $managed = @{
            started_at = (Get-Date).ToString("o")
            backend = "wsl"
            wsl_distro = $WslDistro
            state_dir = $stateDirFull
            state_wsl = $stateWsl
            web_root = $webRootFull
            web_wsl = $webWsl
            node_modules_wsl = $nodeModulesWsl
            chrome_gl_mode = $ChromeGlMode
            chrome_headless = $ChromeHeadless
            chrome_exe = $ChromeExe
            cap_port = $CapPort
            http_port = $HttpPort
        }
        $managed | ConvertTo-Json -Depth 6 | Out-File -Encoding UTF8 -LiteralPath $managedFile
        exit 0
    }
    Start-Sleep -Milliseconds 200
}

Write-Error "WSL remote-style persistent worker did not become ready; see $logDir"
exit 1
