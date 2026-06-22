import json
from pathlib import Path

from z7_sentineltray.telemetry import JsonWriter


def test_status_export_writer(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    writer = JsonWriter(path)

    payload = {
        "running": True,
        "last_scan": "t1",
        "last_match": "m1",
        "last_send": "s1",
        "last_error": "",
        "last_healthcheck": "h1",
        "uptime_seconds": 1,
        "error_count": 0,
    }

    writer.write(payload)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["last_scan"] == "t1"
    assert data["running"] is True
