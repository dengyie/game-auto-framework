"""Unit tests for REST API Stress Test runner."""

import asyncio
from pathlib import Path
from scripts.api_stress_test import APIStressTester, EndpointMetrics


def test_endpoint_metrics_calculations():
    m = EndpointMetrics(path="/test")
    assert m.success_rate_pct == 100.0
    assert m.p50_ms == 0.0

    m.total_requests = 10
    m.success_requests = 9
    m.failed_requests = 1
    m.latencies_ms = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]

    assert m.success_rate_pct == 90.0
    assert m.mean_ms == 55.0
    assert m.p50_ms == 60.0
    assert m.p95_ms == 100.0
    assert m.p99_ms == 100.0


def test_api_stress_tester_run(tmp_path: Path):
    report_file = tmp_path / "test_api_stress.json"
    tester = APIStressTester(
        base_url="http://127.0.0.1:8000",
        concurrency=2,
        total_requests=4,
        timeout_sec=0.5,
        report_path=str(report_file),
    )

    # Run async stress tester against local or dummy target
    summary = asyncio.run(tester.run())

    assert summary.total_requests == 4
    assert summary.qps >= 0.0
    assert report_file.exists()
    assert report_file.with_suffix(".md").exists()
