"""Unit tests for DAG pipeline execution and self-healing escape logic."""

import json
from pathlib import Path
from scheduler.dag import DAGPipeline, PipelineContext, PipelineStatus
from scheduler.escape import EscapeLevel, SelfHealingEscapeManager


def test_dag_pipeline_from_json():
    json_path = Path(__file__).parent.parent / "plugins" / "mhxy_mobile" / "pipelines" / "shimen.json"
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pipeline = DAGPipeline.from_dict(data)
    assert pipeline.name == "daily_shimen"
    assert len(pipeline.nodes) == 6
    assert len(pipeline.interrupt_nodes) == 1
    assert pipeline.interrupt_nodes[0].name == "intercept_anti_bot_popup"


def test_dag_pipeline_state_transition_and_interrupt():
    json_path = Path(__file__).parent.parent / "plugins" / "mhxy_mobile" / "pipelines" / "shimen.json"
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pipeline = DAGPipeline.from_dict(data)
    ctx = PipelineContext()

    state = {
        "shimen_open": True,
        "master_open": False,
        "anti_bot_popup": False,
    }

    # Register mock handlers
    ctx.register_recognition("find_shimen_tracker", lambda c, f, r: state["shimen_open"])
    ctx.register_action("click_shimen_tracker", lambda c, a: state.update({"shimen_open": False, "master_open": True}))

    ctx.register_recognition("is_master_dialog_open", lambda c, f, r: state["master_open"])
    ctx.register_action("click_accept_shimen", lambda c, a: state.update({"master_open": False}))

    ctx.register_recognition("detect_anti_bot_popup", lambda c, f, r: state["anti_bot_popup"])
    ctx.register_action("resolve_anti_bot_popup", lambda c, a: state.update({"anti_bot_popup": False}))

    pipeline.start()
    assert pipeline.status == PipelineStatus.RUNNING
    assert pipeline.current_node_name == "check_task_list"

    # Step 1: execute check_task_list
    pipeline.tick(ctx)
    assert "check_task_list" in ctx.history
    assert state["master_open"] is True

    # Inject Anti-Bot Popup!
    state["anti_bot_popup"] = True
    pipeline.tick(ctx)
    assert "INTERRUPT:intercept_anti_bot_popup" in ctx.history
    assert state["anti_bot_popup"] is False  # Resolved by interrupt action!


def test_self_healing_escape_escalation():
    actions = []

    manager = SelfHealingEscapeManager(
        stall_threshold_sec=0.01,
        max_level_1_attempts=2,
        on_minor_escape=lambda: actions.append("minor"),
        on_medium_escape=lambda: actions.append("medium"),
        on_major_escape=lambda: actions.append("major"),
    )

    import time
    time.sleep(0.02)

    # First attempt: Tier 1
    lvl1 = manager.check_and_heal()
    assert lvl1 == EscapeLevel.LEVEL_1_MINOR
    assert actions[-1] == "minor"

    # Second attempt: Tier 1
    time.sleep(0.02)
    lvl2 = manager.check_and_heal()
    assert lvl2 == EscapeLevel.LEVEL_1_MINOR
    assert actions[-1] == "minor"

    # Third attempt: Tier 2 (Tier 1 exhausted)
    time.sleep(0.02)
    lvl3 = manager.check_and_heal()
    assert lvl3 == EscapeLevel.LEVEL_2_MEDIUM
    assert actions[-1] == "medium"
