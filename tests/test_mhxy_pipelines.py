"""End-to-end unit and simulation tests for MHXY Mobile Plugin pipelines and Quiz solver."""

from core.device.virtual import VirtualDevice
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from plugins.mhxy_mobile.custom.quiz import QuizSolver
from scheduler.dag import PipelineStatus


def test_mhxy_plugin_loads_all_pipelines():
    device = VirtualDevice()
    plugin = MHXYMobilePlugin(device=device)

    assert "daily_shimen" in plugin.pipelines
    assert "daily_baotu" in plugin.pipelines
    assert "daily_yuntong" in plugin.pipelines
    assert "anti_bot_interceptor" in plugin.pipelines


def test_quiz_solver_accuracy():
    solver = QuizSolver()

    # Question 1: Master of DT
    idx, opt_text, conf = solver.solve("大唐官府的门派师傅是谁？", ["程咬金", "李世民", "秦叔宝", "尉迟恭"])
    assert idx == 0
    assert opt_text == "程咬金"
    assert conf > 0.6

    # Question 2: Baotu daily limit
    idx2, opt_text2, conf2 = solver.solve("藏宝图每天最多可以打几张？", ["5", "10", "15", "20"])
    assert idx2 == 1
    assert opt_text2 == "10"
    assert conf2 > 0.6

    # Question 3: Jin Chuang Yao recovery
    idx3, opt_text3, conf3 = solver.solve("金疮药可以恢复什么？", ["魔法", "愤怒", "气血", "气力"])
    assert idx3 == 2
    assert opt_text3 == "气血"
    assert conf3 > 0.6


def test_daily_shimen_pipeline_flow():
    device = VirtualDevice()
    plugin = MHXYMobilePlugin(device=device)

    # Initialize variables for shimen flow
    plugin.context.variables["shimen_rounds"] = 19
    plugin.context.variables["has_shimen_quest"] = True
    plugin.context.variables["master_dialog_open"] = True

    # Step 1: Start check_task_list
    status1 = plugin.run_pipeline_step("daily_shimen")
    assert status1 == PipelineStatus.RUNNING

    # Step 2: Transition to talk_to_master
    status2 = plugin.run_pipeline_step("daily_shimen")
    assert status2 == PipelineStatus.RUNNING

    # Step 3: Advance and increment round to 20
    plugin.context.variables["shimen_rounds"] = 20
    pipe = plugin.get_pipeline("daily_shimen")
    pipe.current_node_name = "increment_round"

    # Step 4: Branch check should route to shimen_finish
    status3 = plugin.run_pipeline_step("daily_shimen")
    assert pipe.current_node_name == "shimen_finish"

    # Step 5: Terminal node reached
    status4 = plugin.run_pipeline_step("daily_shimen")
    assert status4 == PipelineStatus.COMPLETED


def test_daily_baotu_pipeline_flow():
    device = VirtualDevice()
    plugin = MHXYMobilePlugin(device=device)

    # Simulate fast-forwarding to dig completion
    plugin.context.variables["baotu_count"] = 10
    plugin.context.variables["has_treasure_map"] = True
    plugin.context.variables["dig_count"] = 9
    plugin.context.variables["dig_completed"] = True

    pipe = plugin.get_pipeline("daily_baotu")
    pipe.start()
    pipe.current_node_name = "wait_dig_finish"

    status = plugin.run_pipeline_step("daily_baotu")
    # dig_count incremented to 10, branch routes to baotu_finish
    assert plugin.context.variables["dig_count"] == 10
    assert pipe.current_node_name == "baotu_finish"

    # Terminal node
    final_status = plugin.run_pipeline_step("daily_baotu")
    assert final_status == PipelineStatus.COMPLETED


def test_daily_yuntong_pipeline_flow():
    device = VirtualDevice()
    plugin = MHXYMobilePlugin(device=device)

    # Simulate 3rd escort completion
    plugin.context.variables["yuntong_completed"] = 2
    plugin.context.variables["escort_reached"] = True

    pipe = plugin.get_pipeline("daily_yuntong")
    pipe.start()
    pipe.current_node_name = "deliver_escort"

    status = plugin.run_pipeline_step("daily_yuntong")
    assert plugin.context.variables["yuntong_completed"] == 3
    assert pipe.current_node_name == "yuntong_finish"

    final_status = plugin.run_pipeline_step("daily_yuntong")
    assert final_status == PipelineStatus.COMPLETED
