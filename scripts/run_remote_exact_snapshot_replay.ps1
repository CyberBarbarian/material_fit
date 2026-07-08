param(
    [Parameter(Mandatory = $true)]
    [string]$SnapshotRoot,
    [string]$OutputDir = "",
    [int]$Iterations = 0,
    [double]$TargetScore = 0.0,
    [int]$CapPort = 0,
    [int]$HttpPort = 0,
    [string]$ChromeGlMode = "egl",
    [switch]$Headful,
    [string]$ChromeExe = "",
    [ValidateSet("windows", "wsl")]
    [string]$WorkerBackend = "windows",
    [string]$Python = "python",
    [int]$MaxRuntimeSec = 0,
    [switch]$DryRun,
    [switch]$KeepWorkerRunning,
    [switch]$SkipTargetRenderHashCheck
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredPath {
    param([string]$PathText, [string]$Name)
    if (-not $PathText) {
        throw "$Name is required."
    }
    $resolved = Resolve-Path -LiteralPath $PathText -ErrorAction SilentlyContinue
    if (-not $resolved) {
        throw "$Name does not exist: $PathText"
    }
    return $resolved.Path
}

function Resolve-OptionalPath {
    param([string]$PathText)
    if (-not $PathText) {
        return ""
    }
    $resolved = Resolve-Path -LiteralPath $PathText -ErrorAction SilentlyContinue
    if (-not $resolved) {
        return ""
    }
    return $resolved.Path
}

function Resolve-ReleasePackageRoot {
    param([string]$ReleaseDir)
    $releaseFull = Resolve-RequiredPath -PathText $ReleaseDir -Name "snapshot release"
    if (Test-Path -LiteralPath (Join-Path $releaseFull "material_fit\fit_material.py")) {
        return $releaseFull
    }
    $children = @(Get-ChildItem -LiteralPath $releaseFull -Directory -ErrorAction SilentlyContinue | Sort-Object Name)
    foreach ($child in $children) {
        if (Test-Path -LiteralPath (Join-Path $child.FullName "material_fit\fit_material.py")) {
            return $child.FullName
        }
    }
    throw "snapshot release does not contain material_fit/fit_material.py: $ReleaseDir"
}

function Copy-DirectoryContents {
    param([string]$Source, [string]$Destination)
    $sourceFull = Resolve-RequiredPath -PathText $Source -Name "directory copy source"
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $items = Get-ChildItem -LiteralPath $sourceFull -Force
    foreach ($item in $items) {
        Copy-Item -LiteralPath $item.FullName -Destination $Destination -Recurse -Force
    }
}

function Resolve-OperationalWebRoot {
    param(
        [string]$SnapshotRoot,
        [string]$CandidateWebRoot,
        [string]$RepoRoot
    )

    $candidate = Resolve-OptionalPath -PathText $CandidateWebRoot
    if ($candidate -and (Test-Path -LiteralPath (Join-Path $candidate "index.html"))) {
        return $candidate
    }

    $operational = Join-Path $SnapshotRoot "runtime\operational_webroot"
    if (Test-Path -LiteralPath (Join-Path $operational "index.html")) {
        return (Resolve-Path -LiteralPath $operational).Path
    }

    $baseCandidates = @(
        (Join-Path $SnapshotRoot "runtime\operational_webroot_base"),
        (Join-Path $RepoRoot "artifacts\remote_repro_audit_20260707_202817\remote_web_current_exact\web_localpkg_20260702_212056"),
        (Join-Path $RepoRoot "artifacts\remote_exact_run_20260707\remote_web_current_20260702_212056")
    )
    $base = ""
    foreach ($path in $baseCandidates) {
        $resolved = Resolve-OptionalPath -PathText $path
        if ($resolved -and (Test-Path -LiteralPath (Join-Path $resolved "index.html"))) {
            $base = $resolved
            break
        }
    }
    if (-not $base) {
        throw "snapshot webroot is incomplete and no operational webroot base was found. Need a full Laya web build with index.html; checked: $($baseCandidates -join '; ')"
    }

    if (Test-Path -LiteralPath $operational) {
        Remove-Item -LiteralPath $operational -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $operational | Out-Null
    $baseItems = Get-ChildItem -LiteralPath $base -Force
    foreach ($item in $baseItems) {
        Copy-Item -LiteralPath $item.FullName -Destination $operational -Recurse -Force
    }
    if ($candidate) {
        $overlayItems = Get-ChildItem -LiteralPath $candidate -Force
        foreach ($item in $overlayItems) {
            Copy-Item -LiteralPath $item.FullName -Destination $operational -Recurse -Force
        }
    }
    return (Resolve-Path -LiteralPath $operational).Path
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$snapshotRootFull = Resolve-RequiredPath -PathText $SnapshotRoot -Name "SnapshotRoot"
$manifestPath = Resolve-RequiredPath -PathText (Join-Path $snapshotRootFull "manifest.json") -Name "manifest.json"
$layout = "legacy"
$runOutputCandidate = Join-Path $snapshotRootFull "run_output"
$webRootCandidate = Join-Path $snapshotRootFull "webroot"
$startMaterialSource = ""
if (-not (Test-Path -LiteralPath $runOutputCandidate)) {
    $forensicRunOutput = Join-Path $snapshotRootFull "success_run"
    if (Test-Path -LiteralPath $forensicRunOutput) {
        $layout = "forensic_runtime_snapshot"
        $runOutputCandidate = $forensicRunOutput
        $webRootCandidate = Join-Path $snapshotRootFull "runtime\webroot"
        $startMaterialSource = Join-Path $snapshotRootFull "old_out\start_material.lmat"
    }
}
$runOutput = Resolve-RequiredPath -PathText $runOutputCandidate -Name "snapshot run output"
$webRoot = Resolve-OperationalWebRoot -SnapshotRoot $snapshotRootFull -CandidateWebRoot $webRootCandidate -RepoRoot $repoRoot.Path
$releaseRoot = Resolve-ReleasePackageRoot -ReleaseDir (Join-Path $snapshotRootFull "release")
if (-not $startMaterialSource) {
    $startMaterialSource = Join-Path $runOutput "start_material.lmat"
}
$startMaterialSource = Resolve-RequiredPath -PathText $startMaterialSource -Name "snapshot start_material.lmat"
$sourceConfig = Resolve-RequiredPath -PathText (Join-Path $runOutput "fit_config.json") -Name "snapshot fit_config.json"
$targetRender = Resolve-RequiredPath -PathText (Join-Path $runOutput "target_render") -Name "snapshot target_render"
$startRender = Resolve-RequiredPath -PathText (Join-Path $runOutput "start_render") -Name "snapshot start_render"
$cleanupScript = Resolve-RequiredPath -PathText (Join-Path $PSScriptRoot "cleanup_material_fit_background.ps1") -Name "cleanup_material_fit_background.ps1"
if ($WorkerBackend -eq "wsl") {
    $ensureScript = Resolve-RequiredPath -PathText (Join-Path $PSScriptRoot "ensure_remote_style_laya_worker_wsl.ps1") -Name "ensure_remote_style_laya_worker_wsl.ps1"
    $stopScript = Resolve-RequiredPath -PathText (Join-Path $PSScriptRoot "stop_remote_style_laya_worker_wsl.ps1") -Name "stop_remote_style_laya_worker_wsl.ps1"
} else {
    $ensureScript = Resolve-RequiredPath -PathText (Join-Path $PSScriptRoot "ensure_remote_style_laya_worker.ps1") -Name "ensure_remote_style_laya_worker.ps1"
    $stopScript = Resolve-RequiredPath -PathText (Join-Path $PSScriptRoot "stop_remote_style_laya_worker.ps1") -Name "stop_remote_style_laya_worker.ps1"
}

$manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $manifestPath | ConvertFrom-Json
$remoteOutput = [string]$manifest.remote_output
if (-not $remoteOutput) {
    $remoteOutput = [string]$manifest.success_out
}
if (-not $remoteOutput) {
    throw "manifest.remote_output/success_out is missing: $manifestPath"
}
$runSh = Resolve-RequiredPath -PathText (Join-Path $runOutput "scripts\run.sh") -Name "snapshot run.sh"

$runSpecParser = Join-Path $env:TEMP ("material_fit_run_sh_spec_{0}_{1}.py" -f (Get-Date -Format "yyyyMMddHHmmss"), $PID)
$runSpecPath = Join-Path $env:TEMP ("material_fit_run_sh_spec_{0}_{1}.json" -f (Get-Date -Format "yyyyMMddHHmmss"), $PID)
$runSpecParserCode = @'
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

run_sh = Path(sys.argv[1])
out_path = Path(sys.argv[2])
text = run_sh.read_text(encoding="utf-8", errors="replace")

variables: dict[str, str] = {}
for line in text.splitlines():
    match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.+?)\s*$", line)
    if not match:
        continue
    raw = match.group(2).strip()
    if raw.startswith("$("):
        continue
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1]
    variables[match.group(1)] = raw

def expand_shell_vars(value: str) -> str:
    previous = None
    current = value
    for _ in range(8):
        if current == previous:
            break
        previous = current
        current = re.sub(
            r"\$([A-Za-z_][A-Za-z0-9_]*)",
            lambda m: variables.get(m.group(1), m.group(0)),
            current,
        )
        current = current.replace("${PYTHONPATH:-}", "")
    return current

variables = {key: expand_shell_vars(value) for key, value in variables.items()}
collapsed = re.sub(r"\\\s*\r?\n\s*", " ", text)
command_match = re.search(
    r"python3\s+-m\s+material_fit\.fit_material\s+(?P<args>.*?)\s*>\s*\"\$OUT/fit_material_[^\"]*\.log\"",
    collapsed,
    re.S,
)
if not command_match:
    raise SystemExit(f"could not find fit_material command in {run_sh}")

fit_args = [expand_shell_vars(token) for token in shlex.split(command_match.group("args"), posix=True)]

def value_after(flag: str) -> str | None:
    for index, token in enumerate(fit_args[:-1]):
        if token == flag:
            return fit_args[index + 1]
    return None

iterations_text = value_after("--iterations") or variables.get("ITERATIONS") or ""
target_text = value_after("--target-score") or variables.get("TARGET_SCORE") or ""

payload = {
    "run_sh": str(run_sh),
    "iterations": int(float(iterations_text)) if iterations_text else None,
    "target_score": float(target_text) if target_text else None,
    "fit_args": fit_args,
    "variables": {key: variables.get(key) for key in ["BASE", "OUT", "OLD_OUT", "ITERATIONS", "TARGET_SCORE"] if key in variables},
}
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
'@
Write-Utf8NoBom -Path $runSpecParser -Text $runSpecParserCode
try {
    & $Python $runSpecParser $runSh $runSpecPath
    if ($LASTEXITCODE -ne 0) {
        throw "run.sh parser failed with exit code $LASTEXITCODE"
    }
    $remoteRunSpec = Get-Content -Raw -Encoding UTF8 -LiteralPath $runSpecPath | ConvertFrom-Json
} finally {
    Remove-Item -LiteralPath $runSpecParser, $runSpecPath -Force -ErrorAction SilentlyContinue
}
if (-not $remoteRunSpec -or -not $remoteRunSpec.fit_args) {
    throw "run.sh parser did not produce fit args: $runSh"
}

$iterationsSource = "override"
if ($Iterations -le 0) {
    if (-not $remoteRunSpec.iterations) {
        throw "Iterations was not provided and could not be parsed from $runSh"
    }
    $Iterations = [int]$remoteRunSpec.iterations
    $iterationsSource = "remote_run_sh"
}
$targetScoreSource = "override"
if ($TargetScore -le 0) {
    if (-not $remoteRunSpec.target_score) {
        throw "TargetScore was not provided and could not be parsed from $runSh"
    }
    $TargetScore = [double]$remoteRunSpec.target_score
    $targetScoreSource = "remote_run_sh"
}

if (-not $OutputDir) {
    $caseName = Split-Path -Leaf $remoteOutput.TrimEnd("/")
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputDir = Join-Path $repoRoot.Path ("artifacts\remote_snapshot_replays\{0}_{1}" -f $caseName, $stamp)
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$outputDirFull = (Resolve-Path -LiteralPath $OutputDir).Path

if ($CapPort -le 0) {
    $CapPort = 9400 + (Get-Random -Minimum 0 -Maximum 200)
}
if ($HttpPort -le 0) {
    $HttpPort = 19400 + (Get-Random -Minimum 0 -Maximum 200)
}
if ($MaxRuntimeSec -le 0) {
    $MaxRuntimeSec = [Math]::Max(300, 180 + ($Iterations * 5))
}
$chromeHeadlessValue = if ($Headful) { "0" } else { "1" }
$chromeExeArg = if ($ChromeExe) { $ChromeExe } else { "-" }

$localTargetRender = Join-Path $outputDirFull "target_render"
$localStartRender = Join-Path $outputDirFull "start_render"
$localStartMaterial = Join-Path $outputDirFull "start_material.lmat"
if (-not (Test-Path -LiteralPath $localTargetRender)) {
    Copy-Item -LiteralPath $targetRender -Destination $localTargetRender -Recurse
}
if (-not (Test-Path -LiteralPath $localStartRender)) {
    Copy-Item -LiteralPath $startRender -Destination $localStartRender -Recurse
}
Copy-Item -LiteralPath $startMaterialSource -Destination $localStartMaterial -Force

$localConfig = Join-Path $outputDirFull "fit_config.local_snapshot.json"
$configBuilder = Join-Path $env:TEMP ("material_fit_snapshot_config_{0}_{1}.py" -f (Get-Date -Format "yyyyMMddHHmmss"), $PID)
$configBuilderCode = @'
from __future__ import annotations

import json
import sys
from pathlib import Path

source_config = Path(sys.argv[1])
snapshot_root = Path(sys.argv[2])
run_output = Path(sys.argv[3])
webroot = Path(sys.argv[4])
output_dir = Path(sys.argv[5])
remote_output = sys.argv[6]
cap_port = int(sys.argv[7])
http_port = int(sys.argv[8])
ensure_script = Path(sys.argv[9])
stop_script = Path(sys.argv[10])
target_score = float(sys.argv[11])
chrome_gl_mode = sys.argv[12]
chrome_headless = sys.argv[13]
chrome_exe = "" if sys.argv[14] == "-" else sys.argv[14]
start_material = Path(sys.argv[15])
snapshot_layout = sys.argv[16]
out_config = Path(sys.argv[17])

config = json.loads(source_config.read_text(encoding="utf-8"))

def replace_paths(value):
    if isinstance(value, str):
        return value.replace(remote_output, str(run_output))
    if isinstance(value, list):
        return [replace_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: replace_paths(item) for key, item in value.items()}
    return value

config = replace_paths(config)
config["case_name"] = output_dir.name
config["output_dir"] = str(output_dir)
config["target_score"] = target_score
config["auto_adjust_target_score"] = target_score
config["laya_material_path"] = str(start_material)
config.setdefault("replay_metadata", {})["snapshot_layout"] = snapshot_layout
config.setdefault("replay_metadata", {})["snapshot_root"] = str(snapshot_root)
config.setdefault("replay_metadata", {})["source_run_output"] = str(run_output)
config.setdefault("replay_metadata", {})["source_webroot"] = str(webroot)
shader = webroot / "resources" / "shader" / "Custom_low.shader"
if shader.exists():
    config["laya_shader_path"] = str(shader)

laya_capture = config.setdefault("laya_capture", {})
views = laya_capture.get("views") or []
target_render = output_dir / "target_render"
start_render = output_dir / "start_render"
laya_capture.setdefault("browser_score", {})["reference_images"] = [
    {"view_id": view.get("view_id"), "path": str(target_render / view.get("file_name"))}
    for view in views
    if view.get("file_name")
]
config["image_pairs"] = [
    {
        "view_id": view.get("view_id"),
        "reference": str(target_render / view.get("file_name")),
        "candidate": str(start_render / view.get("file_name")),
    }
    for view in views
    if view.get("file_name")
]

state_dir = output_dir / "persistent_worker_state"
queue_dir = state_dir / "queue"
result_dir = state_dir / "results"
log_dir = state_dir / "logs"
pq = laya_capture.setdefault("persistent_queue", {})
pq.update(
    {
        "enabled": True,
        "state_dir": str(state_dir),
        "queue_dir": str(queue_dir),
        "result_dir": str(result_dir),
        "ready_file": str(state_dir / "ready.json"),
        "cap_port": cap_port,
        "width": int(laya_capture.get("width", 900)),
        "height": int(laya_capture.get("height", 700)),
        "timeout_s": max(int(pq.get("timeout_s", 120)), 120),
        "poll_s": float(pq.get("poll_s", 0.02)),
        "warmup_timeout_s": max(int(pq.get("warmup_timeout_s", 120)), 120),
        "server_base_url": f"http://127.0.0.1:{cap_port}",
        "path_replacements": [{"from": remote_output, "to": str(run_output)}],
        "ensure_command": [],
        "prestarted_ensure_command": [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ensure_script),
            "-StateDir",
            str(state_dir),
            "-RemoteArtifactRoot",
            str(snapshot_root),
            "-WebRoot",
            str(webroot),
            "-CapPort",
            str(cap_port),
            "-HttpPort",
            str(http_port),
            "-ChromeGlMode",
            chrome_gl_mode,
            "-ChromeHeadless",
            chrome_headless,
        ],
        "stop_command": [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(stop_script),
            "-StateDir",
            str(state_dir),
        ],
        "warmup_record_file": str(state_dir / "warmup_records.json"),
        "warmup_requests": [
            {
                "label": "target_render",
                "source_path": str(run_output / "target_render" / "persistent_request_command.json"),
                "output_dir": str(output_dir / "_warmup_target_render"),
            },
            {
                "label": "start_render",
                "source_path": str(run_output / "start_render" / "persistent_request_command.json"),
                "output_dir": str(output_dir / "_warmup_start_render"),
            },
        ],
        "environment": {
            "MATERIAL_FIT_PERSISTENT_STATE_DIR": str(state_dir),
            "MATERIAL_FIT_PERSISTENT_LOG_DIR": str(log_dir),
            "CAP_PORT": str(cap_port),
            "HTTP_PORT": str(http_port),
            "CAP_WIDTH": str(int(laya_capture.get("width", 900))),
            "CAP_HEIGHT": str(int(laya_capture.get("height", 700))),
            "CAP_POLL_MS": "10",
            "CHROME_GL_MODE": chrome_gl_mode,
            "CHROME_HEADLESS": chrome_headless,
            "CAP_ALPHA_SOURCE": str(laya_capture.get("alpha_source", "render_alpha")),
            "MATERIAL_FIT_PERSISTENT_RESTART_ON_MISMATCH": "1",
            "MATERIAL_FIT_PERSISTENT_START_TIMEOUT_SEC": "60",
        },
    }
)
if chrome_exe:
    pq["prestarted_ensure_command"].extend(["-ChromeExe", chrome_exe])
    pq["environment"]["CHROME_EXE"] = chrome_exe

out_config.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
'@
Write-Utf8NoBom -Path $configBuilder -Text $configBuilderCode

try {
    & $Python $configBuilder $sourceConfig $snapshotRootFull $runOutput $webRoot $outputDirFull $remoteOutput $CapPort $HttpPort $ensureScript $stopScript $TargetScore $ChromeGlMode $chromeHeadlessValue $chromeExeArg $localStartMaterial $layout $localConfig
    if ($LASTEXITCODE -ne 0) {
        throw "config builder failed with exit code $LASTEXITCODE"
    }
} finally {
    Remove-Item -LiteralPath $configBuilder -Force -ErrorAction SilentlyContinue
}

$stateDir = Join-Path $outputDirFull "persistent_worker_state"
$logPath = Join-Path $outputDirFull "fit_material_snapshot_replay.log"
$stdoutPath = Join-Path $outputDirFull "fit_material_snapshot_replay.stdout.log"
$stderrPath = Join-Path $outputDirFull "fit_material_snapshot_replay.stderr.log"

function New-FitMaterialArgs {
    param(
        [object[]]$RemoteFitArgs,
        [string]$ConfigPath,
        [int]$IterationCount,
        [double]$ScoreTarget,
        [bool]$DryRunMode
    )

    $argsOut = @("-u", "-m", "material_fit.fit_material")
    $hasConfigArg = $false
    $hasIterationsArg = $false
    $hasTargetScoreArg = $false
    for ($argIndex = 0; $argIndex -lt $RemoteFitArgs.Count; $argIndex += 1) {
        $arg = [string]$RemoteFitArgs[$argIndex]
        if ($arg -eq "--config") {
            $argsOut += @("--config", $ConfigPath)
            $hasConfigArg = $true
            $argIndex += 1
            continue
        }
        if ($arg -eq "--iterations") {
            $argsOut += @("--iterations", "$IterationCount")
            $hasIterationsArg = $true
            $argIndex += 1
            continue
        }
        if ($arg -eq "--target-score") {
            $argsOut += @("--target-score", "$ScoreTarget")
            $hasTargetScoreArg = $true
            $argIndex += 1
            continue
        }
        $argsOut += $arg
    }
    if (-not $hasConfigArg) {
        $argsOut += @("--config", $ConfigPath)
    }
    if (-not $hasIterationsArg) {
        $argsOut += @("--iterations", "$IterationCount")
    }
    if (-not $hasTargetScoreArg) {
        $argsOut += @("--target-score", "$ScoreTarget")
    }
    if ($DryRunMode) {
        $argsOut += "--dry-run"
    }
    return $argsOut
}

$fitArgs = New-FitMaterialArgs -RemoteFitArgs @($remoteRunSpec.fit_args) -ConfigPath $localConfig -IterationCount $Iterations -ScoreTarget $TargetScore -DryRunMode ([bool]$DryRun)
if ($DryRun) {
    $summary = [ordered]@{
        ok = $true
        exit_code = 0
        snapshot_root = $snapshotRootFull
        snapshot_layout = $layout
        output_dir = $outputDirFull
        web_root = $webRoot
        release_root = $releaseRoot
        config = $localConfig
        remote_run_sh = $runSh
        fit_args_source = "remote_run_sh"
        remote_fit_args = @($remoteRunSpec.fit_args)
        effective_fit_args = @($fitArgs)
        log = $logPath
        stdout_log = $stdoutPath
        stderr_log = $stderrPath
        result_path = Join-Path $outputDirFull "auto_adjust\auto_adjust_result.json"
        dry_run = $true
        iterations = $Iterations
        iterations_source = $iterationsSource
        target_score = $TargetScore
        target_score_source = $targetScoreSource
        max_runtime_sec = $MaxRuntimeSec
        cap_port = $CapPort
        http_port = $HttpPort
        chrome_gl_mode = $ChromeGlMode
        headful = [bool]$Headful
        chrome_exe = $ChromeExe
        worker_backend = $WorkerBackend
        used_warmup_reference_renders = $false
        target_render_hash_mismatch_path = ""
    }
    $summaryPath = Join-Path $outputDirFull "snapshot_replay_summary.json"
    $summary | ConvertTo-Json -Depth 8 | Out-File -Encoding UTF8 -LiteralPath $summaryPath
    $summary | ConvertTo-Json -Depth 8
    exit 0
}

& powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -StateDir $stateDir | Out-Null
& powershell -NoProfile -ExecutionPolicy Bypass -File $cleanupScript -StateDir $stateDir | Out-Null

$warmupProbe = Join-Path $env:TEMP ("material_fit_snapshot_warmup_{0}_{1}.py" -f (Get-Date -Format "yyyyMMddHHmmss"), $PID)
$warmupProbeCode = @'
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

config_path = Path(sys.argv[1])
record_path = Path(sys.argv[2])
timeout_s = float(sys.argv[3])

config = json.loads(config_path.read_text(encoding="utf-8"))
capture = config.get("laya_capture") if isinstance(config.get("laya_capture"), dict) else {}
pq = capture.get("persistent_queue") if isinstance(capture.get("persistent_queue"), dict) else {}
queue_dir = Path(str(pq.get("queue_dir")))
result_dir = Path(str(pq.get("result_dir")))
cap_port = int(pq.get("cap_port") or 8787)
base_url = str(pq.get("server_base_url") or f"http://127.0.0.1:{cap_port}")
path_replacements = pq.get("path_replacements") if isinstance(pq.get("path_replacements"), list) else []
warmups = pq.get("warmup_requests") if isinstance(pq.get("warmup_requests"), list) else []

queue_dir.mkdir(parents=True, exist_ok=True)
result_dir.mkdir(parents=True, exist_ok=True)
records = []

def replace_paths(value):
    if isinstance(value, str):
        out = value
        for item in path_replacements:
            if isinstance(item, dict):
                out = out.replace(str(item.get("from", "")), str(item.get("to", "")))
        return out
    if isinstance(value, list):
        return [replace_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: replace_paths(item) for key, item in value.items()}
    return value

def run_one(raw: dict, index: int) -> dict:
    source = Path(str(raw.get("source_path") or ""))
    if not source.exists():
        raise RuntimeError(f"warmup source request missing: {source}")
    request = replace_paths(json.loads(source.read_text(encoding="utf-8")))
    command = request.get("command")
    if not isinstance(command, dict):
        raise RuntimeError(f"warmup source has no command: {source}")
    label = str(raw.get("label") or f"warmup_{index}")
    request_id = f"preflight_{label}_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns()}"
    output_dir = Path(str(raw.get("output_dir") or config_path.parent / f"_preflight_{label}"))
    output_dir.mkdir(parents=True, exist_ok=True)
    request["request_id"] = request_id
    command["nonce"] = f"persistent_{request_id}_{int(time.time() * 1000) % 1000000:06d}"
    command["server_base_url"] = base_url
    command["post_url"] = f"{base_url}/material-fit/capture-result"
    command["output_dir"] = str(output_dir)
    command = replace_paths(command)
    request["command"] = command
    queue_path = queue_dir / f"{request_id}.request.json"
    result_path = result_dir / f"{request_id}.result.json"
    queue_path.with_suffix(queue_path.suffix + ".tmp").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    queue_path.with_suffix(queue_path.suffix + ".tmp").replace(queue_path)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if result_path.exists() and result_path.stat().st_size > 0:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            record = {
                "label": label,
                "request_id": request_id,
                "result_path": str(result_path),
                "output_dir": str(output_dir),
                "ok": bool(result.get("ok")),
                "browser_score": result.get("browser_score"),
                "png_count": result.get("png_count"),
                "error": result.get("error"),
            }
            if not result.get("ok"):
                raise RuntimeError(f"warmup request failed: {json.dumps(record, ensure_ascii=False)}")
            return record
        time.sleep(0.05)
    raise RuntimeError(f"warmup request timed out after {timeout_s}s: {request_id}")

try:
    if not warmups:
        raise RuntimeError("persistent_queue.warmup_requests is empty")
    for index, warmup in enumerate(warmups):
        if isinstance(warmup, dict):
            records.append(run_one(warmup, index))
    record_path.write_text(json.dumps({"ok": True, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
except Exception as exc:
    record_path.write_text(json.dumps({"ok": False, "error": str(exc), "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    raise
'@
Write-Utf8NoBom -Path $warmupProbe -Text $warmupProbeCode

function Start-PreflightWorker {
    param([int]$Attempt)

    $prestartArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $ensureScript,
        "-StateDir",
        $stateDir,
        "-RemoteArtifactRoot",
        $snapshotRootFull,
        "-WebRoot",
        $webRoot,
        "-CapPort",
        "$CapPort",
        "-HttpPort",
        "$HttpPort",
        "-ChromeGlMode",
        $ChromeGlMode,
        "-ChromeHeadless",
        $chromeHeadlessValue
    )
    if ($ChromeExe) {
        $prestartArgs += @("-ChromeExe", $ChromeExe)
    }
    $prestartStdout = Join-Path $outputDirFull ("prestart_worker_attempt_{0}.stdout.log" -f $Attempt)
    $prestartStderr = Join-Path $outputDirFull ("prestart_worker_attempt_{0}.stderr.log" -f $Attempt)
    Remove-Item -LiteralPath $prestartStdout, $prestartStderr -Force -ErrorAction SilentlyContinue
    $prestartProc = Start-Process -FilePath "powershell" -ArgumentList $prestartArgs -WorkingDirectory $repoRoot.Path -WindowStyle Hidden -PassThru -RedirectStandardOutput $prestartStdout -RedirectStandardError $prestartStderr
    $readyFile = Join-Path $stateDir "ready.json"
    $prestartDeadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $prestartDeadline) {
        if (Test-Path -LiteralPath $readyFile) {
            break
        }
        $prestartProc.Refresh()
        if ($prestartProc.HasExited -and $prestartProc.ExitCode -ne 0) {
            $stdout = if (Test-Path -LiteralPath $prestartStdout) { Get-Content -Raw -Encoding UTF8 -LiteralPath $prestartStdout } else { "" }
            $stderr = if (Test-Path -LiteralPath $prestartStderr) { Get-Content -Raw -Encoding UTF8 -LiteralPath $prestartStderr } else { "" }
            throw "prestarting remote-style worker failed with exit code $($prestartProc.ExitCode)`nstdout=$stdout`nstderr=$stderr"
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-Path -LiteralPath $readyFile)) {
        if (-not $prestartProc.HasExited) {
            Stop-Process -Id $prestartProc.Id -Force -ErrorAction SilentlyContinue
        }
        throw "prestarting remote-style worker timed out waiting for $readyFile"
    }
    $prestartProc.Refresh()
    if (-not $prestartProc.HasExited) {
        Stop-Process -Id $prestartProc.Id -Force -ErrorAction SilentlyContinue
    }

    $warmupRecord = Join-Path $stateDir ("preflight_warmup_attempt_{0}.json" -f $Attempt)
    $warmupStdout = Join-Path $outputDirFull ("preflight_warmup_attempt_{0}.stdout.log" -f $Attempt)
    $warmupStderr = Join-Path $outputDirFull ("preflight_warmup_attempt_{0}.stderr.log" -f $Attempt)
    & $Python $warmupProbe $localConfig $warmupRecord 45 > $warmupStdout 2> $warmupStderr
    if ($LASTEXITCODE -ne 0) {
        $detail = if (Test-Path -LiteralPath $warmupRecord) { Get-Content -Raw -Encoding UTF8 -LiteralPath $warmupRecord } else { "" }
        $stderr = if (Test-Path -LiteralPath $warmupStderr) { Get-Content -Raw -Encoding UTF8 -LiteralPath $warmupStderr } else { "" }
        throw "preflight warmup failed on attempt $Attempt`n$detail`nstderr=$stderr"
    }
}

$preflightOk = $false
$preflightErrors = @()
for ($attempt = 1; $attempt -le 3; $attempt += 1) {
    try {
        Start-PreflightWorker -Attempt $attempt
        $preflightOk = $true
        break
    } catch {
        $preflightErrors += $_.Exception.Message
        & powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -StateDir $stateDir | Out-Null
        & powershell -NoProfile -ExecutionPolicy Bypass -File $cleanupScript -StateDir $stateDir | Out-Null
    }
}
Remove-Item -LiteralPath $warmupProbe -Force -ErrorAction SilentlyContinue
if (-not $preflightOk) {
    throw ("remote-style worker preflight failed after 3 attempts`n" + ($preflightErrors -join "`n---`n"))
}

$warmupTargetRender = Join-Path $outputDirFull "_warmup_target_render"
$warmupStartRender = Join-Path $outputDirFull "_warmup_start_render"
$mismatchPath = ""
$targetHashMismatches = @()
if (-not $SkipTargetRenderHashCheck) {
    $targetPngs = @(Get-ChildItem -LiteralPath $localTargetRender -Filter "*.png" -File -ErrorAction SilentlyContinue | Sort-Object Name)
    foreach ($targetPng in $targetPngs) {
        $warmupPng = Join-Path $warmupTargetRender $targetPng.Name
        if (-not (Test-Path -LiteralPath $warmupPng -PathType Leaf)) {
            $targetHashMismatches += [pscustomobject]@{
                file = $targetPng.Name
                expected = (Get-FileHash -Algorithm SHA256 -LiteralPath $targetPng.FullName).Hash.ToLowerInvariant()
                actual = "missing"
            }
            continue
        }
        $expectedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $targetPng.FullName).Hash.ToLowerInvariant()
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $warmupPng).Hash.ToLowerInvariant()
        if ($expectedHash -ne $actualHash) {
            $targetHashMismatches += [pscustomobject]@{
                file = $targetPng.Name
                expected = $expectedHash
                actual = $actualHash
            }
        }
    }
    if ($targetHashMismatches.Count -gt 0) {
        $mismatchPath = Join-Path $outputDirFull "target_render_hash_mismatch.json"
        $payload = [ordered]@{
            ok = ($layout -eq "forensic_runtime_snapshot")
            reason = "snapshot target_render differs from local warmup render"
            snapshot_target_render = $localTargetRender
            local_warmup_target_render = $warmupTargetRender
            mismatch_count = $targetHashMismatches.Count
            mismatches = @($targetHashMismatches)
            policy = if ($layout -eq "forensic_runtime_snapshot") { "continue_with_local_warmup_reference_renders" } else { "stop_legacy_snapshot_replay" }
        }
        $payload | ConvertTo-Json -Depth 6 | Out-File -Encoding UTF8 -LiteralPath $mismatchPath
        if ($layout -ne "forensic_runtime_snapshot") {
            $summaryPath = Join-Path $outputDirFull "snapshot_replay_summary.json"
            $summary = [ordered]@{
                ok = $false
                exit_code = 2
                reason = "target_render_hash_mismatch"
                mismatch_path = $mismatchPath
                snapshot_root = $snapshotRootFull
                snapshot_layout = $layout
                output_dir = $outputDirFull
                web_root = $webRoot
                release_root = $releaseRoot
                config = $localConfig
                remote_run_sh = $runSh
                fit_args_source = "remote_run_sh"
                remote_fit_args = @($remoteRunSpec.fit_args)
                effective_fit_args = @($fitArgs)
                dry_run = [bool]$DryRun
                iterations = $Iterations
                iterations_source = $iterationsSource
                target_score = $TargetScore
                target_score_source = $targetScoreSource
                cap_port = $CapPort
                http_port = $HttpPort
                chrome_gl_mode = $ChromeGlMode
                headful = [bool]$Headful
                chrome_exe = $ChromeExe
                worker_backend = $WorkerBackend
            }
            $summary | ConvertTo-Json -Depth 8 | Out-File -Encoding UTF8 -LiteralPath $summaryPath
            if (-not $KeepWorkerRunning) {
                & powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -StateDir $stateDir | Out-Null
                & powershell -NoProfile -ExecutionPolicy Bypass -File $cleanupScript -StateDir $stateDir | Out-Null
            }
            $summary | ConvertTo-Json -Depth 8
            exit 2
        }
    }
}
$usedWarmupReferenceRenders = $false
if ($layout -eq "forensic_runtime_snapshot") {
    foreach ($pair in @(@($warmupTargetRender, $localTargetRender), @($warmupStartRender, $localStartRender))) {
        $sourceDir = $pair[0]
        $destDir = $pair[1]
        if (Test-Path -LiteralPath $sourceDir) {
            Get-ChildItem -LiteralPath $sourceDir -File -ErrorAction SilentlyContinue |
                ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $destDir $_.Name) -Force }
        }
    }
    $usedWarmupReferenceRenders = $true
}

$oldPythonPath = $env:PYTHONPATH
$oldPyIo = $env:PYTHONIOENCODING
$oldPyUtf8 = $env:PYTHONUTF8
$oldPyUnbuffered = $env:PYTHONUNBUFFERED
$oldPyFaulthandler = $env:PYTHONFAULTHANDLER
$env:PYTHONPATH = $releaseRoot
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONFAULTHANDLER = "1"

$exitCode = 0
$timeoutMessage = $null
try {
    Remove-Item -LiteralPath $stdoutPath, $stderrPath, $logPath -Force -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $Python -ArgumentList $fitArgs -WorkingDirectory $releaseRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $timedOut = $false
    try {
        Wait-Process -Id $proc.Id -Timeout $MaxRuntimeSec -ErrorAction Stop
    } catch {
        $timedOut = $true
    }
    if ($timedOut -and (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        $timeoutMessage = "snapshot replay timed out after $MaxRuntimeSec seconds"
        $exitCode = 124
    } else {
        $proc.Refresh()
        $exitCode = $proc.ExitCode
    }
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:PYTHONIOENCODING = $oldPyIo
    $env:PYTHONUTF8 = $oldPyUtf8
    $env:PYTHONUNBUFFERED = $oldPyUnbuffered
    $env:PYTHONFAULTHANDLER = $oldPyFaulthandler
    if (-not $KeepWorkerRunning) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -StateDir $stateDir | Out-Null
        & powershell -NoProfile -ExecutionPolicy Bypass -File $cleanupScript -StateDir $stateDir | Out-Null
    }
}

$combined = @()
if (Test-Path -LiteralPath $stdoutPath) {
    $combined += Get-Content -Encoding UTF8 -LiteralPath $stdoutPath -ErrorAction SilentlyContinue
}
if (Test-Path -LiteralPath $stderrPath) {
    $combined += Get-Content -Encoding UTF8 -LiteralPath $stderrPath -ErrorAction SilentlyContinue
}
if ($timeoutMessage) {
    $combined += $timeoutMessage
}
$combined | Out-File -Encoding UTF8 -LiteralPath $logPath

$resultPath = Join-Path $outputDirFull "auto_adjust\auto_adjust_result.json"
if ($null -eq $exitCode -and (Test-Path -LiteralPath $resultPath)) {
    $exitCode = 0
}
if ($null -eq $exitCode) {
    $exitCode = 1
}
$summary = [ordered]@{
    ok = ($exitCode -eq 0)
    exit_code = $exitCode
    snapshot_root = $snapshotRootFull
    snapshot_layout = $layout
    output_dir = $outputDirFull
    web_root = $webRoot
    release_root = $releaseRoot
    config = $localConfig
    remote_run_sh = $runSh
    fit_args_source = "remote_run_sh"
    remote_fit_args = @($remoteRunSpec.fit_args)
    effective_fit_args = @($fitArgs)
    log = $logPath
    stdout_log = $stdoutPath
    stderr_log = $stderrPath
    result_path = $resultPath
    dry_run = [bool]$DryRun
    iterations = $Iterations
    iterations_source = $iterationsSource
    target_score = $TargetScore
    target_score_source = $targetScoreSource
    max_runtime_sec = $MaxRuntimeSec
    cap_port = $CapPort
    http_port = $HttpPort
    chrome_gl_mode = $ChromeGlMode
    headful = [bool]$Headful
    chrome_exe = $ChromeExe
    worker_backend = $WorkerBackend
    used_warmup_reference_renders = $usedWarmupReferenceRenders
    target_render_hash_mismatch_path = $mismatchPath
}
if (Test-Path -LiteralPath $resultPath) {
    $result = Get-Content -Raw -Encoding UTF8 -LiteralPath $resultPath | ConvertFrom-Json
    $summary["status"] = $result.status
    $summary["terminal_reason"] = $result.terminal_reason
    $summary["best_fit_score"] = $result.best_fit_score
    $summary["best_score"] = $result.best_score
}

$summaryPath = Join-Path $outputDirFull "snapshot_replay_summary.json"
$summary | ConvertTo-Json -Depth 8 | Out-File -Encoding UTF8 -LiteralPath $summaryPath
$summary | ConvertTo-Json -Depth 8
exit $exitCode
