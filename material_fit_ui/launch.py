"""One-click launcher for the Material Fit Inspector.

This script saves you from juggling two terminal windows. It:

1. Starts the FastAPI backend (``uvicorn`` on ``127.0.0.1:8000``).
2. Starts the Vite dev server (``npm run dev`` on ``localhost:5173``).
3. Tails both processes' stdout into a single console with
   colored ``[backend]`` / ``[frontend]`` prefixes so you can spot
   errors quickly.
4. Polls the backend until it answers ``/api/health``, then opens
   the browser to ``http://localhost:5173/`` automatically.
5. Ctrl+C (or closing the launcher window) cleanly kills both
   children, including ``npm``'s grandchildren on Windows.

Usage (from the repo root):

.. code-block:: powershell

    python tools/material_fit_ui/launch.py

Or just double-click ``launch.bat`` next to this file. See
``--help`` for flags (``--no-browser``, ``--no-reload``,
``--backend-only``, ``--frontend-only``, ``--no-npm-install``).

Cross-platform notes:

* On Windows, ``npm`` is actually ``npm.cmd``; we resolve it via
  :func:`shutil.which` so the user does not have to know.
* On Windows, ``subprocess.CREATE_NEW_PROCESS_GROUP`` lets us send
  ``CTRL_BREAK_EVENT`` to children without killing the launcher.
  Vite spawns a few sub-processes, so on shutdown we additionally
  ``taskkill /T /F`` to wipe the whole tree.
* On POSIX we just ``terminate()`` then ``kill()`` after a grace
  period.

This launcher intentionally has zero non-stdlib dependencies so it
works in a fresh checkout where the user has not yet
``pip install``-ed anything.
"""

from __future__ import annotations

import argparse
import http.client
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = UI_ROOT / "frontend"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173

BACKEND_HEALTH_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}/api/health"
BROWSER_URL = f"http://localhost:{FRONTEND_PORT}/"

# ANSI color codes; Windows 10+ powershell.exe / cmd.exe support
# these natively. We avoid the ``colorama`` dependency.
COLOR_BACKEND = "\x1b[36m"   # cyan
COLOR_FRONTEND = "\x1b[35m"  # magenta
COLOR_LAUNCH = "\x1b[33m"    # yellow
COLOR_ERR = "\x1b[31m"       # red
COLOR_RESET = "\x1b[0m"


# ---------------------------------------------------------------------
# logging helpers


def _say(msg: str, *, color: str = COLOR_LAUNCH) -> None:
    print(f"{color}[launch]{COLOR_RESET} {msg}", flush=True)


