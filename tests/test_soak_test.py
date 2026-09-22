import json
import os
import time
from pathlib import Path
from scripts.soak_test_24h import SoakTestRunner, get_current_rss_mb


def test_get_current_rss_mb():
    rss = get_current_rss_mb()
    assert isinstance(rss, float)
    assert rss > 0.0


def test_soak_test_runner_smoke_execution(tmp_path: Path):
    report_file = tmp_path / "smoke_soak_report.json"
    runner = SoakTestRunner(
        duration_hours=0.0005,  # ~1.8 seconds
        sample_interval_sec=0.3,
        num_instances=5,
        device_type="virtual",
        inject_faults=False,
        report_path=str(report_file),
    )

    result = runner.run()

    assert result.passed_sla is True
    assert result.actual_duration_sec >= 1.0
    assert result.total_tasks_completed > 0
    assert result.deadlocks_detected == 0
    assert result.proxy_violations == 0
    assert report_file.exists()

    with open(report_file, "r") as f:
        data = json.load(f)
        assert "summary" in data
        assert data["summary"]["passed_sla"] is True
        assert len(data["samples_tail"]) > 0

    md_file = report_file.with_suffix(".md")
    assert md_file.exists()
    content = md_file.read_text()
    assert "PASSED (ALL SLA MET)" in content


def test_soak_test_runner_fault_recovery(tmp_path: Path):
    report_file = tmp_path / "fault_soak_report.json"
    runner = SoakTestRunner(
        duration_hours=0.0005,
        sample_interval_sec=0.2,
        num_instances=3,
        device_type="virtual",
        inject_faults=True,
        report_path=str(report_file),
    )

    runner.setup_cluster()
    # Force a fault injection manually
    runner._run_fault_injection(step=60)
    assert runner.faults_injected == 1
    assert runner.faults_recovered == 1
    runner.stop()
