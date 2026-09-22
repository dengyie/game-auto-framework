"""Tests for 24h soak test telemetry and API stress testing REST endpoints."""

import csv
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from server.app import app, SOAK_PID_FILE, SOAK_REPORT_CSV, SOAK_REPORT_JSON


@pytest.fixture
def client():
    return TestClient(app)


def test_soak_status_endpoint(client, tmp_path, monkeypatch):
    """Test GET /api/v1/soak/status when idle or with simulated report."""
    res = client.get("/api/v1/soak/status")
    assert res.status_code == 200
    data = res.json()
    assert "is_running" in data
    assert "elapsed_sec" in data
    assert "memory_drift_pct" in data
    assert "active_instances" in data
    assert "completed_ops" in data
    assert "faults_recovered" in data
    assert "deadlocks_detected" in data


def test_soak_status_with_mock_csv(client, tmp_path, monkeypatch):
    """Test GET /api/v1/soak/status with mock telemetry CSV data."""
    mock_csv = tmp_path / "mock_soak.csv"
    with open(mock_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "elapsed_sec", "rss_mb", "active_instances", "completed_tasks", "faults_recovered", "deadlocks_detected"])
        writer.writerow([1700000000.0, 0.0, 100.0, 5, 0, 0, 0])
        writer.writerow([1700000010.0, 10.0, 101.5, 5, 20, 1, 0])

    monkeypatch.setattr("server.app.SOAK_REPORT_CSV", mock_csv)

    res = client.get("/api/v1/soak/status")
    assert res.status_code == 200
    data = res.json()
    assert data["baseline_rss_mb"] == 100.0
    assert data["current_rss_mb"] == 101.5
    assert data["memory_drift_pct"] == 1.5
    assert data["elapsed_sec"] == 10.0
    assert data["active_instances"] == 5
    assert data["completed_ops"] == 20
    assert data["faults_recovered"] == 1
    assert data["deadlocks_detected"] == 0
    assert data["sla_passed"] is True


def test_soak_telemetry_endpoint(client, tmp_path, monkeypatch):
    """Test GET /api/v1/soak/telemetry with mock CSV."""
    mock_csv = tmp_path / "mock_soak_telem.csv"
    with open(mock_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "elapsed_sec", "rss_mb", "active_instances", "completed_tasks", "faults_recovered", "deadlocks_detected"])
        for i in range(10):
            writer.writerow([1700000000.0 + i * 5, float(i * 5), 100.0 + i * 0.1, 5, i * 10, 0, 0])

    monkeypatch.setattr("server.app.SOAK_REPORT_CSV", mock_csv)

    res = client.get("/api/v1/soak/telemetry?limit=5")
    assert res.status_code == 200
    data = res.json()
    assert "samples" in data
    assert len(data["samples"]) == 5
    assert data["total_recorded"] == 10
    last_sample = data["samples"][-1]
    assert last_sample["elapsed_sec"] == 45.0


def test_soak_stop_not_running(client, tmp_path, monkeypatch):
    """Test POST /api/v1/soak/stop when PID file does not exist."""
    fake_pid_file = tmp_path / "nonexistent.pid"
    monkeypatch.setattr("server.app.SOAK_PID_FILE", fake_pid_file)

    res = client.post("/api/v1/soak/stop")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ["not_running", "already_stopped"]


def test_stress_run_endpoint_smoke(client):
    """Test on-demand API stress test with small request count."""
    res = client.post(
        "/api/v1/stress/run",
        json={
            "concurrency": 2,
            "requests": 4,
            "p95_threshold_ms": 1000.0,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert "qps" in data
    assert "overall_p95_ms" in data
    assert data["total_requests"] == 4
    assert data["total_success"] == 4
    assert data["passed_sla"] is True
