"""Tests for FastAPI remote invocation server on VPS."""

import pytest
from fastapi.testclient import TestClient
from server.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_and_status_endpoints(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["engine"] == "game-auto-framework"
    assert data["version"] == "0.1.0"
    assert "platform" in data
    assert data["is_running"] is False


def test_task_start_and_stop_lifecycle(client):
    # Start task with virtual device
    payload = {
        "plugin": "mhxy_mobile",
        "pipeline": "daily_shimen",
        "device_type": "virtual",
        "variables": {"has_shimen_quest": True},
    }
    start_res = client.post("/api/v1/tasks/start", json=payload)
    assert start_res.status_code == 200
    start_data = start_res.json()
    assert start_data["status"] == "started"
    assert start_data["plugin"] == "mhxy_mobile"

    # Status check while running
    status_res = client.get("/api/v1/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["is_running"] is True
    assert status_data["active_plugin"] == "mhxy_mobile"

    # Fetch live screenshot frame
    shot_res = client.get("/api/v1/screenshot")
    assert shot_res.status_code == 200
    assert shot_res.headers["content-type"] == "image/jpeg"
    assert len(shot_res.content) > 0

    # Stop task
    stop_res = client.post("/api/v1/tasks/stop")
    assert stop_res.status_code == 200
    stop_data = stop_res.json()
    assert stop_data["status"] == "stopped"

    # Verify stopped
    final_status = client.get("/api/v1/status").json()
    assert final_status["is_running"] is False
