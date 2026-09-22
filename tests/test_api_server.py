"""Tests for FastAPI remote invocation server on VPS, including single tasks and chained routines."""

import pytest
from fastapi.testclient import TestClient
from server.app import app


@pytest.fixture
def client():
    # Ensure server is stopped before each test
    c = TestClient(app)
    c.post("/api/v1/tasks/stop")
    return c


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

    # Conflict check: starting another task should return 409
    dup_res = client.post("/api/v1/tasks/start", json=payload)
    assert dup_res.status_code == 409

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


def test_routine_start_status_and_stop_lifecycle(client):
    # Routine status when no routine active
    no_routine_res = client.get("/api/v1/tasks/routine-status")
    assert no_routine_res.status_code == 200
    assert no_routine_res.json()["status"] == "no_active_routine"

    # Start a routine with shimen, baotu, yuntong
    payload = {
        "plugin": "mhxy_mobile",
        "routine_name": "daily_speedrun",
        "pipelines": ["shimen", "baotu", "yuntong"],
        "device_type": "virtual",
        "variables": {
            "shimen_rounds": 20,
            "baotu_count": 10,
            "dig_count": 10,
            "yuntong_count": 3,
        },
    }
    start_res = client.post("/api/v1/tasks/start-routine", json=payload)
    assert start_res.status_code == 200
    start_data = start_res.json()
    assert start_data["status"] == "started"
    assert start_data["routine"] == "daily_speedrun"
    assert start_data["pipelines"] == ["daily_shimen", "daily_baotu", "daily_yuntong"]

    # Check status endpoint shows routine is active
    status_res = client.get("/api/v1/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["is_running"] is True
    assert status_data["is_routine"] is True
    assert status_data["routine_progress"] is not None
    assert status_data["routine_progress"]["routine_name"] == "daily_speedrun"

    # Query routine-specific status
    routine_res = client.get("/api/v1/tasks/routine-status")
    assert routine_res.status_code == 200
    r_data = routine_res.json()
    assert r_data["routine_name"] == "daily_speedrun"
    assert r_data["total_pipelines"] == 3

    # Stop routine
    stop_res = client.post("/api/v1/tasks/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "stopped"

    # Verify stopped
    final_status = client.get("/api/v1/status").json()
    assert final_status["is_running"] is False
