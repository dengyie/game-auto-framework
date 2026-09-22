"""
FastAPI Server for Remote Invocation on Linux VPS / Windows / macOS.
Provides REST endpoints to start/stop pipelines, monitor progress, and stream screenshots.
"""

from __future__ import annotations
import sys
import threading
import time
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from loguru import logger

from core.device.base import BaseDevice
from core.device.factory import DeviceFactory
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from scheduler.dag import PipelineStatus


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


class TaskState:
    def __init__(self) -> None:
        self.device: Optional[BaseDevice] = None
        self.plugin: Optional[Any] = None
        self.pipeline_name: Optional[str] = None
        self.running: bool = False
        self.status: PipelineStatus = PipelineStatus.IDLE
        self.thread: Optional[threading.Thread] = None
        self.stop_event: threading.Event = threading.Event()
        self.start_time: float = 0.0
        self.last_tick_time: float = 0.0
        self.error: Optional[str] = None


GLOBAL_TASK = TaskState()


def _background_pipeline_worker() -> None:
    logger.info(f"Background task worker started for [{GLOBAL_TASK.pipeline_name}]")
    try:
        while GLOBAL_TASK.running and not GLOBAL_TASK.stop_event.is_set():
            if GLOBAL_TASK.plugin and GLOBAL_TASK.pipeline_name:
                status = GLOBAL_TASK.plugin.run_pipeline_step(GLOBAL_TASK.pipeline_name)
                GLOBAL_TASK.status = status
                GLOBAL_TASK.last_tick_time = time.time()

                if status in (PipelineStatus.COMPLETED, PipelineStatus.FAILED, PipelineStatus.TIMEOUT):
                    logger.info(f"Pipeline finished with status: {status}")
                    GLOBAL_TASK.running = False
                    break
            GLOBAL_TASK.stop_event.wait(0.3)
    except Exception as e:
        logger.error(f"Pipeline worker encountered unexpected error: {e}")
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
    if GLOBAL_TASK.plugin and GLOBAL_TASK.pipeline_name:
        p = GLOBAL_TASK.plugin.get_pipeline(GLOBAL_TASK.pipeline_name)
        if p:
            current_node = p.current_node_name
        history = GLOBAL_TASK.plugin.context.history

    return {
        "engine": "game-auto-framework",
        "version": "0.1.0",
        "platform": sys.platform,
        "is_running": GLOBAL_TASK.running,
        "pipeline_status": GLOBAL_TASK.status.value,
        "active_plugin": GLOBAL_TASK.plugin.plugin_id if GLOBAL_TASK.plugin else None,
        "active_pipeline": GLOBAL_TASK.pipeline_name,
        "current_node": current_node,
        "uptime_sec": int(time.time() - GLOBAL_TASK.start_time) if GLOBAL_TASK.running else 0,
        "history_count": len(history),
        "device_connected": GLOBAL_TASK.device.is_connected() if GLOBAL_TASK.device else False,
        "device_type": GLOBAL_TASK.device.platform_type if GLOBAL_TASK.device else None,
        "error": GLOBAL_TASK.error,
    }


@app.post("/api/v1/tasks/start")
def start_task(req: StartTaskRequest) -> Dict[str, Any]:
    """Start an automation pipeline in background."""
    if GLOBAL_TASK.running:
        raise HTTPException(status_code=409, detail="A task is already running. Stop it before starting a new one.")

    logger.info(f"Received start request: plugin={req.plugin}, pipeline={req.pipeline}, device={req.device_type}")

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
    GLOBAL_TASK.running = True
    GLOBAL_TASK.status = PipelineStatus.RUNNING
    GLOBAL_TASK.start_time = time.time()
    GLOBAL_TASK.error = None
    GLOBAL_TASK.stop_event.clear()

    # 3. Launch daemon thread worker
    worker_thread = threading.Thread(target=_background_pipeline_worker, daemon=True)
    GLOBAL_TASK.thread = worker_thread
    worker_thread.start()

    return {
        "status": "started",
        "plugin": req.plugin,
        "pipeline": req.pipeline,
        "device_type": device.platform_type,
    }


@app.post("/api/v1/tasks/stop")
def stop_task() -> Dict[str, Any]:
    """Stop the currently active task."""
    if not GLOBAL_TASK.running and not GLOBAL_TASK.thread:
        return {"status": "already_stopped"}

    GLOBAL_TASK.stop_event.set()
    GLOBAL_TASK.running = False
    if GLOBAL_TASK.thread:
        GLOBAL_TASK.thread.join(timeout=1.0)
        GLOBAL_TASK.thread = None

    GLOBAL_TASK.status = PipelineStatus.IDLE
    logger.info("Active task stopped via API call")
    return {"status": "stopped"}


@app.get("/api/v1/screenshot")
def get_screenshot() -> Response:
    """Fetch live screenshot frame from active device."""
    if not GLOBAL_TASK.device:
        # Fallback placeholder device
        dev = DeviceFactory.create("virtual")
        dev.connect()
        data = dev.screencap()
        return Response(content=data, media_type="image/jpeg")

    try:
        frame_bytes = GLOBAL_TASK.device.screencap()
        return Response(content=frame_bytes, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to capture frame: {e}")
