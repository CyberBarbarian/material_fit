param(
    [switch]$SkipBrowser
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $repoRoot
if (-not $env:PIP_DEFAULT_TIMEOUT) {
    $env:PIP_DEFAULT_TIMEOUT = "60"
}
if (-not $env:PIP_RETRIES) {
    $env:PIP_RETRIES = "10"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

foreach ($command in @("python", "node", "npm.cmd")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is required. Install Python 3.10+ and Node.js 18+ first."
    }
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Write-Host "[1/5] Creating the Python virtual environment."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Python virtual environment creation failed with exit code $LASTEXITCODE."
    }
} else {
    Write-Host "[1/5] Reusing the Python virtual environment."
}
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
Write-Host "[2/5] Installing the Python package and test dependencies."
Invoke-Checked -Command $python -Arguments @("-m", "pip", "install", "--upgrade", "pip") -Description "pip upgrade"
Invoke-Checked -Command $python -Arguments @("-m", "pip", "install", "-e", ".[test,perceptual]") -Description "Python dependency installation"

Write-Host "[3/5] Installing the locked Node.js dependencies."
Invoke-Checked -Command "npm.cmd" -Arguments @("ci") -Description "Node.js dependency installation"

if (-not $SkipBrowser) {
    Write-Host "[4/5] Installing and checking Playwright Chromium."
    Invoke-Checked -Command "npm.cmd" -Arguments @("run", "browser:install") -Description "Playwright Chromium installation"
    & npm.cmd run browser:check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Chromium health check failed; reinstalling the locked browser build."
        Invoke-Checked -Command "npm.cmd" -Arguments @("run", "browser:reinstall") -Description "Playwright Chromium reinstall"
        Invoke-Checked -Command "npm.cmd" -Arguments @("run", "browser:check") -Description "Playwright Chromium health check"
    }
} else {
    Write-Host "[4/5] Skipping Playwright Chromium installation."
}

Write-Host "[5/5] Validating the checkout."
Invoke-Checked -Command $python -Arguments @("-m", "material_fit.doctor", "--repo-root", $repoRoot) -Description "checkout validation"
Write-Host "Bootstrap completed."
