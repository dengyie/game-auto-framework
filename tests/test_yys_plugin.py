"""
Test suite for Onmyoji (yys_mobile) plugin and cross-game dynamic registry.
Validates zero-core-change multi-game extensibility, pipeline loading, and execution.
"""

from __future__ import annotations

import pytest

from core.device.virtual import VirtualDevice
from plugins.registry import GamePluginRegistry
from plugins.yys_mobile.plugin import YYSMobilePlugin
from scheduler.dag import PipelineStatus


def test_yys_plugin_registration_and_discovery():
    """Verify GamePluginRegistry dynamically discovers and instantiates yys_mobile."""
    plugins = GamePluginRegistry.list_plugins()
    plugin_ids = [p["id"] for p in plugins]
    assert "mhxy_mobile" in plugin_ids
    assert "yys_mobile" in plugin_ids

    # Check yys_mobile manifest data
    yys_info = next(p for p in plugins if p["id"] == "yys_mobile")
    assert yys_info["name"] == "Onmyoji Automation Plugin"
    assert "yuhun" in yys_info["aliases"]

    # Verify instantiation via factory
    dev = VirtualDevice()
    dev.connect()
    plugin = GamePluginRegistry.create("yys_mobile", device=dev)
    assert isinstance(plugin, YYSMobilePlugin)
    assert plugin.plugin_id == "yys_mobile"
    assert "yuhun_farm" in plugin.pipelines
    assert "jiejie_raid" in plugin.pipelines
    assert "anti_bot_interceptor" in plugin.pipelines
    dev.disconnect()


def test_yys_yuhun_pipeline_flow():
    """Verify Yuhun (Soul 10/11) farming DAG execution and round counting."""
    dev = VirtualDevice()
    dev.connect()
    plugin = YYSMobilePlugin(device=dev)
    pipe = plugin.get_pipeline("yuhun_farm")
    assert pipe is not None

    plugin.context.variables["in_yuhun_lobby"] = True
    plugin.context.variables["yuhun_count"] = 0
    plugin.context.variables["max_yuhun_count"] = 2

    # 1. Entry: check_lobby -> wait_battle
    status = plugin.run_pipeline_step("yuhun_farm")
    assert status == PipelineStatus.RUNNING
    assert pipe.current_node_name == "wait_battle"
    assert plugin.context.variables["in_battle"] is True

    # 2. wait_battle -> check_settlement
    status = plugin.run_pipeline_step("yuhun_farm")
    assert pipe.current_node_name == "check_settlement"

    # 3. check_settlement -> increment_run
    status = plugin.run_pipeline_step("yuhun_farm")
    assert pipe.current_node_name == "increment_run"
    assert plugin.context.variables["battle_settlement_active"] is False

    # 4. increment_run -> loops back to check_lobby since count (1) < max (2)
    status = plugin.run_pipeline_step("yuhun_farm")
    assert plugin.context.variables["yuhun_count"] == 1
    assert pipe.current_node_name == "check_lobby"

    # Advance to max runs
    plugin.context.variables["yuhun_count"] = 2
    status = plugin.run_pipeline_step("yuhun_farm")
    assert pipe.current_node_name == "yuhun_finish"

    # Terminal node
    status = plugin.run_pipeline_step("yuhun_farm")
    assert status == PipelineStatus.COMPLETED
    dev.disconnect()


def test_yys_jiejie_raid_pipeline_flow():
    """Verify Realm Raid (Jiejie) ticket consumption and target attack."""
    dev = VirtualDevice()
    dev.connect()
    plugin = YYSMobilePlugin(device=dev)
    pipe = plugin.get_pipeline("jiejie_raid")
    assert pipe is not None

    plugin.context.variables["raid_tickets"] = 1

    # 1. check_tickets has tickets -> select_target
    status = plugin.run_pipeline_step("jiejie_raid")
    assert status == PipelineStatus.RUNNING
    assert pipe.current_node_name == "select_target"

    # 2. select_target -> confirm_attack
    status = plugin.run_pipeline_step("jiejie_raid")
    assert pipe.current_node_name == "confirm_attack"
    assert plugin.context.variables["target_selected"] is True

    # 3. confirm_attack -> wait_raid_combat
    status = plugin.run_pipeline_step("jiejie_raid")
    assert pipe.current_node_name == "wait_raid_combat"
    assert plugin.context.variables["raid_tickets"] == 0

    # 4. wait_raid_combat -> check_tickets
    status = plugin.run_pipeline_step("jiejie_raid")
    assert pipe.current_node_name == "check_tickets"

    # 5. check_tickets with 0 tickets branches to raid_finish
    status = plugin.run_pipeline_step("jiejie_raid")
    assert pipe.current_node_name == "raid_finish"

    # Terminal node
    status = plugin.run_pipeline_step("jiejie_raid")
    assert status == PipelineStatus.COMPLETED
    dev.disconnect()


def test_yys_bounty_interrupt_handling():
    """Verify high-priority global popup interception (Cooperation Bounty)."""
    dev = VirtualDevice()
    dev.connect()
    plugin = YYSMobilePlugin(device=dev)
    pipe = plugin.get_pipeline("yuhun_farm")
    assert pipe is not None

    # Normal state in lobby
    plugin.context.variables["in_yuhun_lobby"] = True
    status = plugin.run_pipeline_step("yuhun_farm")
    assert status == PipelineStatus.RUNNING
    assert pipe.current_node_name == "wait_battle"

    # Incoming cooperation bounty popup arrives!
    plugin.context.variables["bounty_invite_popup"] = True
    status = plugin.run_pipeline_step("yuhun_farm")
    assert status == PipelineStatus.RUNNING
    # Verify interrupt occurred and resolved
    assert "INTERRUPT:check_bounty_popup" in plugin.context.history
    assert plugin.context.variables["bounty_invite_popup"] is False
    assert plugin.context.variables["bounty_accepted"] is True

    dev.disconnect()
