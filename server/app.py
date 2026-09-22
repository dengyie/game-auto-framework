"""
FastAPI Server for Remote Invocation on Linux VPS / Windows / macOS.
Provides REST endpoints to start/stop pipelines, monitor progress, chain routines, and stream screenshots.
"""

from __future__ import annotations
import sys
import threading
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from loguru import logger

from core.device.base import BaseDevice
from core.device.factory import DeviceFactory
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from scheduler.dag import PipelineStatus
from scheduler.routine import RoutineConfig, RoutineStatus, TaskRoutineExecutor


app = FastAPI(
    title="game-auto-framework VPS API",
    version="0.1.0",
    description="Cross-platform game automation engine and remote invocation middleware",
)


class StartTaskRequest(BaseModel):
    plugin: str = Field(default="mhxy_mobile", description="Target plugin ID")
    pipeline: str = Field(default="daily_shimen", description="Pipeline name")
    device_type: str = Field(default="auto", description="'auto', 'adb', 'virtual', etc.")
    device_serial: Optional[str] = Field(default=None, description="ADB target host:port")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Initial state variables")


class StartRoutineRequest(BaseModel):
    plugin: str = Field(default="mhxy_mobile", description="Target plugin ID")
    routine_name: str = Field(default="daily_routine", description="Routine name")
    pipelines: List[str] = Field(
        default_factory=lambda: ["shimen", "baotu", "yuntong"],
        description="Ordered list of pipelines to execute sequentially",
    )
    device_type: str = Field(default="auto", description="'auto', 'adb', 'virtual', etc.")
    device_serial: Optional[str] = Field(default=None, description="ADB target host:port")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Initial state variables")
    stop_on_failure: bool = Field(default=True, description="Stop routine on first pipeline failure")
    max_anti_bot_fails: int = Field(default=2, description="Circuit breaker threshold for anti-bot popups")
    retry_pipeline_times: int = Field(default=1, description="Number of retries per pipeline")


class TaskState:
    def __init__(self) -> None:
        self.device: Optional[BaseDevice] = None
        self.plugin: Optional[Any] = None
        self.pipeline_name: Optional[str] = None
        self.routine_executor: Optional[TaskRoutineExecutor] = None
        self.is_routine: bool = False
        self.running: bool = False
        self.status: PipelineStatus = PipelineStatus.IDLE
        self.thread: Optional[threading.Thread] = None
        self.stop_event: threading.Event = threading.Event()
        self.start_time: float = 0.0
        self.last_tick_time: float = 0.0
        self.error: Optional[str] = None


GLOBAL_TASK = TaskState()


def _background_worker() -> None:
    logger.info(
        f"Background worker started (is_routine={GLOBAL_TASK.is_routine}, target={GLOBAL_TASK.pipeline_name or (GLOBAL_TASK.routine_executor.config.name if GLOBAL_TASK.routine_executor else 'None')})"
    )
    try:
        while GLOBAL_TASK.running and not GLOBAL_TASK.stop_event.is_set():
            if GLOBAL_TASK.is_routine and GLOBAL_TASK.routine_executor:
                routine_status = GLOBAL_TASK.routine_executor.tick()
                GLOBAL_TASK.last_tick_time = time.time()

                if routine_status in (
                    RoutineStatus.COMPLETED,
                    RoutineStatus.FAILED,
                    RoutineStatus.CIRCUIT_BROKEN,
                    RoutineStatus.STOPPED,
                ):
                    logger.info(f"Task routine finished with status: {routine_status.value}")
                    GLOBAL_TASK.running = False
                    if routine_status == RoutineStatus.COMPLETED:
                        GLOBAL_TASK.status = PipelineStatus.COMPLETED
                    else:
                        GLOBAL_TASK.status = PipelineStatus.FAILED
                        GLOBAL_TASK.error = GLOBAL_TASK.routine_executor.error_message
                    break
            elif GLOBAL_TASK.plugin and GLOBAL_TASK.pipeline_name:
                status = GLOBAL_TASK.plugin.run_pipeline_step(GLOBAL_TASK.pipeline_name)
                GLOBAL_TASK.status = status
                GLOBAL_TASK.last_tick_time = time.time()

                if status in (PipelineStatus.COMPLETED, PipelineStatus.FAILED, PipelineStatus.TIMEOUT):
                    logger.info(f"Single pipeline finished with status: {status.value}")
                    GLOBAL_TASK.running = False
                    break

            GLOBAL_TASK.stop_event.wait(0.2)
    except Exception as e:
        logger.error(f"Background worker encountered unexpected error: {e}")
        GLOBAL_TASK.status = PipelineStatus.FAILED
        GLOBAL_TASK.error = str(e)
    finally:
        GLOBAL_TASK.running = False


