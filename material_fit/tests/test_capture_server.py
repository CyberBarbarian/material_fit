from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from tools.material_fit.laya_capture.capture_server import CaptureState, make_server  # type: ignore[import-not-found] # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - exercised in remote release layout.
    from material_fit.laya_capture.capture_server import CaptureState, make_server  # noqa: E402


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1.0) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_capture_server_rejects_stale_browser_score_nonce(tmp_path: Path) -> None:
    state = CaptureState(
        command={
            "nonce": "current-nonce",
            "views": [{"view_id": "v000_yaw0_pitch0"}],
        },
        output_dir=tmp_path,
        expected={"v000_yaw0_pitch0"},
    )
    server = make_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"
    try:
        status, payload = _post_json(
            f"{base_url}/material-fit/capture-score",
            {
                "nonce": "old-nonce",
                "browser_score": {
                    "fit_score": 0.99,
                    "diff_score": 0.01,
                },
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert status == 409
    assert payload["error"] == "stale capture nonce"
    assert state.browser_score is None
    assert state.received == set()
    assert not (tmp_path / "browser_score.json").exists()
