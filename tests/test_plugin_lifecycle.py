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


def test_on_pipeline_started_resets_dig_state_and_stale_cache():
    """Review P2：routine 重试复用同一个 PluginContext（routine.py 有意保留
    ctx.variables），若不重置，digital 从失败 run 继承的购图预算/尝试计数会让
    重试必然再次超时；on_pipeline_started 必须在 daily_baotu (re)start 时清零
    dig-state，同时清掉跨 pipeline 泄漏的帧缓存。"""
    device = VirtualDevice()
    device.connect()
    plugin = MHXYMobilePlugin(device=device)
    v = plugin.context.variables
    v["treasure_map_buy_attempts"] = 3
    v["treasure_map_buys_this_dig"] = 1
    v["_last_frame_items"] = ["stale-items-from-shimen"]
    v["_last_frame"] = "stale-frame-bytes"

    plugin.on_pipeline_started("daily_baotu")

    assert v["treasure_map_buy_attempts"] == 0
    assert v["treasure_map_buys_this_dig"] == 0
    assert "_last_frame_items" not in v
    assert "_last_frame" not in v
    device.disconnect()


def test_on_pipeline_started_keeps_dig_state_for_other_pipelines():
    """仅 baotu 管线的 dig-state 被重置；其他管线启动（如 daily_shimen）不能
    干扰 baotu 计数。"""
    device = VirtualDevice()
    device.connect()
    plugin = MHXYMobilePlugin(device=device)
    v = plugin.context.variables
    v["treasure_map_buy_attempts"] = 2
    v["dig_count"] = 5

    plugin.on_pipeline_started("daily_shimen")

    assert v["treasure_map_buy_attempts"] == 2
    assert v["dig_count"] == 5
    device.disconnect()


def test_baotu_shop_never_opens_times_out_then_retry_restarts_clean():
    """Review P2 end-to-end：商铺打不开（无「购买」按钮）时环路诚实超时而不是
    盲点坐标；routine 重试（status 置回 IDLE）经 on_pipeline_started 重置后
    重试不再继承失败的 attempts，具备再次购图的机会。"""
    import time
    device = VirtualDevice()
    device.connect()
    plugin = MHXYMobilePlugin(device=device)
    pipe = plugin.get_pipeline("daily_baotu")
    plugin.context.variables.update(
        {
            "has_treasure_map": False,
            "dig_count": 2,
            "treasure_map_buys_this_dig": 0,
            "treasure_map_buy_attempts": 0,
        }
    )
    pipe.start()
    # 直接钉在购图节点（与既有 dig-loop 测试一致），避免 entry 在虚拟设备上竞速
    pipe.current_node_name = "buy_map_to_dig"

    # 无新鲜帧（DummyDevice 语义）→ 三次尝试后 needs_treasure_map 永久 False
    status = plugin.run_pipeline_step("daily_baotu")
    assert status == PipelineStatus.RUNNING
    assert plugin.context.variables["treasure_map_buy_attempts"] == 1

    pipe.node_entered_time = time.time() - 21.0  # timeout_sec=20
    status = plugin.run_pipeline_step("daily_baotu")
    assert status == PipelineStatus.TIMEOUT

    # 模拟 routine 重试：置回 IDLE -> pipeline.start() -> on_pipeline_started
    pipe.status = PipelineStatus.IDLE
    pipe.current_node_name = "accept_baotu_task"
    status = plugin.run_pipeline_step("daily_baotu")
    assert status == PipelineStatus.RUNNING
    assert plugin.context.variables["treasure_map_buy_attempts"] == 0
    device.disconnect()
