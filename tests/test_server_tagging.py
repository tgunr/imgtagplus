from __future__ import annotations

import queue
import threading
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import imgtagplus.server as server


class _ImmediateThread:
    def __init__(self, target, daemon=None):
        self._target = target
        self.daemon = daemon

    def start(self) -> None:
        self._target()


@pytest.fixture
def tagging_client(monkeypatch, tmp_path: Path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr(server, "log_queue", queue.Queue())
    monkeypatch.setattr(server, "progress_queue", queue.Queue())
    monkeypatch.setattr(server, "_job_lock", threading.Lock())
    monkeypatch.setattr(server, "_job_started_at", None)
    monkeypatch.setattr(server, "_job_started_monotonic", None)
    monkeypatch.setattr(server, "_last_job_runtime_seconds", None)
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)

    def fake_run(args, progress_callback=None):
        captured["args"] = args
        return 0

    monkeypatch.setattr(server, "app_run", fake_run)

    return TestClient(server.app), work_dir, captured


def test_start_tagging_invalid_path_does_not_leave_server_busy(tagging_client, tmp_path: Path):
    client, _, _ = tagging_client
    missing_path = tmp_path / "missing"

    response = client.post("/api/tag", json={"input": str(missing_path)})

    assert response.status_code == 400
    assert response.json() == {"detail": f"Invalid or non-existent path: {missing_path}"}
    assert client.get("/api/status").json()["is_processing"] is False


def test_start_tagging_clamps_threshold_and_max_tags(tagging_client) -> None:
    client, work_dir, captured = tagging_client
    image_path = work_dir / "photo.jpg"
    image_path.write_bytes(b"image")

    response = client.post(
        "/api/tag",
        json={"input": str(image_path), "threshold": -5, "max_tags": 10_000},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "started"
    assert datetime.fromisoformat(payload["started_at"])
    assert captured["args"].threshold == 0.0
    assert captured["args"].max_tags == 200


def test_start_tagging_passes_manual_accelerator(tagging_client) -> None:
    client, work_dir, captured = tagging_client
    image_path = work_dir / "photo.jpg"
    image_path.write_bytes(b"image")

    response = client.post(
        "/api/tag",
        json={"input": str(image_path), "accelerator": "cpu"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "started"
    assert datetime.fromisoformat(payload["started_at"])
    assert captured["args"].accelerator == "cpu"


def test_security_headers_are_added_to_api_responses(tagging_client) -> None:
    client, _, _ = tagging_client

    response = client.get("/api/status")

    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_index_uses_external_scripts_for_csp(tagging_client) -> None:
    client, _, _ = tagging_client

    response = client.get("/")

    assert response.status_code == 200
    assert "<script>" not in response.text
    assert '<script src="/static/theme.js"></script>' in response.text
    assert 'id="runtime-clock"' in response.text
    assert 'id="copy-logs"' in response.text


def test_health_endpoint_reports_ok(tagging_client) -> None:
    client, _, _ = tagging_client

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_reports_runtime_details_when_idle(tagging_client) -> None:
    client, _, _ = tagging_client

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "is_processing": False,
        "started_at": None,
        "runtime_seconds": None,
    }


def test_done_event_reports_empty_scan_when_no_images_processed(tagging_client) -> None:
    client, work_dir, _ = tagging_client
    image_path = work_dir / "photo.jpg"
    image_path.write_bytes(b"image")

    response = client.post("/api/tag", json={"input": str(image_path)})

    assert response.status_code == 200

    progress_events = []
    while not server.progress_queue.empty():
        progress_events.append(server.progress_queue.get_nowait())

    done_event = next(event for event in progress_events if event.get("type") == "done")
    assert done_event["result_status"] == "empty_scan"
    assert done_event["result_message"] is None


def test_done_event_reports_failed_when_worker_crashes(tagging_client, monkeypatch) -> None:
    client, work_dir, _ = tagging_client
    image_path = work_dir / "photo.jpg"
    image_path.write_bytes(b"image")

    def crash_run(args, progress_callback=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "app_run", crash_run)

    response = client.post("/api/tag", json={"input": str(image_path)})

    assert response.status_code == 200

    progress_events = []
    while not server.progress_queue.empty():
        progress_events.append(server.progress_queue.get_nowait())
    done_event = next(event for event in progress_events if event.get("type") == "done")
    assert done_event["result_status"] == "failed"
    assert done_event["result_message"] == "boom"

    log_events = []
    while not server.log_queue.empty():
        log_events.append(server.log_queue.get_nowait())

    assert any(event.get("level") == "ERROR" for event in log_events)
    assert not any("No images found" in event.get("message", "") for event in log_events)


def test_done_event_reports_failed_when_worker_returns_nonzero(tagging_client, monkeypatch) -> None:
    client, work_dir, _ = tagging_client
    image_path = work_dir / "photo.jpg"
    image_path.write_bytes(b"image")

    def fail_run(args, progress_callback=None):
        return 1

    monkeypatch.setattr(server, "app_run", fail_run)

    response = client.post("/api/tag", json={"input": str(image_path)})

    assert response.status_code == 200

    progress_events = []
    while not server.progress_queue.empty():
        progress_events.append(server.progress_queue.get_nowait())
    done_event = next(event for event in progress_events if event.get("type") == "done")
    assert done_event["result_status"] == "failed"
    assert "Job exited with code 1" in done_event["result_message"]

    log_events = []
    while not server.log_queue.empty():
        log_events.append(server.log_queue.get_nowait())

    assert not any("No images found" in event.get("message", "") for event in log_events)


def test_start_tagging_allows_same_origin_from_lan_host(tagging_client) -> None:
    """The UI opened via a LAN IP/hostname must be able to POST back to itself.

    Regression: the origin check only accepted ``localhost``/``127.0.0.1`` and
    returned a plain-text 403 for the app's own same-origin request, which
    Safari surfaced as "The string did not match the expected pattern.".
    """
    client, work_dir, captured = tagging_client
    image_path = work_dir / "photo.jpg"
    image_path.write_bytes(b"image")

    response = client.post(
        "/api/tag",
        json={"input": str(image_path)},
        headers={"Origin": "http://192.168.1.50:5002", "Host": "192.168.1.50:5002"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["status"] == "started"


def test_start_tagging_allows_same_origin_hostname(tagging_client) -> None:
    client, work_dir, _ = tagging_client
    image_path = work_dir / "photo.jpg"
    image_path.write_bytes(b"image")

    response = client.post(
        "/api/tag",
        json={"input": str(image_path)},
        headers={"Origin": "http://mini.local:5002", "Host": "mini.local:5002"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "started"


def test_start_tagging_rejects_cross_site_origin(tagging_client) -> None:
    client, work_dir, _ = tagging_client
    image_path = work_dir / "photo.jpg"
    image_path.write_bytes(b"image")

    response = client.post(
        "/api/tag",
        json={"input": str(image_path)},
        headers={"Origin": "http://evil.example.com", "Host": "192.168.1.50:5002"},
    )

    assert response.status_code == 403
    assert response.text == "Forbidden: cross-origin request"

