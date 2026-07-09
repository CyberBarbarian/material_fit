param(
    [string]$StateDir = "",
    [bool]$IncludeHeadlessChrome = $true,
    [bool]$IncludePlaywrightChrome = $true,
    [bool]$IncludeWsl = $true,
    [string]$WslDistro = "Ubuntu-24.04",
    [switch]$DryRun
)

function Stop-ProcessTree {
    param(
        [int]$ProcessId,
        [string]$Reason
    )
    if ($ProcessId -le 0) {
        return
    }
    if ($DryRun) {
        Write-Output "DRYRUN stop pid=$ProcessId reason=$Reason"
        return
    }
    $args = @("/F", "/T", "/PID", "$ProcessId")
    & taskkill @args >$null 2>$null
    $global:LASTEXITCODE = 0
}

function Stop-PidFiles {
    param([string]$Root)
    if (-not $Root) {
        return
    }
    $resolved = Resolve-Path -LiteralPath $Root -ErrorAction SilentlyContinue
    if (-not $resolved) {
        return
    }
    $names = @(
        "worker.pid",
        "server.pid",
        "http.pid",
        "daemon.pid",
        "daemon_launcher.pid",
        "renderer.pid",
        "worker.winpid",
        "server.winpid",
        "http.winpid"
    )
    foreach ($name in $names) {
        $pidFile = Join-Path $resolved.Path $name
        if (-not (Test-Path -LiteralPath $pidFile)) {
            continue
        }
        $pidText = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pidText) {
            Stop-ProcessTree -ProcessId ([int]$pidText) -Reason "pid_file:$pidFile"
        }
        if (-not $DryRun) {
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not $DryRun) {
        Remove-Item -LiteralPath (Join-Path $resolved.Path "ready.json") -Force -ErrorAction SilentlyContinue
        New-Item -ItemType File -Force -Path (Join-Path $resolved.Path "stop") | Out-Null
    }
}

function Stop-MaterialFitCommandLines {
    $repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..") -ErrorAction SilentlyContinue
    $repoText = if ($repoRoot) { [string]$repoRoot.Path } else { "C:\WorkSpace\material_fit" }
    $nodePatterns = @(
        "$repoText\material_fit\laya_capture\run_runtime_renderer.js",
        "\persistent_browser_worker.js"
    )
    $pythonPatterns = @(
        "\persistent_capture_server.py",
        "-m material_fit.laya_capture.persistent_queue_daemon",
        "-m material_fit.fit_material",
        "-m http.server"
    )
    $powershellPatterns = @(
        "$repoText\scripts\ensure_persistent_laya_queue.ps1",
        "$repoText\scripts\start_local_laya_runtime_renderer.ps1",
        "$repoText\scripts\run_fish_core_experiment.ps1",
        "$repoText\scripts\run_fish_finetune.ps1",
        "$repoText\scripts\run_fish_zero_start.ps1"
    )

    $chromePatterns = @(
        "$repoText",
        "material_fit",
        "persistent_worker",
        "persistent_browser_worker",
        "ms-playwright"
    )
    $wslPatterns = @(
        "persistent_browser_worker.js",
        "persistent_capture_server.py",
        "material_fit"
    )

    $processes = Get-CimInstance Win32_Process |
        Where-Object {
            ($_.Name -eq "node.exe" -or
             $_.Name -eq "python.exe" -or
             $_.Name -eq "powershell.exe" -or
             $_.Name -eq "chrome.exe" -or
             $_.Name -eq "wsl.exe") -and
            $_.CommandLine
        }
    foreach ($process in $processes) {
        if ([int]$process.ProcessId -eq $PID) {
            continue
        }
        $commandLine = [string]$process.CommandLine
        if ($commandLine.Contains("$repoText\scripts\cleanup_material_fit_background.ps1") -or
            $commandLine.Contains("$repoText\scripts\stop_persistent_laya_queue.ps1")) {
            continue
        }

        if ($process.Name -eq "chrome.exe") {
            if (-not $IncludePlaywrightChrome) {
                continue
            }
            $patterns = $chromePatterns
        } elseif ($process.Name -eq "wsl.exe") {
            if (-not $IncludeWsl) {
                continue
            }
            $patterns = $wslPatterns
        } elseif ($process.Name -eq "node.exe") {
            $patterns = $nodePatterns
        } elseif ($process.Name -eq "python.exe") {
            $patterns = $pythonPatterns
        } else {
            $patterns = $powershellPatterns
        }
        $matched = $false
        foreach ($pattern in $patterns) {
            if ($commandLine.Contains($pattern)) {
                $matched = $true
                break
            }
        }
        if ($matched) {
            Stop-ProcessTree -ProcessId ([int]$process.ProcessId) -Reason "material_fit_command_line"
        }
    }
}

function Stop-WslMaterialFitProcesses {
    if (-not $IncludeWsl) {
        return
    }
    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if (-not $wsl) {
        return
    }
    $script = "pkill -f 'persistent_browser_worker.js|persistent_capture_server.py|material_fit.laya_capture.persistent_queue_daemon' || true; pkill -f 'chrome-linux/chrome|chrome-headless-shell' || true"
    if ($DryRun) {
        Write-Output "DRYRUN wsl cleanup distro=$WslDistro script=$script"
        return
    }
    & wsl.exe -d $WslDistro -- bash -lc $script >$null 2>$null
    $global:LASTEXITCODE = 0
}

Stop-PidFiles -Root $StateDir

if ($IncludeHeadlessChrome) {
    if ($DryRun) {
        Write-Output "DRYRUN stop image=chrome-headless-shell.exe"
    } else {
        & taskkill /F /T /IM chrome-headless-shell.exe >$null 2>$null
        $global:LASTEXITCODE = 0
    }
}

Stop-MaterialFitCommandLines
Stop-WslMaterialFitProcesses
exit 0
