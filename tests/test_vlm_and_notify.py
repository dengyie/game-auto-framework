"""
Tests for Multi-modal VLM Engine and Multi-channel Webhook Alert Notifier.
"""

import numpy as np
import pytest

from core.ocr.vlm import VLMClient
from core.notify.webhook import WebhookNotifier
from plugins.mhxy_mobile.custom.vlm_solver import MHXYVLMSolver
from scheduler.routine import RoutineConfig, RoutineStatus, TaskRoutineExecutor
from core.device.virtual import VirtualDevice
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin


def test_vlm_client_mock_inference():
    """Verify VLMClient operates deterministically in offline mock mode."""
    vlm = VLMClient(enable_mock_fallback=True)
    fake_img = np.zeros((200, 200, 3), dtype=np.uint8)

    # 1. Ask image
    answer_text = vlm.ask_image(fake_img, "请描述画面中的内容")
    assert isinstance(answer_text, str)
    assert len(answer_text) > 0

    # 2. Multi-choice question solving
    res = vlm.solve_question(
        image=fake_img,
        question="《梦幻西游》手游中地府门派的师傅是谁？",
        options=["地藏王", "菩提祖师", "观音菩萨", "镇元大仙"],
    )
    assert "option_index" in res
    assert 0 <= res["option_index"] < 4
    assert res["confidence"] > 0.0
    assert "answer" in res


def test_mhxy_vlm_solver():
    """Verify MHXYVLMSolver exam and anti-bot challenge solving."""
    solver = MHXYVLMSolver()
    fake_img = np.zeros((150, 150, 3), dtype=np.uint8)

    # Exam question
    exam_res = solver.solve_exam(
        image=fake_img,
        question="科举乡试：唐代著名的诗仙是谁？",
        options=["李白", "杜甫", "白居易", "王维"],
    )
    assert 0 <= exam_res["option_index"] <= 3

    # Anti-bot captcha
    cx, cy = solver.solve_anti_bot_captcha(
        image=fake_img,
        prompt_text="请点击面向正前方的角色",
        option_bboxes=[(300, 300, 50, 50), (450, 300, 50, 50)],
    )
    assert isinstance(cx, int) and isinstance(cy, int)
    assert cx > 0 and cy > 0


def test_webhook_notifier_all_channels():
    """Verify WebhookNotifier broadcasts across Feishu, WeChat Work, and Telegram."""
    notifier = WebhookNotifier()

    # Individual channels in mock mode
    assert notifier.send_feishu("Test Alert", "Content message") is True
    assert notifier.send_wechat("Test Alert", "Content message") is True
    assert notifier.send_telegram("Test Alert", "Content message") is True

    # Broadcast
    res = notifier.send_alert(
        title="自动化监控警告",
        message="检测到角色处于空闲状态",
        level="warning",
        image_bytes=b"fake_image_bytes",
        channels=["feishu", "wechat", "telegram"],
    )
    assert res["feishu"] is True
    assert res["wechat"] is True
    assert res["telegram"] is True

    # Circuit breaker alert
    cb_res = notifier.send_circuit_breaker_alert(
        device_name="TestDevice-01",
        routine_name="daily_routine",
        reason="连续2次防作弊识别未通过",
    )
    assert cb_res["feishu"] is True


def test_routine_circuit_breaker_triggers_webhook():
    """Verify that Routine circuit breaker automatically invokes WebhookNotifier."""
    dev = VirtualDevice()
    plugin = MHXYMobilePlugin(device=dev)
    config = RoutineConfig(name="test_cb_routine", pipelines=["shimen"], max_anti_bot_fails=2)
    executor = TaskRoutineExecutor(plugin=plugin, config=config)

    executor.start()
    plugin.context.variables["anti_bot_failed_count"] = 2

    status = executor.tick()
    assert status == RoutineStatus.CIRCUIT_BROKEN
    assert "circuit breaker" in executor.error_message.lower()
