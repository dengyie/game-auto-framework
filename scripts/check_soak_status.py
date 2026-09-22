#!/usr/bin/env python3
"""
Live status checker for game-auto-framework 24h soak test.
Reads time-series telemetry CSV and logs to display real-time SLA metrics.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import List, Optional


def check_status(
    report_json: str = "logs/soak_test_report.json",
    csv_path: str = "logs/soak_test_report.csv",
    pid_file: str = "logs/soak_test.pid",
) -> None:
    csv_p = Path(csv_path)
    json_p = Path(report_json)
    pid_p = Path(pid_file)

    print("=" * 65)
    print("   game-auto-framework 24h Soak Test Telemetry Monitor   ")
    print("=" * 65)

    is_running = False
    pid: Optional[int] = None
    if pid_p.exists():
        try:
            pid = int(pid_p.read_text().strip())
            # Check if process is running
            os.kill(pid, 0)
            is_running = True
        except (OSError, ValueError):
            is_running = False

    status_str = f"🟢 RUNNING (PID: {pid})" if is_running else "⚪ COMPLETED / STOPPED"
    print(f"• Execution Status : {status_str}")

    # Read latest CSV samples
    if not csv_p.exists():
        print(f"• Telemetry Data   : No CSV data found at {csv_path}")
        print("=" * 65)
        return

    rows: List[List[str]] = []
    try:
        with open(csv_p, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for r in reader:
                if len(r) >= 7:
                    rows.append(r)
    except Exception as e:
        print(f"• Telemetry Error  : Failed to read CSV: {e}")
        return

    if not rows:
        print("• Telemetry Data   : CSV initialized but no samples recorded yet.")
        print("=" * 65)
        return

    first = rows[0]
    last = rows[-1]

    elapsed_sec = float(last[1])
    hours = int(elapsed_sec // 3600)
    minutes = int((elapsed_sec % 3600) // 60)
    seconds = int(elapsed_sec % 60)

    base_rss = float(first[2])
    cur_rss = float(last[2])
    drift_pct = ((cur_rss - base_rss) / max(base_rss, 1.0)) * 100.0

    active_inst = int(last[3])
    ops = int(last[4])
    recovered = int(last[5])
    deadlocks = int(last[6])

    print(f"• Elapsed Runtime  : {hours:02d}h {minutes:02d}m {seconds:02d}s ({elapsed_sec:.1f}s)")
    print(f"• Memory RSS       : Baseline: {base_rss:.2f} MB | Current: {cur_rss:.2f} MB")
    drift_symbol = "✅" if abs(drift_pct) <= 5.0 else "❌"
    print(f"• Memory Drift     : {drift_pct:+.2f}% {drift_symbol} (SLA Threshold: <= 5.00%)")
    print(f"• Active Instances : {active_inst}/5 Instances Online")
    print(f"• Completed Ops    : {ops} operations ({ops / max(elapsed_sec, 1.0):.2f} ops/sec)")
    print(f"• Self-Healing     : {recovered} faults recovered by ClusterSupervisor")
    dl_symbol = "✅" if deadlocks == 0 else "❌"
    print(f"• Dual-Lock Status : {deadlocks} deadlocks detected {dl_symbol}")
    print(f"• Total Telemetry  : {len(rows)} samples recorded in {csv_p.name}")

    if json_p.exists():
        try:
            with open(json_p, "r", encoding="utf-8") as f:
                data = json.load(f)
                summary = data.get("summary", {})
                verdict = "PASSED" if summary.get("passed_sla") else "PENDING / FAILED"
                print(f"• Final SLA Verdict: {verdict}")
        except Exception:
            pass

    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check soak test status")
    parser.add_argument("--report", default="logs/soak_test_report.json")
    parser.add_argument("--csv", default="logs/soak_test_report.csv")
    parser.add_argument("--pid", default="logs/soak_test.pid")
    args = parser.parse_args()
    check_status(args.report, args.csv, args.pid)
