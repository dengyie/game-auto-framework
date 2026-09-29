"""Tests for the DAG static-frame stall watchdog, retry_count semantics, and the
eval_condition once-per-expr warning (P1 fixes from the 2026-09-30 review).

The stall watchdog replaces a naive transition-pair counter (which would false-
positive on long battles and escort travel) with a static-frame streak. wait_expected
exempts legitimate static waits (pathfinding/idle).
"""

import numpy as np
import pytest

from loguru import logger as loguru_logger

from scheduler.dag import (
    DAGNode,
    DAGPipeline,
    NodeAction,
    NodeRecognition,
    PipelineContext,
    PipelineStatus,
)


def _self_loop_pipeline(stall_warn_ticks=3, stall_fail_ticks=5):
    """A node that always recognizes and loops to itself: never times out on its own,
    so only the stall watchdog can break it."""
    node = DAGNode(
        name="loop",
        recognition=NodeRecognition(type="always"),
        next_nodes=["loop"],
        timeout_sec=9999.0,
    )
    return DAGPipeline(
        "stall",
        [node],
        "loop",
        stall_warn_ticks=stall_warn_ticks,
        stall_fail_ticks=stall_fail_ticks,
    )


def _blank_frame():
    return np.zeros((900, 1600, 3), dtype=np.uint8)


def test_static_frame_stall_breaks_pipeline():
    pipeline = _self_loop_pipeline(stall_warn_ticks=3, stall_fail_ticks=5)
    ctx = PipelineContext()
    pipeline.start()
    frame = _blank_frame()
    # tick 1 sets last_sig (streak 0); subsequent identical frames grow the streak.
    for _ in range(20):
        status = pipeline.tick(ctx, frame)
        if status == PipelineStatus.TIMEOUT:
            break
    assert pipeline.status == PipelineStatus.TIMEOUT
    assert pipeline._static_streak >= 5


def test_changing_frames_do_not_trigger_watchdog():
    pipeline = _self_loop_pipeline(stall_fail_ticks=5)
    ctx = PipelineContext()
    pipeline.start()
    a, b = _blank_frame(), np.full((900, 1600, 3), 50, dtype=np.uint8)
    for i in range(20):
        status = pipeline.tick(ctx, a if i % 2 == 0 else b)
        assert status == PipelineStatus.RUNNING
    assert pipeline.status == PipelineStatus.RUNNING
    assert pipeline._static_streak == 0


def test_wait_expected_exempts_static_wait():
    """Escort travel / pathfinding screens are legitimately static for minutes."""
    pipeline = _self_loop_pipeline(stall_fail_ticks=5)
    ctx = PipelineContext()
    pipeline.start()
    frame = _blank_frame()
    for _ in range(20):
        # Simulate a wait handler that sets wait_expected each tick.
        ctx.variables["wait_expected"] = True
        status = pipeline.tick(ctx, frame)
        assert status == PipelineStatus.RUNNING
    assert pipeline.status == PipelineStatus.RUNNING
    assert pipeline._static_streak == 0


def test_none_frame_resets_streak():
    pipeline = _self_loop_pipeline(stall_fail_ticks=3)
    ctx = PipelineContext()
    pipeline.start()
    # A screencap failure (frame None) must never itself trip the watchdog.
    for _ in range(10):
        assert pipeline.tick(ctx, None) == PipelineStatus.RUNNING
    assert pipeline._static_streak == 0


def test_retry_count_warning_when_node_never_advances(caplog_records):
    """A node with no next_nodes that keeps recognizing without advancing should
    give retry_count real semantics (previously dead code)."""
    node = DAGNode(
        name="stuck",
        recognition=NodeRecognition(type="always"),
        next_nodes=[],  # never advances
        max_retries=2,
        timeout_sec=9999.0,
    )
    pipeline = DAGPipeline("retry", [node], "stuck", stall_fail_ticks=9999)
    ctx = PipelineContext()
    pipeline.start()
    frame = _blank_frame()
    pipeline.tick(ctx, frame)  # retry_count 1
    pipeline.tick(ctx, frame)  # retry_count 2 == max_retries -> one-shot WARNING
    pipeline.tick(ctx, frame)  # retry_count 3, no second warning
    assert pipeline.retry_count == 3
    warnings = [r for r in caplog_records if "possible stall" in str(r)]
    assert len(warnings) == 1, f"expected exactly one retry warning, got {warnings}"


def test_eval_condition_warns_once_per_expression(caplog_records):
    ctx = PipelineContext()
    # NameError during warm-up: silent (debug-level), never warned.
    assert ctx.eval_condition("undefined_var > 1") is False
    assert all("Condition evaluation error" not in str(r) for r in caplog_records)
    # A real eval error: warned once.
    assert ctx.eval_condition("1 + 'a'") is False
    assert ctx.eval_condition("1 + 'a'") is False
    errs = [r for r in caplog_records if "Condition evaluation error for '1 + 'a''" in str(r)]
    assert len(errs) == 1, f"expected one warning, got {errs}"


class _KeyDevice:
    """AdbDevice-shaped key API: press_key (NOT key_event)."""

    def __init__(self):
        self.keys = []

    def press_key(self, key_code):
        self.keys.append(key_code)


def test_key_action_uses_press_key_not_dead_key_event():
    """type=key NodeActions were silent no-ops: _execute_action called the
    nonexistent device.key_event instead of AdbDevice.press_key."""
    device = _KeyDevice()
    ctx = PipelineContext(device=device)
    node = DAGNode(
        name="back",
        recognition=NodeRecognition(type="always"),
        action=NodeAction(type="key", key_code="BACK"),
        next_nodes=["back"],
        timeout_sec=9999.0,
    )
    pipeline = DAGPipeline("keys", [node], "back", stall_fail_ticks=9999)
    pipeline.start()
    pipeline.tick(ctx, _blank_frame())
    assert device.keys == ["BACK"]


# --- loguru -> list sink helper ----------------------------------------------
@pytest.fixture
def caplog_records():
    records = []
    handler_id = loguru_logger.add(records.append, level="DEBUG", colorize=False)
    try:
        yield records
    finally:
        loguru_logger.remove(handler_id)