def _err(msg: str) -> None:
    print(f"{COLOR_ERR}[launch]{COLOR_RESET} {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------
# subprocess plumbing


def _spawn(
    cmd: list[str],
    cwd: Path,
    label: str,
    color: str,
) -> subprocess.Popen[bytes]:
    """Spawn a child with a tail thread relaying stdout to our console.

    ``stderr`` is merged into ``stdout`` so the order on screen
    matches what each child actually printed.
    """

    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP: lets us send Ctrl+Break to the
        # child later. Without this, our own Ctrl+C handler would
        # also interrupt the child (which is fine for graceful
        # shutdown, but makes signal management ambiguous).
        creationflags = 0x00000200  # CREATE_NEW_PROCESS_GROUP

    _say(f"starting {label}: {' '.join(cmd)}  (cwd={cwd})")
    try:
        proc = subprocess.Popen(  # noqa: S603 - cmd is internal
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            bufsize=0,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"could not start {label}: {exc}. Check that {cmd[0]!r} is "
            f"on PATH."
        ) from exc

    thread = threading.Thread(
        target=_tail,
        args=(proc, label, color),
        daemon=True,
        name=f"tail-{label}",
    )
    thread.start()
    return proc


def _tail(proc: subprocess.Popen[bytes], label: str, color: str) -> None:
    """Read ``proc.stdout`` line by line, prefix and print."""
    if proc.stdout is None:
        return
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                continue
            print(f"{color}[{label}]{COLOR_RESET} {line}", flush=True)
    except (ValueError, OSError):
        # File handle closed under us during shutdown: that's fine.
        pass


def _terminate(procs: Iterable[subprocess.Popen[bytes]]) -> None:
    """Kill child processes (and their descendants on Windows)."""
    procs = list(procs)
    for proc in procs:
        if proc.poll() is not None:
            continue
        pid = proc.pid
        try:
            if sys.platform == "win32":
                # ``npm`` is a shim that itself spawns ``node.exe`` /
                # ``vite``; ``proc.terminate`` only kills the shim,
                # leaving an orphan dev server bound to port 5173.
                # ``taskkill /T`` walks the tree.
                subprocess.run(  # noqa: S603,S607
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                proc.terminate()
        except Exception as exc:  # noqa: BLE001
            _err(f"failed to terminate pid {pid}: {exc}")
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    # Best-effort wait so we don't leave zombies behind.
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------
# health check + browser


def _wait_for_backend(timeout: float) -> bool:
    """Poll the backend until ``/api/health`` answers, or give up."""
    parsed = urlparse(BACKEND_HEALTH_URL)
    host = parsed.hostname or BACKEND_HOST
    port = parsed.port or BACKEND_PORT
    path = parsed.path or "/"
    deadline = time.monotonic() + timeout
    last_err: str | None = None
    while time.monotonic() < deadline:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=1.5)
            conn.request("GET", path)
            resp = conn.getresponse()
            # Even a 404 means uvicorn is alive; here we expect 200.
            if 200 <= resp.status < 500:
                conn.close()
                return True
            last_err = f"backend returned HTTP {resp.status}"
            conn.close()
        except (ConnectionRefusedError, TimeoutError, OSError) as exc:
            last_err = type(exc).__name__
        time.sleep(0.5)

    _err(
        f"backend did not become healthy within {timeout:.0f}s "
        f"(last error: {last_err}). Check the [backend] log above."
    )
    return False


def _open_browser() -> None:
    try:
        opened = webbrowser.open(BROWSER_URL, new=2)
    except Exception as exc:  # noqa: BLE001
        _err(f"could not open browser automatically: {exc}")
        opened = False
    if opened:
        _say(f"opened {BROWSER_URL} in your default browser")
    else:
        _say(f"open {BROWSER_URL} manually in your browser")


# ---------------------------------------------------------------------
# preflight checks


def _ensure_python_dep(module: str, install_hint: str) -> None:
    """Verify a Python dependency is importable; otherwise raise."""
    try:
        __import__(module)
    except ImportError:
        raise RuntimeError(
            f"missing Python dependency {module!r}. Run:\n"
            f"    {install_hint}\n"
            f"in this Python environment ({sys.executable})."
        )


def _ensure_npm_install(skip: bool) -> None:
    """Run ``npm install`` once if ``node_modules`` is missing."""
    if skip:
        return
    if (FRONTEND_DIR / "node_modules").exists():
        return
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    npm = shutil.which(npm_cmd)
    if not npm:
        raise RuntimeError(
            f"could not locate {npm_cmd!r} on PATH. Install Node.js "
            f"(https://nodejs.org/) and reopen the shell so PATH picks up `npm`."
        )
    _say("frontend/node_modules missing — running 'npm install' (one-time)…")
    rc = subprocess.run([npm, "install"], cwd=str(FRONTEND_DIR), check=False).returncode  # noqa: S603
    if rc != 0:
        raise RuntimeError(
            f"npm install failed with exit code {rc}. Fix the error above and retry."
        )
    _say("npm install complete.")


# ---------------------------------------------------------------------
# command builders


def _build_backend_cmd(reload: bool) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "tools.material_fit_ui.backend.main:app",
        "--host",
        BACKEND_HOST,
        "--port",
        str(BACKEND_PORT),
    ]
    if reload:
        cmd.append("--reload")
    return cmd


def _build_frontend_cmd() -> list[str]:
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    npm = shutil.which(npm_cmd)
    if not npm:
        raise RuntimeError(
            f"could not locate {npm_cmd!r} on PATH. Install Node.js "
            f"(https://nodejs.org/) and reopen the shell."
        )
    return [
        npm,
        "run",
        "dev",
        "--",
        "--host",
        "localhost",
        "--port",
        str(FRONTEND_PORT),
    ]


