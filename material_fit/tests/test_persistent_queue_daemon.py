from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.laya_capture import persistent_queue_daemon  # noqa: E402


def test_persistent_queue_daemon_writes_browser_score_result(tmp_path: Path) -> None:
    paths = persistent_queue_daemon.QueuePaths(
        state_dir=tmp_path,
        queue_dir=tmp_path / "queue",
        result_dir=tmp_path / "results",
        ready_file=tmp_path / "ready.json",
        inflight_dir=tmp_path / "inflight",
        processed_dir=tmp_path / "processed",
        failed_dir=tmp_path / "failed",
        log_dir=tmp_path / "logs",
    )
    persistent_queue_daemon.ensure_dirs(paths)
    request_id = "req_test"
    request_path = paths.queue_dir / f"{request_id}.request.json"
    request_path.write_text(
        json.dumps(
            {
                "request_id": request_id,
                "command": {
                    "nonce": "nonce-test",
                    "output_dir": str(tmp_path / "capture_out"),
                    "views": [{"view_id": "v000_yaw0_pitch0", "yaw": 0.0, "pitch": 0.0}],
                    "browser_score": {"enabled": True, "reference_images": [{"view_id": "v000_yaw0_pitch0"}]},
                },
            }
        ),
        encoding="utf-8",
    )

    def post_score() -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                payload = json.dumps(
                    {
                        "nonce": "nonce-test",
                        "browser_score": {
                            "fit_score": 0.83,
                            "diff_score": 0.17,
                            "views": [{"view_id": "v000_yaw0_pitch0", "fit_score": 0.83}],
                        },
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    "http://127.0.0.1:18787/material-fit/capture-score",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=1).read()
                return
            except OSError:
                time.sleep(0.02)

    worker = threading.Thread(target=post_score)
    worker.start()
    persistent_queue_daemon.process_request(
        request_path,
        paths=paths,
        host="127.0.0.1",
        port=18787,
        timeout_s=5,
    )
    worker.join(timeout=1)

    result = json.loads((paths.result_dir / f"{request_id}.result.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["browser_score"]["fit_score"] == 0.83
    assert (paths.processed_dir / f"{request_id}.request.json").exists()
