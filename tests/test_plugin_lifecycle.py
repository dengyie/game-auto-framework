"""Tests for Plugin lifecycle, operator registration, and end-to-end pipeline execution."""

from core.device.virtual import VirtualDevice
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from scheduler.dag import PipelineStatus


def test_mhxy_mobile_plugin_lifecycle():
    device = VirtualDevice()
    device.connect()

    plugin = MHXYMobilePlugin(device=device)
    assert plugin.plugin_id == "mhxy_mobile"
    assert "daily_shimen" in plugin.pipelines

    # Check that custom operators are registered
    ctx = plugin.context
    assert "find_shimen_tracker" in ctx.recognition_handlers
    assert "click_shimen_tracker" in ctx.action_handlers
    assert "detect_anti_bot_popup" in ctx.recognition_handlers

    # Run step 1: task tracker click
    ctx.variables["has_shimen_quest"] = True
    status = plugin.run_pipeline_step("daily_shimen")
    assert status == PipelineStatus.RUNNING
    assert "check_task_list" in ctx.history

    # Inject Anti-Bot Popup!
    ctx.variables["anti_bot_popup_active"] = True
    status = plugin.run_pipeline_step("daily_shimen")
    assert status == PipelineStatus.RUNNING
    assert "INTERRUPT:intercept_anti_bot_popup" in ctx.history
    assert ctx.variables["anti_bot_popup_active"] is False  # Successfully handled!

    device.disconnect()