@app.get("/health")
@app.get("/api/v1/status")
def get_status() -> Dict[str, Any]:
    """Check VPS engine health, operating system, and task state."""
    current_node = None
    history = []
    if GLOBAL_TASK.plugin:
        history = GLOBAL_TASK.plugin.context.history

    active_pipeline = GLOBAL_TASK.pipeline_name
    if GLOBAL_TASK.is_routine and GLOBAL_TASK.routine_executor:
        active_pipeline = GLOBAL_TASK.routine_executor.current_pipeline_name
        if active_pipeline and GLOBAL_TASK.plugin:
            p = GLOBAL_TASK.plugin.get_pipeline(active_pipeline)
            if p:
                current_node = p.current_node_name
    elif GLOBAL_TASK.plugin and GLOBAL_TASK.pipeline_name:
        p = GLOBAL_TASK.plugin.get_pipeline(GLOBAL_TASK.pipeline_name)
        if p:
            current_node = p.current_node_name

    routine_progress = GLOBAL_TASK.routine_executor.get_progress() if GLOBAL_TASK.routine_executor else None

    return {
        "engine": "game-auto-framework",
        "version": "0.1.0",
        "platform": sys.platform,
        "is_running": GLOBAL_TASK.running,
        "is_routine": GLOBAL_TASK.is_routine,
        "pipeline_status": GLOBAL_TASK.status.value,
        "active_plugin": GLOBAL_TASK.plugin.plugin_id if GLOBAL_TASK.plugin else None,
        "active_pipeline": active_pipeline,
        "current_node": current_node,
        "uptime_sec": int(time.time() - GLOBAL_TASK.start_time) if GLOBAL_TASK.running else 0,
        "history_count": len(history),
        "device_connected": GLOBAL_TASK.device.is_connected() if GLOBAL_TASK.device else False,
        "device_type": GLOBAL_TASK.device.platform_type if GLOBAL_TASK.device else None,
        "routine_progress": routine_progress,
        "error": GLOBAL_TASK.error,
    }


@app.post("/api/v1/tasks/start")
def start_task(req: StartTaskRequest) -> Dict[str, Any]:
    """Start a single automation pipeline in background."""
    if GLOBAL_TASK.running:
        raise HTTPException(status_code=409, detail="A task or routine is already running. Stop it before starting a new one.")

    logger.info(f"Received start task request: plugin={req.plugin}, pipeline={req.pipeline}, device={req.device_type}")

    # 1. Initialize Device
    try:
        device = DeviceFactory.create(device_type=req.device_type, serial=req.device_serial)
        device.connect()
        GLOBAL_TASK.device = device
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize device: {e}")

    # 2. Initialize Plugin
    if req.plugin == "mhxy_mobile":
        plugin = MHXYMobilePlugin(device=device)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported plugin: {req.plugin}")

    # Seed variables into plugin context
    for k, v in req.variables.items():
        plugin.context.variables[k] = v

    GLOBAL_TASK.plugin = plugin
    GLOBAL_TASK.pipeline_name = req.pipeline
    GLOBAL_TASK.routine_executor = None
    GLOBAL_TASK.is_routine = False
    GLOBAL_TASK.running = True
    GLOBAL_TASK.status = PipelineStatus.RUNNING
    GLOBAL_TASK.start_time = time.time()
    GLOBAL_TASK.error = None
    GLOBAL_TASK.stop_event.clear()

    # 3. Launch daemon thread worker
    worker_thread = threading.Thread(target=_background_worker, daemon=True)
    GLOBAL_TASK.thread = worker_thread
    worker_thread.start()

    return {
        "status": "started",
        "plugin": req.plugin,
        "pipeline": req.pipeline,
        "device_type": device.platform_type,
    }


