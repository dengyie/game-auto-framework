"""Unit and integration tests for TaskRoutineExecutor and Anti-Bot Circuit Breaker."""

import pytest
from core.device.virtual import VirtualDevice
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from scheduler.dag import PipelineStatus
from scheduler.routine import RoutineConfig, RoutineStatus, TaskRoutineExecutor


def test_routine_normalization_and_initial_state():
    dev = VirtualDevice()
    dev.connect()
    plugin = MHXYMobilePlugin(device=dev)

    config = RoutineConfig(
        name="test_routine",
        pipelines=["shimen", "daily_baotu", "yuntong"],
    )
    executor = TaskRoutineExecutor(plugin=plugin, config=config)

    assert executor._normalized_pipelines == ["daily_shimen", "daily_baotu", "daily_yuntong"]
    assert executor.status == RoutineStatus.IDLE
    assert executor.current_pipeline_name == "daily_shimen"

    progress = executor.get_progress()
    assert progress["total_pipelines"] == 3
    assert progress["progress_percent"] == 0.0


def test_routine_successful_chain_execution():
    dev = VirtualDevice()
    dev.connect()
    plugin = MHXYMobilePlugin(device=dev)

    # Pre-seed variables to allow fast completion of all 3 pipelines
    plugin.context.variables["shimen_rounds"] = 20
    plugin.context.variables["baotu_count"] = 10
    plugin.context.variables["dig_count"] = 10
    plugin.context.variables["yuntong_count"] = 3

    config = RoutineConfig(
        name="daily_all",
        pipelines=["shimen", "baotu", "yuntong"],
        retry_pipeline_times=0,
    )
    executor = TaskRoutineExecutor(plugin=plugin, config=config)
    executor.start()
    assert executor.status == RoutineStatus.RUNNING

    # Run loop until routine completes (max 50 ticks)
    for _ in range(50):
        status = executor.tick()
        if status in (RoutineStatus.COMPLETED, RoutineStatus.FAILED, RoutineStatus.CIRCUIT_BROKEN):
            break

    assert executor.status == RoutineStatus.COMPLETED
    assert len(executor.completed_pipelines) == 3
    assert executor.completed_pipelines == ["daily_shimen", "daily_baotu", "daily_yuntong"]
    assert executor.failed_pipelines == []

    progress = executor.get_progress()
    assert progress["progress_percent"] == 100.0
    assert progress["status"] == "completed"


def test_routine_anti_bot_circuit_breaker():
    dev = VirtualDevice()
    dev.connect()
    plugin = MHXYMobilePlugin(device=dev)

    config = RoutineConfig(
        name="circuit_breaker_test",
        pipelines=["shimen"],
        max_anti_bot_fails=2,
    )
    executor = TaskRoutineExecutor(plugin=plugin, config=config)
    executor.start()

    # Simulate 2 consecutive anti-bot failures
    plugin.context.variables["anti_bot_failed_count"] = 2

    status = executor.tick()
    assert status == RoutineStatus.CIRCUIT_BROKEN
    assert executor.status == RoutineStatus.CIRCUIT_BROKEN
    assert "circuit breaker" in executor.error_message.lower()


def test_routine_retry_and_failure_policy():
    dev = VirtualDevice()
    dev.connect()
    plugin = MHXYMobilePlugin(device=dev)

    # Configure nonexistent pipeline to force failure
    config = RoutineConfig(
        name="failure_test",
        pipelines=["non_existent_task"],
        stop_on_failure=True,
    )
    executor = TaskRoutineExecutor(plugin=plugin, config=config)
    executor.start()
    status = executor.tick()

    assert status == RoutineStatus.FAILED
    assert executor.status == RoutineStatus.FAILED
    assert "non_existent_task" in executor.failed_pipelines
