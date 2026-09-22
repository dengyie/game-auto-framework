"""
Comprehensive tests for LiveVLMDefenseSolver and anti-bot interrupt pipeline.
Verifies slider puzzle solving, sequential character clicking, auto-routing,
and MHXY plugin global interrupt integration.
"""

import numpy as np
import pytest

from core.device.virtual import VirtualDevice
from core.notify.webhook import WebhookNotifier
from core.vlm import LiveVLMDefenseSolver, VLMClient
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from scheduler.dag import NodeAction, NodeRecognition, PipelineContext


def test_vlm_client_slider_and_sequential():
    """Verify VLMClient parses slider and sequential mock responses properly."""
    client = VLMClient(enable_mock_fallback=True)
    fake_frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    # 1. Slider captcha
    slider_res = client.solve_slider_captcha(fake_frame, "拖动滑块完成拼图")
    assert "slider_x" in slider_res
    assert "slider_y" in slider_res
    assert "gap_x" in slider_res
    assert "distance" in slider_res
    assert slider_res["distance"] > 0
    assert slider_res["confidence"] >= 0.8

    # 2. Sequential captcha
    seq_res = client.solve_sequential_captcha(fake_frame, "请依次点击文字")
    assert "labels" in seq_res
    assert "points" in seq_res
    assert len(seq_res["points"]) >= 2
    assert seq_res["confidence"] >= 0.8


def test_live_vlm_defense_slider_puzzle():
    """Verify LiveVLMDefenseSolver executes humanized Bezier drag for slider."""
    device = VirtualDevice()
    assert device.connect()

    solver = LiveVLMDefenseSolver(device=device)
    fake_frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    success = solver.solve_slider_puzzle(
        frame=fake_frame,
        slider_start_hint=(420, 530),
        prompt_text="请拖动滑块完成拼图",
    )
    assert success is True

    # Check that events were logged in virtual driver
    events = device.input_driver.event_log
    assert any("DOWN" in ev for ev in events)
    assert any("MOVE" in ev for ev in events)
    assert any("UP" in ev for ev in events)


def test_live_vlm_defense_sequential_clicks():
    """Verify LiveVLMDefenseSolver executes sequential clicks with natural jitter."""
    device = VirtualDevice()
    assert device.connect()

    solver = LiveVLMDefenseSolver(device=device)
    fake_frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    success = solver.solve_sequential_text_click(
        frame=fake_frame,
        prompt_text="请依次点击【桃】【李】【满】【天】",
    )
    assert success is True

    events = device.input_driver.event_log
    # Must have multiple clicks (DOWN and UP pairs)
    down_count = sum(1 for ev in events if "DOWN" in ev)
    assert down_count >= 2


def test_live_vlm_defense_auto_solve_routing():
    """Verify auto_solve_challenge routes by prompt keywords."""
    device = VirtualDevice()
    assert device.connect()
    solver = LiveVLMDefenseSolver(device=device)
    fake_frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    # 1. Slider keyword
    res_slider = solver.auto_solve_challenge(
        frame=fake_frame,
        detected_text="按住滑块，拖动完成拼图",
    )
    assert res_slider is True

    # 2. Sequential click keyword
    res_seq = solver.auto_solve_challenge(
        frame=fake_frame,
        detected_text="请按顺序依次点击成语",
    )
    assert res_seq is True

    # 3. Trivia dialog keyword
    res_dialog = solver.auto_solve_challenge(
        frame=fake_frame,
        detected_text="请回答以下问题",
    )
    assert res_dialog is True


def test_mhxy_plugin_anti_bot_vlm_integration():
    """Verify MHXYMobilePlugin invokes LiveVLMDefenseSolver during anti-bot interrupt."""
    device = VirtualDevice()
    assert device.connect()
    plugin = MHXYMobilePlugin(device=device)

    ctx = PipelineContext()
    ctx.variables["anti_bot_popup_active"] = True
    ctx.variables["anti_bot_prompt_text"] = "拖动下方滑块完成拼图验证"

    rec = NodeRecognition(type="custom", custom_func="detect_anti_bot_popup")
    act = NodeAction(type="custom", custom_func="resolve_anti_bot_popup")

    # 1. Detect interrupt
    is_detected = plugin._detect_anti_bot_popup(ctx, frame=None, rec=rec)
    assert is_detected is True

    # 2. Resolve interrupt
    plugin._resolve_anti_bot_popup(ctx, act=act)

    # 3. Verify modal dismissed
    assert ctx.variables.get("anti_bot_popup_active") is False
    assert ctx.variables.get("anti_bot_prompt_text") == ""
