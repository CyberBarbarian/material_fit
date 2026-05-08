@echo off
REM ===================================================================
REM Material Fit Inspector — one-click launcher (Windows)
REM
REM Double-click this file to start backend + frontend together. The
REM real work happens in launch.py; this .bat is just a friendly
REM double-click wrapper that:
REM
REM   1. cd's to the repo root (one level above tools/material_fit_ui)
REM      so ``tools.material_fit_ui.backend.main`` resolves.
REM   2. Runs ``python tools\material_fit_ui\launch.py`` with whatever
REM      flags the user dropped onto the .bat (e.g. ``--no-browser``).
REM   3. Pauses on exit so the user can read the last log line before
REM      the console closes (otherwise a double-clicked .bat slams shut
REM      the moment Python returns).
REM
REM Args after the .bat name are forwarded to launch.py, e.g.:
REM
REM     launch.bat --no-browser --backend-only
REM ===================================================================

setlocal

REM Resolve paths relative to THIS .bat, not whatever cwd the user has.
set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%..\.."

cd /d "%REPO_ROOT%"
if errorlevel 1 (
    echo [launch.bat] ERROR: could not cd to %REPO_ROOT%
    pause
    exit /b 1
)

REM Prefer ``py`` (the Python launcher that ships with Python.org
REM installers) so we get the user's default Python without caring
REM whether ``python`` is on PATH. Fall back to ``python``.
where py >nul 2>nul
if %errorlevel% == 0 (
    py -3 "%SCRIPT_DIR%launch.py" %*
) else (
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        echo [launch.bat] ERROR: neither ``py`` nor ``python`` is on PATH.
        echo Install Python 3.10+ from https://www.python.org/ and re-run.
        pause
        exit /b 1
    )
    python "%SCRIPT_DIR%launch.py" %*
)

set "EXIT_CODE=%errorlevel%"
echo.
echo [launch.bat] launcher exited with code %EXIT_CODE%.
echo Press any key to close this window.
pause >nul
exit /b %EXIT_CODE%