@app.post("/api/v1/tasks/start-routine")
def start_routine(req: StartRoutineRequest) -> Dict[str, Any]:
    """Start an ordered routine chain of pipelines in background."""
    if GLOBAL_TASK.running:
        raise HTTPException(status_code=409, detail="A task or routine is already running. Stop it before starting a new one.")

    logger.info(
        f"Received start routine request: plugin={req.plugin}, routine={req.routine_name}, "
        f"pipelines={req.pipelines}, device={req.device_type}"
    )

    # 1. Initialize Device
    try:
        device = DeviceFactory.create(device_type=req.device_type, serial=req.device_serial)
        device.connect()
        GLOBAL_TASK.device = device
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize device: {e}")

    # 2. Initialize Plugin
    if req.plugin == "mhxy_mobile":
        plugin = MHXYMobilePlugin(device=device)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported plugin: {req.plugin}")

    # Seed variables into plugin context
    for k, v in req.variables.items():
        plugin.context.variables[k] = v

    # 3. Initialize Routine Executor
    config = RoutineConfig(
        name=req.routine_name,
        pipelines=req.pipelines,
        stop_on_failure=req.stop_on_failure,
        max_anti_bot_fails=req.max_anti_bot_fails,
        retry_pipeline_times=req.retry_pipeline_times,
    )
    executor = TaskRoutineExecutor(plugin=plugin, config=config)
    executor.start()

    GLOBAL_TASK.plugin = plugin
    GLOBAL_TASK.pipeline_name = None
    GLOBAL_TASK.routine_executor = executor
    GLOBAL_TASK.is_routine = True
    GLOBAL_TASK.running = True
    GLOBAL_TASK.status = PipelineStatus.RUNNING
    GLOBAL_TASK.start_time = time.time()
    GLOBAL_TASK.error = None
    GLOBAL_TASK.stop_event.clear()

    # 4. Launch daemon thread worker
    worker_thread = threading.Thread(target=_background_worker, daemon=True)
    GLOBAL_TASK.thread = worker_thread
    worker_thread.start()

    return {
        "status": "started",
        "routine": req.routine_name,
        "pipelines": executor._normalized_pipelines,
        "plugin": req.plugin,
        "device_type": device.platform_type,
    }


@app.get("/api/v1/tasks/routine-status")
def get_routine_status() -> Dict[str, Any]:
    """Fetch current progress and stats of the active or latest routine."""
    if not GLOBAL_TASK.routine_executor:
        return {"status": "no_active_routine"}
    return GLOBAL_TASK.routine_executor.get_progress()


@app.post("/api/v1/tasks/stop")
def stop_task() -> Dict[str, Any]:
    """Stop the currently active task or routine."""
    if not GLOBAL_TASK.running and not GLOBAL_TASK.thread:
        return {"status": "already_stopped"}

    GLOBAL_TASK.stop_event.set()
    GLOBAL_TASK.running = False
    if GLOBAL_TASK.routine_executor:
        GLOBAL_TASK.routine_executor.stop()

    if GLOBAL_TASK.thread:
        GLOBAL_TASK.thread.join(timeout=1.0)
        GLOBAL_TASK.thread = None

    GLOBAL_TASK.status = PipelineStatus.IDLE
    logger.info("Active task/routine stopped via API call")
    return {"status": "stopped"}


@app.get("/api/v1/screenshot")
def get_screenshot() -> Response:
    """Fetch live screenshot frame from active device."""
    if not GLOBAL_TASK.device:
        dev = DeviceFactory.create("virtual")
        dev.connect()
        data = dev.screencap()
        return Response(content=data, media_type="image/jpeg")

    try:
        frame_bytes = GLOBAL_TASK.device.screencap()
        return Response(content=frame_bytes, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to capture frame: {e}")
