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
    [object]$ChromeHeadless = $(if ($env:CHROME_HEADLESS) { $env:CHROME_HEADLESS } else { $true }),
    [string]$ChromeExe = $(if ($env:CHROME_EXE) { $env:CHROME_EXE } else { "" }),
    [object]$CleanBeforeStart = $true,
    [object]$AllowExisting = $false
)

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

if (-not $StateDir) {
    Write-Error "StateDir is required. Pass -StateDir or set MATERIAL_FIT_PERSISTENT_STATE_DIR."
    exit 2
}

$CleanBeforeStart = Convert-ToBool -Value $CleanBeforeStart
$AllowExisting = Convert-ToBool -Value $AllowExisting
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

if (-not (Test-Path -LiteralPath (Join-Path $nodeModulesFull "playwright")) -and -not (Test-Path -LiteralPath (Join-Path $nodeModulesFull "playwright-chromium"))) {
    Write-Error "NodeModules must contain playwright or playwright-chromium: $nodeModulesFull"
    exit 2
}

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$statePath = Resolve-Path -LiteralPath $StateDir
$stateDirFull = $statePath.Path
$queueDir = Join-Path $stateDirFull "queue"
$resultDir = Join-Path $stateDirFull "results"
$logDir = Join-Path $stateDirFull "logs"
$readyFile = Join-Path $stateDirFull "ready.json"
$stopFile = Join-Path $stateDirFull "stop"
$serverScript = Join-Path $stateDirFull "persistent_capture_server.py"
$workerScript = Join-Path $stateDirFull "persistent_browser_worker.js"
$httpPidFile = Join-Path $stateDirFull "http.pid"
$serverPidFile = Join-Path $stateDirFull "server.pid"
$workerPidFile = Join-Path $stateDirFull "worker.pid"
$managedFile = Join-Path $stateDirFull "managed_processes.json"

New-Item -ItemType Directory -Force -Path $queueDir, $resultDir, $logDir | Out-Null

if ($CleanBeforeStart) {
    $stopScript = Join-Path $PSScriptRoot "stop_remote_style_laya_worker.ps1"
    if (Test-Path -LiteralPath $stopScript) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -StateDir $stateDirFull | Out-Null
    }
    Remove-Item -LiteralPath (Join-Path $queueDir "*.request.json") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $queueDir "*.tmp") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $resultDir "*.result.json") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $resultDir "*.tmp") -Force -ErrorAction SilentlyContinue
}

if ($AllowExisting) {
    $pidFiles = @($httpPidFile, $serverPidFile, $workerPidFile)
    $readyProcessCount = 0
    foreach ($pidFile in $pidFiles) {
        if (Test-Path -LiteralPath $pidFile) {
            $pidText = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($pidText) {
                $proc = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
                if ($proc) {
                    $readyProcessCount += 1
                }
            }
        }
    }
    if ($readyProcessCount -eq 3 -and (Test-Path -LiteralPath $readyFile)) {
        exit 0
    }
}

Remove-Item -LiteralPath $readyFile, $stopFile -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $serverSource -Destination $serverScript -Force
Copy-Item -LiteralPath $workerSource -Destination $workerScript -Force

# The remote generated worker imports "playwright"; the local quickstart already
# installs "playwright-chromium". Keep the remote worker body intact and only
# swap the package name when the exact package is unavailable locally.
if (-not (Test-Path -LiteralPath (Join-Path $nodeModulesFull "playwright")) -and (Test-Path -LiteralPath (Join-Path $nodeModulesFull "playwright-chromium"))) {
    $workerText = Get-Content -Raw -Encoding UTF8 -LiteralPath $workerScript
    $workerText = $workerText -replace "require\('playwright'\)", "require('playwright-chromium')"
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($workerScript, $workerText, $utf8NoBom)
}

$httpStdout = Join-Path $logDir "http_server.log"
$httpStderr = Join-Path $logDir "http_server.err.log"
$serverStdout = Join-Path $logDir "persistent_capture_server.log"
$serverStderr = Join-Path $logDir "persistent_capture_server.err.log"
$workerStdout = Join-Path $logDir "daemon_stdout.log"
$workerStderr = Join-Path $logDir "daemon_stderr.log"

