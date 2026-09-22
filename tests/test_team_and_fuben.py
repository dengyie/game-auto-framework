"""
Tests for Team Ghost Hunting (team_zhuogui) and Dungeon (fuben_320_520) Pipelines.
"""

from core.device.virtual import VirtualDevice
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from scheduler.dag import PipelineStatus


def test_team_zhuogui_leader_flow():
    """Verify team leader ghost hunting pipeline from matchmaking to completion."""
    dev = VirtualDevice()
    plugin = MHXYMobilePlugin(device=dev)
    pipe = plugin.get_pipeline("team_zhuogui")
    assert pipe is not None

    plugin.context.variables["team_role"] = "leader"
    plugin.context.variables["max_zhuogui_rounds"] = 2
    plugin.context.variables["team_member_count"] = 1
    plugin.context.variables["double_points_active"] = False

    # 1. Entry: check_team_status -> leader_open_team_panel
    status = plugin.run_pipeline_step("team_zhuogui")
    assert status == PipelineStatus.RUNNING
    assert pipe.current_node_name == "leader_open_team_panel"

    # 2. leader_open_team_panel -> leader_create_team
    status = plugin.run_pipeline_step("team_zhuogui")
    assert pipe.current_node_name == "leader_create_team"

    # 3. leader_create_team -> leader_auto_match
    status = plugin.run_pipeline_step("team_zhuogui")
    assert pipe.current_node_name == "leader_auto_match"

    # 4. leader_auto_match -> leader_check_double
    status = plugin.run_pipeline_step("team_zhuogui")
    assert pipe.current_node_name == "leader_check_double"
    assert plugin.context.variables["team_member_count"] == 5

    # 5. leader_check_double -> find_zhongkui_npc
    status = plugin.run_pipeline_step("team_zhuogui")
    assert pipe.current_node_name == "find_zhongkui_npc"
    assert plugin.context.variables["double_points_active"] is True

    # 6. find_zhongkui_npc -> accept_ghost_task
    status = plugin.run_pipeline_step("team_zhuogui")
    assert pipe.current_node_name == "accept_ghost_task"

    # 7. accept_ghost_task -> track_ghost_king
    status = plugin.run_pipeline_step("team_zhuogui")
    assert pipe.current_node_name == "track_ghost_king"

    # 8. track_ghost_king -> wait_ghost_combat
    status = plugin.run_pipeline_step("team_zhuogui")
    assert pipe.current_node_name == "wait_ghost_combat"

    # 9. wait_ghost_combat -> ghost_combat_finish
    status = plugin.run_pipeline_step("team_zhuogui")
    assert pipe.current_node_name == "ghost_combat_finish"

    # 10. Round 1 finish: increment round -> branch check (1 < 2) -> loops to find_zhongkui_npc
    status = plugin.run_pipeline_step("team_zhuogui")
    assert plugin.context.variables["zhuogui_rounds"] == 1
    assert pipe.current_node_name == "find_zhongkui_npc"

    # Fast-forward round 2 to ghost_combat_finish
    pipe.current_node_name = "ghost_combat_finish"
    plugin.context.variables["in_ghost_battle"] = False

    # Round 2 finish: increment round -> branch check (2 >= 2) -> ghost_finish
    status = plugin.run_pipeline_step("team_zhuogui")
    assert plugin.context.variables["zhuogui_rounds"] == 2
    assert pipe.current_node_name == "ghost_finish"

    # Terminal node
    status = plugin.run_pipeline_step("team_zhuogui")
    assert status == PipelineStatus.COMPLETED


def test_team_zhuogui_member_flow():
    """Verify team member ghost hunting pipeline branching directly to follow and battle."""
    dev = VirtualDevice()
    plugin = MHXYMobilePlugin(device=dev)
    pipe = plugin.get_pipeline("team_zhuogui")

    plugin.context.variables["team_role"] = "member"
    plugin.context.variables["max_zhuogui_rounds"] = 1
    plugin.context.variables["is_following"] = True

    # Entry: branches immediately to member_find_team
    status = plugin.run_pipeline_step("team_zhuogui")
    assert status == PipelineStatus.RUNNING
    assert pipe.current_node_name == "member_find_team"

    # member_find_team -> member_following
    status = plugin.run_pipeline_step("team_zhuogui")
    assert pipe.current_node_name == "member_following"

    # Complete 1 round
    plugin.context.variables["zhuogui_rounds"] = 1
    status = plugin.run_pipeline_step("team_zhuogui")
    assert pipe.current_node_name == "ghost_finish"

    status = plugin.run_pipeline_step("team_zhuogui")
    assert status == PipelineStatus.COMPLETED


def test_fuben_320_520_flow():
    """Verify dungeon pipeline progression across dialog, combat, and settlement."""
    dev = VirtualDevice()
    plugin = MHXYMobilePlugin(device=dev)
    pipe = plugin.get_pipeline("fuben_320_520")
    assert pipe is not None

    plugin.context.variables["fuben_type"] = "320"
    plugin.context.variables["fuben_max_stages"] = 2

    # 1. Entry: check_activity_entry -> select_fuben
    status = plugin.run_pipeline_step("fuben_320_520")
    assert status == PipelineStatus.RUNNING
    assert pipe.current_node_name == "select_fuben"

    # 2. select_fuben -> handle_fuben_dialog
    status = plugin.run_pipeline_step("fuben_320_520")
    assert pipe.current_node_name == "handle_fuben_dialog"
    assert plugin.context.variables["inside_fuben"] is True

    # 3. handle_fuben_dialog -> wait_fuben_battle
    status = plugin.run_pipeline_step("fuben_320_520")
    assert pipe.current_node_name == "wait_fuben_battle"

    # 4. wait_fuben_battle -> fuben_battle_conclude
    status = plugin.run_pipeline_step("fuben_320_520")
    assert pipe.current_node_name == "fuben_battle_conclude"

    # 5. Advance stage 1 -> stage 2
    status = plugin.run_pipeline_step("fuben_320_520")
    assert plugin.context.variables["fuben_stage"] == 2
    assert pipe.current_node_name == "handle_fuben_dialog"

    # Fast forward stage 2 combat to conclusion
    pipe.current_node_name = "fuben_battle_conclude"
    plugin.context.variables["in_fuben_battle"] = False

    # Stage 2 advances to stage 3 (> 2) -> triggers settlement
    status = plugin.run_pipeline_step("fuben_320_520")
    assert plugin.context.variables["fuben_settlement_ready"] is True
    assert pipe.current_node_name == "fuben_settlement"

    # Settle -> fuben_finish
    status = plugin.run_pipeline_step("fuben_320_520")
    assert pipe.current_node_name == "fuben_finish"
    assert plugin.context.variables["fuben_completed"] is True

    # Terminal node
    status = plugin.run_pipeline_step("fuben_320_520")
    assert status == PipelineStatus.COMPLETED
