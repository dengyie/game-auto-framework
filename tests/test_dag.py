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
    assert len(pipeline.nodes) == 9
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


def test_dag_conditional_branches_and_context_flow():
    pipeline_data = {
        "name": "test_branching",
        "entry": "check_count",
        "nodes": [
            {
                "name": "check_count",
                "recognition": {"type": "always"},
                "action": {"type": "set_var", "var_key": "completed_rounds", "var_value": 20},
                "branches": [
                    {"condition": "completed_rounds >= 20", "next": "finish_task"},
                    {"condition": "completed_rounds < 20", "next": "continue_task"},
                ],
            },
            {
                "name": "continue_task",
                "recognition": {"type": "always"},
                "is_terminal": True,
            },
            {
                "name": "finish_task",
                "recognition": {"type": "always"},
                "is_terminal": True,
            },
        ],
    }

    pipeline = DAGPipeline.from_dict(pipeline_data)
    ctx = PipelineContext()
    ctx.variables["completed_rounds"] = 0

    pipeline.start()
    status = pipeline.tick(ctx)

    # After step 1, completed_rounds set to 20, branch routed to finish_task
    assert pipeline.current_node_name == "finish_task"
    assert ctx.variables["completed_rounds"] == 20

    # Step 2: execute finish_task (terminal)
    status2 = pipeline.tick(ctx)
    assert status2 == PipelineStatus.COMPLETED
    assert "finish_task" in ctx.history


def test_dag_watchdog_integration():
    import time
    actions = []
    manager = SelfHealingEscapeManager(
        stall_threshold_sec=0.01,
        max_level_1_attempts=1,
        on_minor_escape=lambda: actions.append("healed_by_watchdog"),
    )

    pipeline_data = {
        "name": "stalled_pipeline",
        "entry": "stalled_node",
        "nodes": [
            {
                "name": "stalled_node",
                "recognition": {"type": "custom", "custom_func": "never_match"},
                "timeout_sec": 10.0,
            }
        ],
    }

    pipeline = DAGPipeline.from_dict(pipeline_data)
    ctx = PipelineContext(escape_manager=manager)
    ctx.register_recognition("never_match", lambda c, f, r: False)

    pipeline.start()
    time.sleep(0.02)

    # Tick should trigger watchdog escape
    pipeline.tick(ctx)
    assert "ESCAPE:LEVEL_1_MINOR" in ctx.history
    assert "healed_by_watchdog" in actions


def test_dag_skip_on_stale_skips_custom_recognition_after_interactive_action():
    """Review P1: a custom recognizer flagged ``skip_on_stale`` must not run on the
    frame captured *before* the just-executed click (that frame cannot prove the
    next screen). The tap tick falls through to the default next node instead, and
    the recognizer is evaluated on the following (fresh) tick."""
    calls = {"probe": 0}

    pipeline_data = {
        "name": "stale_probe",
        "entry": "tap",
        "nodes": [
            {
                "name": "tap",
                "recognition": {"type": "always"},
                "action": {"type": "click", "target_pos": [10, 10]},
                "next": ["probe"],
                "timeout_sec": 60.0,
            },
            {
                "name": "probe",
                "recognition": {"type": "custom", "custom_func": "counting", "skip_on_stale": True},
                "action": {"type": "none"},
                "timeout_sec": 60.0,
            },
        ],
    }

    pipeline = DAGPipeline.from_dict(pipeline_data)
    ctx = PipelineContext()

    def counting(c, frame, rec):
        calls["probe"] += 1
        return True

    ctx.register_recognition("counting", counting)

    pipeline.start()

    # Tick 1: `tap` clicks; `probe` must NOT be evaluated against this stale frame.
    pipeline.tick(ctx)
    assert pipeline.current_node_name == "probe"
    assert calls["probe"] == 0

    # Tick 2: `probe` is now current and sees a fresh frame -> recognition fires.
    pipeline.tick(ctx)
    assert calls["probe"] == 1


def test_dag_custom_recognition_without_flag_still_evaluated_on_stale_frame():
    """Backward compatibility: recognizers without ``skip_on_stale`` keep the old
    behavior (evaluated with the same tick's frame), so the flag is strictly opt-in."""
    calls = {"probe": 0}

    pipeline_data = {
        "name": "stale_probe_unflagged",
        "entry": "tap",
        "nodes": [
            {
                "name": "tap",
                "recognition": {"type": "always"},
                "action": {"type": "click", "target_pos": [10, 10]},
                "next": ["probe"],
                "timeout_sec": 60.0,
            },
            {
                "name": "probe",
                "recognition": {"type": "custom", "custom_func": "counting"},
                "action": {"type": "none"},
                "timeout_sec": 60.0,
            },
        ],
    }

    pipeline = DAGPipeline.from_dict(pipeline_data)
    ctx = PipelineContext()

    def counting(c, frame, rec):
        calls["probe"] += 1
        return True

    ctx.register_recognition("counting", counting)

    pipeline.start()
    pipeline.tick(ctx)
    assert calls["probe"] == 1  # evaluated on the same (stale) tick