$oldEnv = @{
    STATE_DIR = $env:STATE_DIR
    QUEUE_DIR = $env:QUEUE_DIR
    RESULT_DIR = $env:RESULT_DIR
    READY_FILE = $env:READY_FILE
    STOP_FILE = $env:STOP_FILE
    LOG_DIR = $env:LOG_DIR
    WEB_URL = $env:WEB_URL
    CAP_PORT = $env:CAP_PORT
    HTTP_PORT = $env:HTTP_PORT
    CHROME_GL_MODE = $env:CHROME_GL_MODE
    CHROME_HEADLESS = $env:CHROME_HEADLESS
    CHROME_EXE = $env:CHROME_EXE
    CAP_TIMEOUT_SEC = $env:CAP_TIMEOUT_SEC
    CAP_POLL_MS = $env:CAP_POLL_MS
    NODE_PATH = $env:NODE_PATH
}

try {
    $httpArgs = @("-m", "http.server", "$HttpPort", "--bind", $HostName, "--directory", $webRootFull)
    $httpProc = Start-Process -FilePath "python" -ArgumentList $httpArgs -WorkingDirectory $webRootFull -WindowStyle Hidden -RedirectStandardOutput $httpStdout -RedirectStandardError $httpStderr -PassThru
    Set-Content -LiteralPath $httpPidFile -Value $httpProc.Id -Encoding ASCII

    $serverArgs = @($serverScript, "--host", $HostName, "--port", "$CapPort")
    $serverProc = Start-Process -FilePath "python" -ArgumentList $serverArgs -WorkingDirectory $stateDirFull -WindowStyle Hidden -RedirectStandardOutput $serverStdout -RedirectStandardError $serverStderr -PassThru
    Set-Content -LiteralPath $serverPidFile -Value $serverProc.Id -Encoding ASCII

    $env:STATE_DIR = $stateDirFull
    $env:QUEUE_DIR = $queueDir
    $env:RESULT_DIR = $resultDir
    $env:READY_FILE = $readyFile
    $env:STOP_FILE = $stopFile
    $env:LOG_DIR = $logDir
    $env:WEB_URL = "http://${HostName}:${HttpPort}/index.html"
    $env:CAP_PORT = "$CapPort"
    $env:HTTP_PORT = "$HttpPort"
    $env:CHROME_GL_MODE = $ChromeGlMode
    $env:CHROME_HEADLESS = if ($ChromeHeadless) { "1" } else { "0" }
    if ($ChromeExe) {
        $env:CHROME_EXE = $ChromeExe
    } else {
        Remove-Item -LiteralPath "Env:CHROME_EXE" -ErrorAction SilentlyContinue
    }
    $env:CAP_TIMEOUT_SEC = "$TimeoutSec"
    $env:CAP_POLL_MS = "$PollMs"
    $env:NODE_PATH = $nodeModulesFull

    $workerProc = Start-Process -FilePath "node" -ArgumentList @($workerScript) -WorkingDirectory $stateDirFull -WindowStyle Hidden -RedirectStandardOutput $workerStdout -RedirectStandardError $workerStderr -PassThru
    Set-Content -LiteralPath $workerPidFile -Value $workerProc.Id -Encoding ASCII

    $managed = @{
        started_at = (Get-Date).ToString("o")
        state_dir = $stateDirFull
        web_root = $webRootFull
        cap_port = $CapPort
        http_port = $HttpPort
        chrome_gl_mode = $ChromeGlMode
        chrome_headless = $ChromeHeadless
        chrome_exe = $ChromeExe
        processes = @(
            @{ name = "http_server"; pid = $httpProc.Id; pid_file = $httpPidFile },
            @{ name = "capture_server"; pid = $serverProc.Id; pid_file = $serverPidFile },
            @{ name = "browser_worker"; pid = $workerProc.Id; pid_file = $workerPidFile }
        )
    }
    $managed | ConvertTo-Json -Depth 5 | Out-File -Encoding UTF8 -LiteralPath $managedFile
} finally {
    foreach ($key in $oldEnv.Keys) {
        Set-Item -LiteralPath "Env:$key" -Value $oldEnv[$key] -ErrorAction SilentlyContinue
        if ($null -eq $oldEnv[$key]) {
            Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue
        }
    }
}

$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    if (Test-Path -LiteralPath $readyFile) {
        exit 0
    }
    Start-Sleep -Milliseconds 200
}

Write-Error "remote-style persistent worker did not become ready; see $workerStdout and $workerStderr"
exit 1
