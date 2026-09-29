"""Tests for the P2 safety guards added in the 2026-09-30 review:

- _click edge-zone guard (safety redline enforced in code)
- open_activity_panel fallback: 1280x720 constant scaled by real frame size,
  and BACK-degradation after repeated misses (live: (353,64) hit 基础设置 at 1600x900)
- click_dialog_choice fallback degradation: blind default-slot clicks capped at 3,
  reset on any matched choice
- handle_quiz bank-miss header guard: no first-option blind click without a quiz
  header on screen (live: 青丘奇珍 banner reached the miss path)
"""

import numpy as np
import pytest
from unittest.mock import patch

from loguru import logger as loguru_logger

from plugins.mhxy_mobile.custom import daily_handlers as dh
from plugins.mhxy_mobile.custom.daily_handlers import (
    _click,
    click_dialog_choice,
    handle_quiz,
    open_activity_panel,
)
from scheduler.dag import NodeAction, PipelineContext


class DummyOCRItem:
    def __init__(self, text: str, center: tuple, confidence: float = 0.95):
        self.text = text
        self.center = center
        self.confidence = confidence
        self.bbox = (int(center[0]) - 20, int(center[1]) - 10, 40, 20)


class DummyDevice:
    def __init__(self):
        self.clicks = []
        self.keys = []

    def click(self, x, y):
        self.clicks.append((float(x), float(y)))

    def press_key(self, keycode):
        self.keys.append(keycode)


@pytest.fixture
def caplog_records():
    records = []
    handler_id = loguru_logger.add(records.append, level="DEBUG", colorize=False)
    try:
        yield records
    finally:
        loguru_logger.remove(handler_id)


# --- _click edge-zone guard ---------------------------------------------------

def test_click_blocked_outside_frame_bounds():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame"] = np.zeros((900, 1600, 3), dtype=np.uint8)
    _click(ctx, 5, 5)        # bezel
    _click(ctx, 1595, 450)   # right bezel
    _click(ctx, 400, 895)    # bottom bezel
    assert device.clicks == []

    _click(ctx, 400, 300)    # inside -> allowed
    assert device.clicks == [(400.0, 300.0)]


def test_click_allowed_without_frame_info():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    _click(ctx, 50, 50)      # no _last_frame -> guard skipped (tests / pre-classify)
    assert device.clicks == [(50.0, 50.0)]


# --- open_activity_panel fallback ----------------------------------------------

def test_open_panel_fallback_scales_to_frame_size():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    # No 活动 text parsed (overlay covering HUD) on a 1600x900 frame.
    ctx.variables["_last_frame_items"] = []
    ctx.variables["_last_frame"] = np.zeros((900, 1600, 3), dtype=np.uint8)
    open_activity_panel(ctx, NodeAction(type="custom", custom_func="open_activity_panel"))
    assert device.clicks == [(353 * 1.25, 64 * 1.25)]  # (441.25, 80.0) — the real button


def test_open_panel_fallback_degrades_to_back_after_3_misses():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = []
    ctx.variables["_last_frame"] = np.zeros((900, 1600, 3), dtype=np.uint8)
    act = NodeAction(type="custom", custom_func="open_activity_panel")
    for _ in range(3):
        open_activity_panel(ctx, act)
    assert len(device.clicks) == 3
    assert device.keys == []
    open_activity_panel(ctx, act)  # 4th miss: stop clicking, press BACK
    assert len(device.clicks) == 3
    assert device.keys == [4]
    # BACK resets the counter (no latch): the next miss retries the scaled tap
    # instead of pressing BACK forever (which would never open the panel again
    # even after the overlay is gone).
    assert ctx.variables["panel_fallback_count"] == 0
    open_activity_panel(ctx, act)
    assert len(device.clicks) == 4
    assert device.keys == [4]