# ---------------------------------------------------------------------
# main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="launch",
        description=(
            "One-click launcher for the Material Fit Inspector. "
            "Starts the FastAPI backend AND the Vite dev server, "
            "tails both into one console, opens the browser when "
            "the backend is healthy."
        ),
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically.",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable uvicorn --reload (slightly faster, no auto-reload on .py edits).",
    )
    parser.add_argument(
        "--no-npm-install",
        action="store_true",
        help="Skip the auto 'npm install' even if node_modules is missing.",
    )
    parser.add_argument(
        "--backend-only",
        action="store_true",
        help="Skip the frontend; only run the FastAPI backend.",
    )
    parser.add_argument(
        "--frontend-only",
        action="store_true",
        help="Skip the backend; only run the Vite dev server.",
    )
    parser.add_argument(
        "--health-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for the backend to answer /api/health (default: 30).",
    )
    args = parser.parse_args(argv)

    if args.backend_only and args.frontend_only:
        _err("--backend-only and --frontend-only are mutually exclusive.")
        return 2

    # Enable ANSI escapes on legacy Windows terminals if needed.
    if sys.platform == "win32":
        os.system("")  # noqa: S605,S607 — toggles VT processing on cmd.exe

    # Sanity: we need to launch from the repo root so
    # ``tools.material_fit_ui.backend.main`` resolves.
    if not (REPO_ROOT / "tools" / "material_fit_ui" / "backend" / "main.py").exists():
        _err(
            f"expected to find tools/material_fit_ui/backend/main.py under "
            f"{REPO_ROOT} — is this script in its original location?"
        )
        return 1

    # Each entry is (label, Popen) so we can identify which child
    # died first if one of them exits unexpectedly.
    children: list[tuple[str, subprocess.Popen[bytes]]] = []

    try:
        # Backend
        if not args.frontend_only:
            _ensure_python_dep(
                "uvicorn",
                "pip install -r tools/material_fit_ui/requirements.txt",
            )
            _ensure_python_dep(
                "fastapi",
                "pip install -r tools/material_fit_ui/requirements.txt",
            )
            backend_proc = _spawn(
                _build_backend_cmd(reload=not args.no_reload),
                cwd=REPO_ROOT,
                label="backend",
                color=COLOR_BACKEND,
            )
            children.append(("backend", backend_proc))

        # Frontend
        if not args.backend_only:
            _ensure_npm_install(skip=args.no_npm_install)
            frontend_proc = _spawn(
                _build_frontend_cmd(),
                cwd=FRONTEND_DIR,
                label="frontend",
                color=COLOR_FRONTEND,
            )
            children.append(("frontend", frontend_proc))

        # Health check + browser. Skip the wait if backend is not running.
        if not args.frontend_only:
            ok = _wait_for_backend(timeout=args.health_timeout)
            if ok:
                _say("backend is healthy.")
            # Even if the health check timed out, we still hand off to
            # the user — uvicorn might come up shortly and the user
            # can hit refresh.
        if not args.no_browser and not args.backend_only:
            # Give Vite a couple seconds to bind; we don't poll the
            # frontend port because Vite returns 200 only after the
            # first compile finishes, which can vary.
            time.sleep(1.5)
            _open_browser()

        _say("press Ctrl+C to stop both servers.")

        # Block until any child exits or the user hits Ctrl+C.
        while True:
            time.sleep(0.5)
            for name, proc in children:
                rc = proc.poll()
                if rc is not None:
                    _err(
                        f"{name} exited unexpectedly with code {rc}. "
                        f"Stopping any remaining process and quitting."
                    )
                    return rc or 1

    except KeyboardInterrupt:
        _say("Ctrl+C received — shutting down servers…")
        return 0
    except RuntimeError as exc:
        _err(str(exc))
        return 1
    finally:
        _terminate(proc for _, proc in children)
        _say("all child processes stopped. Bye!")


if __name__ == "__main__":
    raise SystemExit(main())
