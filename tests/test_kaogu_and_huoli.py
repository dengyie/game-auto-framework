"""
Tests for Workshop Archaeology (gongfang_kaogu) and Vigor & Commerce (huoli_shanghui) Pipelines,
plus M2 Full Routine Chaining.
"""

from core.device.virtual import VirtualDevice
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from scheduler.dag import PipelineStatus
from scheduler.routine import RoutineConfig, RoutineStatus, TaskRoutineExecutor


def test_kaogu_flow_with_buying_shovels():
    """Verify archaeology pipeline handles purchasing shovels, digging, and appraising."""
    dev = VirtualDevice()
    plugin = MHXYMobilePlugin(device=dev)
    pipe = plugin.get_pipeline("gongfang_kaogu")
    assert pipe is not None

    plugin.context.variables["shovel_count"] = 0
    plugin.context.variables["buy_shovel_amount"] = 3
    plugin.context.variables["max_digs"] = 1

    # 1. Entry: shovel_count <= 0 branches to buy_shovels
    status = plugin.run_pipeline_step("gongfang_kaogu")
    assert status == PipelineStatus.RUNNING
    assert pipe.current_node_name == "buy_shovels"

    # 2. buy_shovels -> use_shovel_to_navigate
    status = plugin.run_pipeline_step("gongfang_kaogu")
    assert pipe.current_node_name == "use_shovel_to_navigate"
    assert plugin.context.variables["shovel_count"] == 3

    # 3. use_shovel_to_navigate -> wait_reach_tomb
    status = plugin.run_pipeline_step("gongfang_kaogu")
    assert pipe.current_node_name == "wait_reach_tomb"

    # 4. wait_reach_tomb -> handle_dig_outcome
    status = plugin.run_pipeline_step("gongfang_kaogu")
    assert pipe.current_node_name == "handle_dig_outcome"
    assert plugin.context.variables["shovel_count"] == 2
    assert plugin.context.variables["digs_completed"] == 1

    # 5. handle_dig_outcome -> appraise_relics (since digs_completed == max_digs)
    status = plugin.run_pipeline_step("gongfang_kaogu")
    assert pipe.current_node_name == "appraise_relics"

    # 6. appraise_relics -> kaogu_finish
    status = plugin.run_pipeline_step("gongfang_kaogu")
    assert pipe.current_node_name == "kaogu_finish"
    assert plugin.context.variables["kaogu_finished"] is True

    # Terminal node
    status = plugin.run_pipeline_step("gongfang_kaogu")
    assert status == PipelineStatus.COMPLETED


def test_huoli_shanghui_flow():
    """Verify vigor consumption and Chamber of Commerce batch selling pipeline."""
    dev = VirtualDevice()
    plugin = MHXYMobilePlugin(device=dev)
    pipe = plugin.get_pipeline("huoli_shanghui")
    assert pipe is not None

    plugin.context.variables["current_huoli"] = 600
    plugin.context.variables["min_huoli_threshold"] = 300
    plugin.context.variables["huoli_strategy"] = "work"
    plugin.context.variables["has_unbound_items"] = True

    # 1. Entry: huoli >= 300 branches to consume_huoli
    status = plugin.run_pipeline_step("huoli_shanghui")
    assert status == PipelineStatus.RUNNING
    assert pipe.current_node_name == "consume_huoli"

    # 2. consume_huoli -> open_shanghui
    status = plugin.run_pipeline_step("huoli_shanghui")
    assert pipe.current_node_name == "open_shanghui"
    assert plugin.context.variables["current_huoli"] == 300
    assert plugin.context.variables["huoli_consumed"] is True

    # 3. open_shanghui -> sell_items
    status = plugin.run_pipeline_step("huoli_shanghui")
    assert pipe.current_node_name == "sell_items"

    # 4. sell_items -> huoli_shanghui_finish
    status = plugin.run_pipeline_step("huoli_shanghui")
    assert pipe.current_node_name == "huoli_shanghui_finish"
    assert plugin.context.variables["shanghui_cleared"] is True

    # Terminal node
    status = plugin.run_pipeline_step("huoli_shanghui")
    assert status == PipelineStatus.COMPLETED


def test_m2_full_routine_chaining():
    """Verify TaskRoutineExecutor chains M2 pipelines with shorthand aliases."""
    dev = VirtualDevice()
    plugin = MHXYMobilePlugin(device=dev)

    config = RoutineConfig(
        name="m2_farming_routine",
        pipelines=["zhuogui", "fuben", "kaogu", "huoli"],
    )
    executor = TaskRoutineExecutor(plugin=plugin, config=config)

    # Verify alias normalization
    assert executor._normalized_pipelines == [
        "team_zhuogui",
        "fuben_320_520",
        "gongfang_kaogu",
        "huoli_shanghui",
    ]

    # Pre-seed conditions so pipelines advance smoothly
    plugin.context.variables["max_zhuogui_rounds"] = 1
    plugin.context.variables["fuben_max_stages"] = 1
    plugin.context.variables["max_digs"] = 1
    plugin.context.variables["shovel_count"] = 2
    plugin.context.variables["current_huoli"] = 400

    executor.start()
    for _ in range(80):
        status = executor.tick()
        if status in (RoutineStatus.COMPLETED, RoutineStatus.FAILED, RoutineStatus.CIRCUIT_BROKEN):
            break

    assert executor.status == RoutineStatus.COMPLETED
    assert executor.completed_pipelines == [
        "team_zhuogui",
        "fuben_320_520",
        "gongfang_kaogu",
        "huoli_shanghui",
    ]