def test_open_panel_fallback_counter_resets_when_panel_opens():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    # Two fallback misses happened, then the scaled tap opened the activity panel.
    ctx.variables["panel_fallback_count"] = 2
    panel_items = [
        DummyOCRItem("日常活动", (150.0, 300.0)),  # left tab column (x < 320)
        DummyOCRItem("活跃度 20", (900.0, 400.0)),  # bottom chest/活跃 strip
    ]
    with patch.object(dh, "_ocr_items", return_value=panel_items):
        dh.classify_screen(ctx, None)
    assert ctx.variables["panel_open"] is True
    assert ctx.variables["panel_fallback_count"] == 0
    # Next fallback miss starts a fresh cycle: blind tap, not BACK.
    ctx.variables["_last_frame_items"] = []
    open_activity_panel(ctx, NodeAction(type="custom", custom_func="open_activity_panel"))
    assert device.clicks and device.keys == []


# --- click_dialog_choice fallback degradation ----------------------------------

def _dialog_items(choice_text=None, y=500.0):
    items = [DummyOCRItem("请选择要做的事", (600.0, 450.0))]
    if choice_text:
        items.append(DummyOCRItem(choice_text, (1085.0, y)))
    return items


def test_dialog_fallback_clicks_default_slot_then_degrades_to_back():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _dialog_items()  # prompt but no valid choice
    act = NodeAction(type="custom", custom_func="click_dialog_choice")
    for _ in range(3):
        click_dialog_choice(ctx, act)
    assert device.clicks == [(1086.0, 468.0)] * 3
    assert device.keys == []
    click_dialog_choice(ctx, act)  # 4th: no more blind clicks
    assert len(device.clicks) == 3
    assert device.keys == [4]
    # BACK resets the counter (no latch): a later OCR-miss dialog gets a fresh
    # 3-try cycle, not an immediate cancel-BACK that would reflexively dismiss it.
    assert ctx.variables["dialog_fallback_count"] == 0
    click_dialog_choice(ctx, act)
    assert len(device.clicks) == 4
    assert device.keys == [4]


def test_dialog_fallback_counter_resets_on_matched_choice():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _dialog_items()
    act = NodeAction(type="custom", custom_func="click_dialog_choice")
    click_dialog_choice(ctx, act)
    click_dialog_choice(ctx, act)
    assert ctx.variables["dialog_fallback_count"] == 2
    # A real matched choice appears -> click it and reset the counter.
    ctx.variables["_last_frame_items"] = _dialog_items("说说话")
    click_dialog_choice(ctx, act)
    assert device.clicks[-1] == (1085.0, 500.0)
    assert ctx.variables["dialog_fallback_count"] == 0
    # Next fallback starts from scratch (blind slot, not BACK).
    ctx.variables["_last_frame_items"] = _dialog_items()
    click_dialog_choice(ctx, act)
    assert device.clicks[-1] == (1086.0, 468.0)


# --- handle_quiz bank-miss header guard ----------------------------------------

_BOGUS_Q = "这是一个完全不存在的题目呀呀呀？"


def _quiz_items(with_header=True):
    items = []
    if with_header:
        items.append(DummyOCRItem("三界奇缘", (700.0, 50.0)))
    items.append(DummyOCRItem(_BOGUS_Q, (700.0, 100.0)))   # question ROI (440..1135, 25..150)
    items.append(DummyOCRItem("选项甲", (500.0, 260.0)))    # option ROI (430..1280, 205..520)
    items.append(DummyOCRItem("选项乙", (900.0, 260.0)))
    return items


def test_quiz_bank_miss_without_header_refuses_blind_click():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _quiz_items(with_header=False)
    handle_quiz(ctx, NodeAction(type="custom", custom_func="handle_quiz"))
    assert device.clicks == [], "bank miss without a quiz header must not blind-click"


def test_quiz_bank_miss_with_header_clicks_first_option():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _quiz_items(with_header=True)
    handle_quiz(ctx, NodeAction(type="custom", custom_func="handle_quiz"))
    # Upstream policy intact inside a genuine quiz window: first option in ROI order.
    assert device.clicks == [(500.0, 260.0)]
