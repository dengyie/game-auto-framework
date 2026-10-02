"""
Autonomous Daily Activities DAG Runner for Fantasy Westward Journey Mobile.
Executes daily_dailies pipeline end-to-end with frame-by-frame evidence logging.

Ops contract (live 2026-09-30 review):
- Logs go BOTH to stderr (INFO, no ANSI) and logs/dailies_*.log (DEBUG, rotated) —
  a run must leave an auditable trail even when stdout/stderr redirection is forgotten
  (e.g. scheduled runs), and the per-tick summary lines must stream in real time.
- One screencap/handler failure must not kill the run silently: guarded retries with
  a streak breaker; the Summary line prints in a finally block no matter what.
- Exit codes let scheduled supervision tell outcomes apart: 0 completed / ticks
  exhausted, 1 TIMEOUT/FAILED (incl. escape Tier-3 abort), 2 startup failure.
- A SelfHealingEscapeManager is wired with REAL device callbacks (previously dormant:
  the manager was never constructed and its default handlers were log-only stubs).
  Note: the daily pipeline's sense recognizer returns True every tick, so record_progress
  rarely starves; the primary loop breaker is the DAG stall watchdog (scheduler/dag.py).
- Lifecycle: device.connect() returns bool (checked before the loop) and device.disconnect()
  runs in the finally block so the ADB session never leaks across runs.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device.adb import AdbDevice
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from plugins.mhxy_mobile.custom.daily_state import load_daily_state, save_daily_state
from scheduler.dag import PipelineContext, PipelineStatus
from scheduler.escape import SelfHealingEscapeManager

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

SCREENCAP_ATTEMPTS = 3
SCREENCAP_STREAK_BREAK = 3
TICK_ERROR_STREAK_BREAK = 5
TARGET_PACKAGE = "com.netease.my"
FG_RESTART_STREAK_BREAK = 3


def ensure_game_foreground(device, package_name: str, restart_streak: int) -> int:
    """Re-launch the client when it lost the foreground; return the updated streak.

    Live 2026-10-02: 30 promo-carousel BACKs walked the client all the way to the
    MuMu launcher, where the desktop's own 每日新发现 promo widget kept re-classifying
    as popup_open — acting on launcher pixels can only ever make things worse, so
    the runner must restore the client itself. Callers abort when the streak reaches
    FG_RESTART_STREAK_BREAK (client keeps leaving / cannot launch).
    """
    if device.is_foreground_app(package_name):
        return 0
    streak = restart_streak + 1
    logger.warning(
        f"Game client not in foreground (streak {streak}/{FG_RESTART_STREAK_BREAK}); "
        f"re-launching {package_name}..."
    )
    try:
        device.start_app(package_name)
    except Exception as e:
        logger.error(f"start_app({package_name}) failed: {e}")
    return streak


def _setup_logging() -> Path:
    """stderr INFO (no ANSI — grep-able when redirected) + rotated DEBUG file sink."""
    LOG_DIR.mkdir(exist_ok=True)
    logfile = LOG_DIR / time.strftime("dailies_%Y%m%d_%H%M%S.log")
    logger.remove()
    logger.add(sys.stderr, level="INFO", colorize=False)
    logger.add(logfile, level="DEBUG", rotation="5 MB", retention=10, encoding="utf-8")
    return logfile


def _restore_state(ctx: PipelineContext) -> None:
    """Resume today's progress (completed dailies + last 活跃度) so a restarted run
    does not redo or mis-report. Rows are day-keyed — nothing survives the 0 点 reset."""
    try:
        saved = load_daily_state()
    except Exception as e:
        logger.warning(f"[state] Failed to load daily state: {e}")
        return
    restored = []
    completed = ctx.variables.setdefault("completed_tasks", [])
    for task in saved.get("completed_tasks") or []:
        if task not in completed:
            completed.append(task)
            restored.append(task)
    if saved.get("huoyue") is not None:
        # Seed only if the pipeline hasn't measured fresher (panel measurement overwrites).
        ctx.variables.setdefault("current_huoyue", saved["huoyue"])
    if restored or saved.get("huoyue") is not None:
        logger.info(
            f"[state] Resumed today's progress: completed_tasks restored={restored}, "
            f"already_done={completed}, 活跃度={ctx.variables.get('current_huoyue')}"
        )


def main(max_ticks: int = 30, serial: str = "127.0.0.1:55556", queue: list | None = None) -> int:
    logfile = _setup_logging()
    logger.info(f"Connecting to device [{serial}]...")
    device = AdbDevice(serial=serial)
    if not device.connect():
        logger.error(f"Failed to connect to ADB device [{serial}]. Aborting.")
        return 2

    status = PipelineStatus.IDLE
    ctx = None  # bound so the finally Summary can run even if context build fails
    try:
        logger.info("Initializing MHXYMobilePlugin and daily_dailies DAG pipeline...")
        plugin = MHXYMobilePlugin(device=device)
        pipeline = plugin.get_pipeline("daily_dailies")
        if not pipeline:
            logger.error("Failed to load daily_dailies pipeline!")
            return 2

        # Escape tiers with REAL device actions (previously the defaults were log-only
        # stubs and the manager was never constructed at all).
        esc_abort = threading.Event()

        def _minor_escape() -> None:
            logger.warning("[escape] Tier1: pressing BACK once to clear overlay")
            if hasattr(device, "press_key"):
                device.press_key(4)

        def _medium_escape() -> None:
            logger.warning("[escape] Tier2: pressing BACK and giving the UI 3s to settle")
            if hasattr(device, "press_key"):
                device.press_key(4)
                time.sleep(3.0)

        def _major_escape() -> None:
            # Hard-restarting the emulator automatically is destructive; instead abort the
            # run with a failure exit code so scheduled supervision can restart it cleanly.
            logger.critical("[escape] Tier3: persistent stall — aborting run (exit 1, supervised restart expected)")
            esc_abort.set()

        escape_manager = SelfHealingEscapeManager(
            on_minor_escape=_minor_escape,
            on_medium_escape=_medium_escape,
            on_major_escape=_major_escape,
        )

        ctx = PipelineContext(device=device, escape_manager=escape_manager)
        plugin.register_custom_operators(ctx)
        ctx.variables["pet_type"] = "attack"
        ctx.variables["daily_queue"] = queue or ["师门任务", "宝图任务", "秘境降妖", "科举乡试", "三界奇缘", "运镖"]
        logger.info(f"Daily queue: {ctx.variables['daily_queue']}")
        _restore_state(ctx)

        screencap_streak = 0
        tick_error_streak = 0
        fg_restart_streak = 0
        pipeline.start()
        logger.info(
            f"Pipeline started at node [{pipeline.current_node_name}]. "
            f"Beginning autonomous loop (max_ticks={max_ticks})..."
        )
        for tick in range(1, max_ticks + 1):
            if esc_abort.is_set():
                status = PipelineStatus.FAILED
                break

            # Screencap with guarded retries: a transient ADB hiccup (or the emulator
            # dying mid-run, live 2026-09-29 Run 4) previously crashed the whole run
            # with no summary. screencap_mat returns None on failure (no bytes decode).
            frame = None
            for attempt in range(1, SCREENCAP_ATTEMPTS + 1):
                try:
                    frame = device.screencap_mat()
                    if frame is not None:
                        break
                    logger.warning(f"Screencap attempt {attempt}/{SCREENCAP_ATTEMPTS}: no frame")
                except Exception as e:
                    logger.warning(f"Screencap attempt {attempt}/{SCREENCAP_ATTEMPTS} failed: {e}")
                time.sleep(2.0)
            if frame is None:
                screencap_streak += 1
                logger.error(f"Screencap failed {SCREENCAP_ATTEMPTS}x (streak {screencap_streak})")
                if screencap_streak >= SCREENCAP_STREAK_BREAK:
                    logger.error("Screencap streak limit reached; device is gone. Aborting run.")
                    status = PipelineStatus.FAILED
                    break
                continue
            screencap_streak = 0

            # Foreground guard: any BACK source (promo dismissal, quiz escape,
            # escape tiers) can pop the client off its last activity and drop the
            # run onto the launcher, where OCR-ing desktop widgets only makes
            # things worse. Restore the client and give it time to settle before
            # the next tick; abort after repeated walk-outs.
            fg_restart_streak = ensure_game_foreground(device, TARGET_PACKAGE, fg_restart_streak)
            if fg_restart_streak >= FG_RESTART_STREAK_BREAK:
                logger.error("Game client keeps leaving the foreground. Aborting run.")
                status = PipelineStatus.FAILED
                break
            if fg_restart_streak > 0:
                time.sleep(20.0)  # engine splash + login/auto-nav needs time to settle
                ctx.variables.pop("promo_back_streak", None)  # fresh episode after relaunch
                continue

            try:
                prev_node = pipeline.current_node_name
                status = pipeline.tick(ctx, frame)
                curr_node = pipeline.current_node_name
            except Exception:
                tick_error_streak += 1
                logger.exception(f"Tick {tick} pipeline error (streak {tick_error_streak})")
                if tick_error_streak >= TICK_ERROR_STREAK_BREAK:
                    logger.error("Tick error streak limit reached. Aborting run.")
                    status = PipelineStatus.FAILED
                    break
                time.sleep(1.0)
                continue
            tick_error_streak = 0

            completed_tasks = ctx.variables.get("completed_tasks", [])
            curr_task = ctx.variables.get("current_task_name", "")
            logger.info(
                f"[Tick {tick:02d}] {prev_node} -> {curr_node} | status={status.name} "
                f"| task={curr_task} | completed={completed_tasks}"
            )

            if status in (PipelineStatus.COMPLETED, PipelineStatus.FAILED, PipelineStatus.TIMEOUT):
                logger.info(f"Pipeline reached terminal status [{status.name}] at tick {tick}")
                break

            time.sleep(1.0)
    except Exception:
        logger.exception("Runner fatal error")
        status = PipelineStatus.FAILED
    finally:
        # The Summary must print no matter how the loop ended (crash, device death,
        # escape abort) — it is the only machine-readable end-of-run record.
        try:
            if ctx is not None:
                logger.info(
                    "Autonomous run completed. Summary: "
                    f"completed_tasks={ctx.variables.get('completed_tasks', [])}, "
                    f"all_done={ctx.variables.get('all_dailies_done', False)}, "
                    f"活跃度={ctx.variables.get('current_huoyue')}, "
                    f"escort_deferred={ctx.variables.get('escort_deferred', False)}, "
                    f"mijing_quota_exhausted={ctx.variables.get('mijing_quota_exhausted', False)}, "
                    f"mijing_blocked={ctx.variables.get('mijing_blocked', False)}, "
                    f"promo_blocked={ctx.variables.get('promo_block_latch', False)}, "
                    f"status={status.name}"
                )
        except Exception:
            logger.exception("Failed to emit run summary")
        if ctx is not None:
            try:
                save_daily_state(
                    ctx.variables.get("completed_tasks", []),
                    ctx.variables.get("current_huoyue"),
                )
                logger.info(f"[state] Saved today's progress ({logfile.name})")
            except Exception as e:
                logger.warning(f"[state] Failed to save daily state: {e}")
        try:
            device.disconnect()
        except Exception:
            pass

    if status == PipelineStatus.COMPLETED:
        return 0
    if status in (PipelineStatus.TIMEOUT, PipelineStatus.FAILED):
        return 1
    # Ticks exhausted while still RUNNING is a normal end for this runner's usage
    # — unless the run is latched behind an undismissable promo overlay: idling
    # to the end there must not report success to the scheduler.
    if ctx is not None and ctx.variables.get("promo_block_latch"):
        logger.error("Ticks exhausted with promo_block_latch set — reporting failure")
        return 1
    return 0


if __name__ == "__main__":
    import argparse

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
    sys.exit(main(max_ticks=args.ticks, serial=args.serial, queue=focus_queue))
