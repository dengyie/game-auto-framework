"""
Autonomous Daily Activities DAG Runner for Fantasy Westward Journey Mobile.
Executes daily_dailies pipeline end-to-end with frame-by-frame evidence logging.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import cv2
import numpy as np
from pathlib import Path
from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device.adb import AdbDevice
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from scheduler.dag import PipelineContext, PipelineStatus


def main(max_ticks: int = 30, serial: str = "127.0.0.1:55556", queue: list | None = None) -> None:
    logger.info(f"Connecting to device [{serial}]...")
    device = AdbDevice(serial=serial)
    if not device.connect():
        logger.error(f"Failed to connect to ADB device [{serial}]. Aborting.")
        sys.exit(1)

    try:
        logger.info("Initializing MHXYMobilePlugin and daily_dailies DAG pipeline...")
        plugin = MHXYMobilePlugin(device=device)
        pipeline = plugin.get_pipeline("daily_dailies")
        if not pipeline:
            logger.error("Failed to load daily_dailies pipeline!")
            sys.exit(1)

        ctx = PipelineContext(device=device)
        plugin.register_custom_operators(ctx)
        ctx.variables["pet_type"] = "attack"
        ctx.variables["daily_queue"] = queue or ["师门任务", "宝图任务", "秘境降妖", "科举乡试", "三界奇缘", "运镖"]
        logger.info(f"Daily queue: {ctx.variables['daily_queue']}")

        pipeline.start()
        logger.info(f"Pipeline started at node [{pipeline.current_node_name}]. Beginning autonomous loop (max_ticks={max_ticks})...")

        for tick in range(1, max_ticks + 1):
            frame = device.screencap_mat()
            if frame is None:
                logger.warning(f"[Tick {tick:02d}] Failed to capture frame from device [{serial}]. Retrying...")
                time.sleep(1.0)
                continue

            prev_node = pipeline.current_node_name
            status = pipeline.tick(ctx, frame)
            curr_node = pipeline.current_node_name

            completed_tasks = ctx.variables.get("completed_tasks", [])
            curr_task = ctx.variables.get("current_task_name", "")
            print(f"[Tick {tick:02d}] {prev_node} -> {curr_node} | status={status.name} | task={curr_task} | completed={completed_tasks}")

            if status in (PipelineStatus.COMPLETED, PipelineStatus.FAILED, PipelineStatus.TIMEOUT):
                logger.info(f"Pipeline reached terminal status [{status.name}] at tick {tick}")
                break

            time.sleep(1.0)

        logger.info(
            "Autonomous run completed. Summary: "
            f"completed_tasks={ctx.variables.get('completed_tasks', [])}, "
            f"all_done={ctx.variables.get('all_dailies_done', False)}, "
            f"活跃度={ctx.variables.get('current_huoyue')}, "
            f"escort_deferred={ctx.variables.get('escort_deferred', False)}, "
            f"mijing_quota_exhausted={ctx.variables.get('mijing_quota_exhausted', False)}, "
            f"mijing_blocked={ctx.variables.get('mijing_blocked', False)}"
        )
    finally:
        try:
            device.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Daily Activities DAG Runner for Fantasy Westward Journey Mobile")
    parser.add_argument("ticks", type=int, nargs="?", default=30, help="Max execution ticks (default: 30)")
    parser.add_argument("queue", type=str, nargs="?", default=None, help="Comma-separated queue override, e.g. '秘境降妖' or '师门任务,宝图任务'")
    parser.add_argument("--serial", "-s", type=str, default=os.getenv("ADB_SERIAL", "127.0.0.1:55556"), help="Target ADB serial (default: 127.0.0.1:55556 or $ADB_SERIAL)")
    args = parser.parse_args()

    focus_queue = (
        [t.strip() for t in args.queue.split(",") if t.strip()]
        if args.queue and args.queue.strip()
        else None
    )
    main(max_ticks=args.ticks, serial=args.serial, queue=focus_queue)
