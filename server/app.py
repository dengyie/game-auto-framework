"""
FastAPI Server for Remote Invocation on Linux VPS / Windows / macOS.
Provides REST endpoints to start/stop pipelines, monitor progress, chain routines, and stream screenshots.
"""

from __future__ import annotations
import csv
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from loguru import logger

from core.device.base import BaseDevice
from core.device.factory import DeviceFactory
from plugins.registry import GamePluginRegistry
from scheduler.dag import PipelineStatus
from scheduler.routine import RoutineConfig, RoutineStatus, TaskRoutineExecutor
from cluster.instance_pool import InstancePool, InstanceStatus, TeamRole
from cluster.proxy import ProxyManager, ProxyStatus
from cluster.account import AccountConfig, AccountMatrix, AccountStatus
from cluster.supervisor import ClusterSupervisor


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


STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


@app.get("/", response_class=HTMLResponse)
@app.head("/")
@app.get("/dashboard", response_class=HTMLResponse)
@app.head("/dashboard")
@app.get("/instances", response_class=HTMLResponse)
@app.head("/instances")
@app.get("/stream", response_class=HTMLResponse)
@app.head("/stream")
@app.get("/teams", response_class=HTMLResponse)
@app.head("/teams")
@app.get("/proxies", response_class=HTMLResponse)
@app.head("/proxies")
@app.get("/accounts", response_class=HTMLResponse)
@app.head("/accounts")
@app.get("/soak", response_class=HTMLResponse)
@app.head("/soak")
@app.get("/agent", response_class=HTMLResponse)
@app.head("/agent")
def serve_dashboard() -> HTMLResponse:
    """Serve the embedded modern dark-mode Web Dashboard and tab sub-URLs."""
    if INDEX_HTML.exists():
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(
        content="""<!DOCTYPE html>
<html>
<head><title>game-auto-framework</title></head>
<body style="background:#0f172a;color:#f8fafc;font-family:sans-serif;padding:40px;">
  <h2>🎮 game-auto-framework VPS Control Plane</h2>
  <p>Loading Dashboard UI... (Static bundle initializing)</p>
  <p><a href="/docs" style="color:#38bdf8;">API Documentation (Swagger UI)</a></p>
</body>
</html>""",
        status_code=200,
    )


@app.get("/api/v1/plugins")
def list_plugins() -> Dict[str, Any]:
    """Enumerate all discovered game plugins and metadata."""
    plugins = GamePluginRegistry.list_plugins()
    return {"plugins": plugins, "total": len(plugins)}


@app.get("/api/v1/plugins/{plugin_id}/pipelines")
def get_plugin_pipelines(plugin_id: str) -> Dict[str, Any]:
    """Get all pipeline DAG definitions for a specific game plugin."""
    pipelines = GamePluginRegistry.get_pipelines(plugin_id)
    if not pipelines:
        raise HTTPException(status_code=404, detail=f"Plugin [{plugin_id}] not found or has no pipelines.")
    return {"plugin_id": plugin_id, "pipelines": pipelines, "total": len(pipelines)}


@app.get("/health")
@app.head("/health")
@app.get("/api/v1/status")
@app.head("/api/v1/status")
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
    try:
        plugin = GamePluginRegistry.create(req.plugin, device=device)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Unsupported or failed to load plugin: {req.plugin} ({e})")

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
    try:
        plugin = GamePluginRegistry.create(req.plugin, device=device)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Unsupported or failed to load plugin: {req.plugin} ({e})")

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
@app.head("/api/v1/screenshot")
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


def _generate_mjpeg_frames(instance_id: Optional[str] = None, fps: float = 10.0):
    interval = max(0.033, 1.0 / max(1.0, min(fps, 30.0)))
    while True:
        frame_bytes = None
        try:
            if instance_id:
                inst = CLUSTER_POOL.get_instance(instance_id)
                if inst:
                    frame_bytes = inst.screencap()
            if not frame_bytes:
                if GLOBAL_TASK.device:
                    frame_bytes = GLOBAL_TASK.device.screencap()
                else:
                    instances = CLUSTER_POOL.list_instances()
                    if instances:
                        frame_bytes = instances[0].screencap()
                    else:
                        dev = DeviceFactory.create("virtual")
                        dev.connect()
                        frame_bytes = dev.screencap()
        except Exception as e:
            logger.debug(f"Frame capture error in stream: {e}")
            time.sleep(interval)
            continue

        if frame_bytes:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
        time.sleep(interval)


@app.get("/api/v1/stream")
@app.head("/api/v1/stream")
def stream_video(instance_id: Optional[str] = None, fps: float = 10.0) -> StreamingResponse:
    """Stream live MJPEG video frames from active task or a specific cluster instance."""
    return StreamingResponse(
        _generate_mjpeg_frames(instance_id=instance_id, fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# =====================================================================
# Milestone 3: Cluster, Multi-Instance, Proxy & Account REST Endpoints
# =====================================================================

CLUSTER_POOL = InstancePool.get_pool()
PROXY_MANAGER = ProxyManager.get_instance()
ACCOUNT_MATRIX = AccountMatrix.get_instance()
SUPERVISOR = ClusterSupervisor.get_instance()


def init_default_cluster(config_path: Optional[str] = None) -> None:
    """Initialize default cluster state, accounts, proxies, instances and supervisor."""
    # 1. Load accounts from config/accounts.json
    candidates = [
        config_path,
        "config/accounts.json",
        str(Path(__file__).parent.parent / "config" / "accounts.json"),
        os.path.join(os.getcwd(), "config", "accounts.json"),
    ]
    target_path = None
    for p in candidates:
        if p and Path(p).exists():
            target_path = p
            break

    if target_path and len(ACCOUNT_MATRIX.list_accounts()) == 0:
        loaded = ACCOUNT_MATRIX.load_from_json(target_path)
        logger.info(f"Auto-loaded {loaded} accounts from {target_path} into ACCOUNT_MATRIX")

    # 2. Register Proxies if pool is empty
    if PROXY_MANAGER.get_pool_status()["total_proxies"] == 0:
        proxies = [
            ("proxy_sh_01", "socks5", "127.0.0.1", 10801, "上海家宽-01 (home-win)", "中国·上海 (移动住宅家宽-通道1)"),
            ("proxy_sh_02", "socks5", "127.0.0.1", 10802, "上海家宽-02 (home-win)", "中国·上海 (移动住宅家宽-通道2)"),
            ("proxy_sh_03", "socks5", "127.0.0.1", 10803, "上海家宽-03 (home-win)", "中国·上海 (移动住宅家宽-通道3)"),
            ("proxy_sh_04", "socks5", "127.0.0.1", 10804, "上海家宽-04 (home-win)", "中国·上海 (移动住宅家宽-通道4)"),
            ("proxy_sh_05", "socks5", "127.0.0.1", 10805, "上海家宽-05 (home-win)", "中国·上海 (移动住宅家宽-通道5)"),
        ]
        for p_id, proto, host, port, lbl, loc in proxies:
            PROXY_MANAGER.register_proxy(
                p_id, host=host, port=port, protocol=proto, max_instances=1, label=lbl, location=loc
            )
        logger.info(f"Registered {len(proxies)} Shanghai residential proxies in PROXY_MANAGER")

    # 3. Register Instances & Bind Accounts
    accounts = ACCOUNT_MATRIX.list_accounts()
    if len(CLUSTER_POOL.get_instances()) == 0 and accounts:
        for i, acc in enumerate(accounts, start=1):
            inst_id = f"inst_{i:02d}"
            inst = CLUSTER_POOL.register_instance(
                instance_id=inst_id,
                device_type="virtual",
                serial=None,
                name=f"{acc.role_name or f'Inst_{i}'}",
            )
            inst.connect()
            inst.assigned_account_id = acc.account_id
            inst.pipeline_name = "daily_shimen" if i == 1 else "basic_tasks"
            inst.pipeline_status = PipelineStatus.IDLE
            inst.status = InstanceStatus.IDLE
            inst.heartbeat()

            # Bind proxy: prefer account's preset proxy or claim next available residential proxy
            target_proxy = None
            if acc.bound_proxy_id:
                p = PROXY_MANAGER.get_proxy(acc.bound_proxy_id)
                if p and p.is_available:
                    target_proxy = p
            if not target_proxy:
                target_proxy = PROXY_MANAGER.get_available_proxy()

            if target_proxy:
                PROXY_MANAGER.bind_instance_to_proxy(inst_id, target_proxy.proxy_id)
                inst.assigned_proxy_id = target_proxy.proxy_id
                acc.start_session(inst_id, target_proxy.proxy_id)
            else:
                acc.start_session(inst_id)

        # 4. Form 1 Leader + Members Team Topology
        inst_ids = [inst.instance_id for inst in CLUSTER_POOL.get_instances()]
        if len(inst_ids) >= 2 and len(CLUSTER_POOL.list_teams()) == 0:
            CLUSTER_POOL.create_team(
                team_id="team_01",
                leader_id=inst_ids[0],
                member_ids=inst_ids[1:],
                target_activity="team_zhuogui",
            )
        logger.info(f"Formed cluster team_01 with {len(inst_ids)} instances")

    # 5. Start Supervisor watchdog
    if not SUPERVISOR.running:
        SUPERVISOR.start()
        logger.info("Started ClusterSupervisor watchdog")


@app.on_event("startup")
def on_startup() -> None:
    init_default_cluster()


# Trigger initial state creation
init_default_cluster()


class RegisterInstanceRequest(BaseModel):
    instance_id: str = Field(description="Unique instance ID (e.g. inst_01, emulator-5554)")
    device_type: str = Field(default="auto", description="'auto', 'adb', 'virtual'")
    serial: Optional[str] = Field(default=None, description="ADB serial host:port")
    name: Optional[str] = Field(default=None, description="Instance display label")


class StartInstanceTaskRequest(BaseModel):
    plugin: str = Field(default="mhxy_mobile", description="Target plugin ID (e.g. 'mhxy_mobile', 'yys_mobile')")
    pipeline: Optional[str] = Field(default=None, description="Single pipeline name (e.g. 'daily_shimen')")
    routine_name: Optional[str] = Field(default=None, description="Routine name if executing routine")
    pipelines: Optional[List[str]] = Field(default=None, description="Ordered list of pipelines for routine")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Initial context variables")


class CreateTeamRequest(BaseModel):
    team_id: str = Field(description="Unique team identifier (e.g. team_01)")
    leader_id: str = Field(description="Instance ID of the team leader")
    member_ids: List[str] = Field(description="List of instance IDs for members (max 4)")
    target_activity: str = Field(default="team_zhuogui", description="Team activity target")


class StartTeamRoutineRequest(BaseModel):
    team_id: str = Field(description="Target team identifier")
    leader_pipelines: List[str] = Field(default_factory=lambda: ["zhuogui"], description="Pipelines for leader")
    member_pipelines: List[str] = Field(default_factory=lambda: ["zhuogui"], description="Pipelines for members")
    leader_vars: Dict[str, Any] = Field(default_factory=dict, description="Variables for leader")
    member_vars: Dict[str, Any] = Field(default_factory=dict, description="Variables for members")


class RegisterProxyRequest(BaseModel):
    proxy_id: str = Field(description="Unique proxy identifier")
    host: str = Field(description="Proxy IP or hostname")
    port: int = Field(description="Proxy port")
    protocol: str = Field(default="socks5", description="Protocol: 'socks5', 'http', 'https'")
    username: Optional[str] = Field(default=None, description="Optional auth user")
    password: Optional[str] = Field(default=None, description="Optional auth password")
    max_instances: int = Field(default=5, description="Max instances per proxy (<=5)")
    label: Optional[str] = Field(default=None, description="Descriptive label e.g. 上海家宽")
    location: Optional[str] = Field(default=None, description="Location e.g. 中国·上海")


class BindProxyRequest(BaseModel):
    instance_id: str
    proxy_id: str


class UnbindProxyRequest(BaseModel):
    instance_id: str


class RegisterAccountRequest(BaseModel):
    account_id: str = Field(description="Unique account ID")
    username: str = Field(description="Login username")
    password: str = Field(description="Login password")
    server_name: str = Field(default="东海湾", description="Game server name")
    role_name: Optional[str] = Field(default=None, description="In-game character name")
    level: int = Field(default=69, description="Character level")
    sect: str = Field(default="大唐官府", description="Character sect")
    team_role_preference: str = Field(default="solo", description="leader / member / solo")


@app.get("/api/v1/cluster/status")
def get_cluster_status() -> Dict[str, Any]:
    """Retrieve full cluster status: instances, teams, proxies, accounts, and supervisor."""
    return {
        "cluster": CLUSTER_POOL.get_cluster_stats(),
        "proxy": PROXY_MANAGER.get_proxy_stats(),
        "assets": ACCOUNT_MATRIX.get_total_assets(),
        "supervisor": SUPERVISOR.get_status(),
    }


@app.post("/api/v1/cluster/instances/register")
def register_instance(req: RegisterInstanceRequest) -> Dict[str, Any]:
    """Register a new device instance into the cluster pool."""
    inst = CLUSTER_POOL.register_instance(
        instance_id=req.instance_id,
        device_type=req.device_type,
        serial=req.serial,
        name=req.name,
    )
    return {"status": "registered", "instance": inst.get_health()}


@app.get("/api/v1/cluster/instances")
def list_cluster_instances() -> List[Dict[str, Any]]:
    """List all registered instances with their health metrics."""
    return [inst.get_health() for inst in CLUSTER_POOL.list_instances()]


@app.get("/api/v1/cluster/instances/{instance_id}")
def get_cluster_instance(instance_id: str) -> Dict[str, Any]:
    """Get diagnostic health of a specific instance."""
    inst = CLUSTER_POOL.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance [{instance_id}] not found.")
    return inst.get_health()


@app.post("/api/v1/cluster/instances/{instance_id}/start")
def start_instance_task(instance_id: str, req: StartInstanceTaskRequest) -> Dict[str, Any]:
    """Start a pipeline or routine on a specific cluster instance."""
    inst = CLUSTER_POOL.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance [{instance_id}] not found.")

    if req.pipelines:
        routine_name = req.routine_name or f"{instance_id}_routine"
        success = inst.start_routine(
            routine_name=routine_name,
            pipelines=req.pipelines,
            variables=req.variables,
            plugin_id=req.plugin,
        )
    elif req.pipeline:
        success = inst.start_pipeline(
            pipeline_name=req.pipeline,
            variables=req.variables,
            plugin_id=req.plugin,
        )
    else:
        raise HTTPException(status_code=400, detail="Must provide either 'pipeline' or 'pipelines'.")

    if not success:
        raise HTTPException(status_code=409, detail=f"Failed to start task on [{instance_id}] (instance busy or connect failed).")

    return {"status": "started", "instance_id": instance_id, "plugin": req.plugin}


@app.post("/api/v1/cluster/instances/{instance_id}/stop")
def stop_instance_task(instance_id: str) -> Dict[str, Any]:
    """Stop active task on a specific cluster instance."""
    inst = CLUSTER_POOL.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance [{instance_id}] not found.")
    inst.stop()
    return {"status": "stopped", "instance_id": instance_id}


@app.delete("/api/v1/cluster/instances/{instance_id}")
def unregister_instance(instance_id: str) -> Dict[str, Any]:
    """Unregister and disconnect a device instance."""
    success = CLUSTER_POOL.unregister_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Instance [{instance_id}] not found.")
    return {"status": "unregistered", "instance_id": instance_id}


@app.get("/api/v1/cluster/instances/{instance_id}/screenshot")
@app.head("/api/v1/cluster/instances/{instance_id}/screenshot")
def get_instance_screenshot(instance_id: str) -> Response:
    """Capture screenshot frame from a specific cluster instance."""
    inst = CLUSTER_POOL.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance [{instance_id}] not found.")
    try:
        data = inst.screencap()
        return Response(content=data, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screenshot failed on [{instance_id}]: {e}")


@app.get("/api/v1/cluster/instances/{instance_id}/stream")
@app.head("/api/v1/cluster/instances/{instance_id}/stream")
def stream_instance_video(instance_id: str, fps: float = 10.0) -> StreamingResponse:
    """Stream live MJPEG video frames from a specific cluster instance."""
    inst = CLUSTER_POOL.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance [{instance_id}] not found.")
    return StreamingResponse(
        _generate_mjpeg_frames(instance_id=instance_id, fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


class DeviceActionRequest(BaseModel):
    action: str = Field(default="tap", description="'tap', 'swipe', 'key', 'text'")
    x: Optional[int] = Field(default=None, description="X coordinate")
    y: Optional[int] = Field(default=None, description="Y coordinate")
    x2: Optional[int] = Field(default=None, description="Target X coordinate for swipe")
    y2: Optional[int] = Field(default=None, description="Target Y coordinate for swipe")
    duration_ms: Optional[int] = Field(default=300, description="Swipe duration in ms")
    keycode: Optional[int] = Field(default=None, description="Keycode")
    text: Optional[str] = Field(default=None, description="Text to input")


@app.post("/api/v1/cluster/instances/{instance_id}/action")
def send_instance_action(instance_id: str, req: DeviceActionRequest) -> Dict[str, Any]:
    """Dispatch virtual touch or key action to a cluster instance device."""
    inst = CLUSTER_POOL.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance [{instance_id}] not found.")

    if not inst.device:
        if not inst.connect():
            raise HTTPException(status_code=500, detail=f"Failed to connect device on [{instance_id}].")

    device = inst.device
    if req.action == "tap":
        if req.x is None or req.y is None:
            raise HTTPException(status_code=400, detail="Action 'tap' requires 'x' and 'y'.")
        res = device.click(float(req.x), float(req.y))
        return {"status": "ok", "action": "tap", "instance_id": instance_id, "coords": res}
    elif req.action == "swipe":
        if None in (req.x, req.y, req.x2, req.y2):
            raise HTTPException(status_code=400, detail="Action 'swipe' requires 'x', 'y', 'x2', 'y2'.")
        device.swipe(float(req.x), float(req.y), float(req.x2), float(req.y2))
        return {"status": "ok", "action": "swipe", "instance_id": instance_id}
    elif req.action == "key":
        keycode = req.keycode or 4
        if hasattr(device, "key_event"):
            device.key_event(keycode)
        return {"status": "ok", "action": "key", "keycode": keycode, "instance_id": instance_id}
    elif req.action == "text":
        if req.text is None:
            raise HTTPException(status_code=400, detail="Action 'text' requires 'text'.")
        if hasattr(device, "input_text"):
            device.input_text(req.text)
        return {"status": "ok", "action": "text", "instance_id": instance_id}
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {req.action}")


@app.post("/api/v1/cluster/team/create")
def create_cluster_team(req: CreateTeamRequest) -> Dict[str, Any]:
    """Assemble a 5-member team topology (1 Leader + up to 4 Members)."""
    try:
        team = CLUSTER_POOL.create_team(
            team_id=req.team_id,
            leader_id=req.leader_id,
            member_ids=req.member_ids,
            target_activity=req.target_activity,
        )
        return {"status": "created", "team": team.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/cluster/teams")
def list_cluster_teams() -> Dict[str, Any]:
    """List all assembled team topologies."""
    teams = [t.to_dict() for t in CLUSTER_POOL.list_teams()]
    return {"teams": teams, "total": len(teams)}


@app.get("/api/v1/cluster/team/{team_id}")
def get_cluster_team(team_id: str) -> Dict[str, Any]:
    """Get topology details of a team."""
    team = CLUSTER_POOL.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team [{team_id}] not found.")
    return team.to_dict()


@app.delete("/api/v1/cluster/team/{team_id}")
@app.delete("/api/v1/cluster/teams/{team_id}")
def dissolve_cluster_team(team_id: str) -> Dict[str, Any]:
    """Dissolve a team topology and reset member roles to solo."""
    success = CLUSTER_POOL.dissolve_team(team_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Team [{team_id}] not found.")
    return {"status": "dissolved", "team_id": team_id}


@app.post("/api/v1/cluster/team/start")
def start_cluster_team(req: StartTeamRoutineRequest) -> Dict[str, Any]:
    """Concurrently launch cooperative routines for all team members."""
    try:
        results = CLUSTER_POOL.start_team_routine(
            team_id=req.team_id,
            leader_pipelines=req.leader_pipelines,
            member_pipelines=req.member_pipelines,
            leader_vars=req.leader_vars,
            member_vars=req.member_vars,
        )
        return {"status": "started", "team_id": req.team_id, "instances": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/cluster/team/stop")
def stop_cluster_team(team_id: str) -> Dict[str, Any]:
    """Stop all running tasks in a team."""
    results = CLUSTER_POOL.stop_team(team_id)
    return {"status": "stopped", "team_id": team_id, "instances": results}


@app.post("/api/v1/cluster/proxies/register")
def register_proxy(req: RegisterProxyRequest) -> Dict[str, Any]:
    """Register a dedicated proxy into the proxy pool."""
    p = PROXY_MANAGER.register_proxy(
        proxy_id=req.proxy_id,
        host=req.host,
        port=req.port,
        protocol=req.protocol,
        username=req.username,
        password=req.password,
        max_instances=req.max_instances,
        label=req.label,
        location=req.location,
    )
    return {"status": "registered", "proxy": p.to_dict()}


@app.get("/api/v1/cluster/proxies")
def list_proxies() -> Dict[str, Any]:
    """List all registered proxies and quota usage."""
    return {
        "stats": PROXY_MANAGER.get_proxy_stats(),
        "proxies": [p.to_dict() for p in PROXY_MANAGER.list_proxies()],
    }


@app.post("/api/v1/cluster/proxies/bind")
def bind_proxy(req: BindProxyRequest) -> Dict[str, Any]:
    """Bind an instance to a dedicated proxy with <=5 quota enforcement."""
    try:
        success = PROXY_MANAGER.bind_instance_to_proxy(req.instance_id, req.proxy_id)
        inst = CLUSTER_POOL.get_instance(req.instance_id)
        if inst:
            inst.assigned_proxy_id = req.proxy_id
        return {"status": "bound", "instance_id": req.instance_id, "proxy_id": req.proxy_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/cluster/proxies/unbind")
def unbind_proxy(req: UnbindProxyRequest) -> Dict[str, Any]:
    """Unbind an instance from its proxy, releasing quota."""
    success = PROXY_MANAGER.unbind_instance(req.instance_id)
    inst = CLUSTER_POOL.get_instance(req.instance_id)
    if inst:
        inst.assigned_proxy_id = None
    if not success:
        raise HTTPException(status_code=404, detail=f"Instance [{req.instance_id}] was not bound to any proxy.")
    return {"status": "unbound", "instance_id": req.instance_id}


@app.delete("/api/v1/cluster/proxies/{proxy_id}")
def unregister_proxy(proxy_id: str) -> Dict[str, Any]:
    """Unregister and remove a dedicated proxy from the pool."""
    success = PROXY_MANAGER.unregister_proxy(proxy_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Proxy [{proxy_id}] not found.")
    return {"status": "unregistered", "proxy_id": proxy_id}


@app.post("/api/v1/cluster/accounts/register")
def register_account(req: RegisterAccountRequest) -> Dict[str, Any]:
    """Register an account into the account matrix."""
    acc = AccountConfig(
        account_id=req.account_id,
        username=req.username,
        password=req.password,
        server_name=req.server_name,
        role_name=req.role_name,
        level=req.level,
        sect=req.sect,
        team_role_preference=req.team_role_preference,
    )
    ACCOUNT_MATRIX.register_account(acc)
    return {"status": "registered", "account": acc.to_dict()}


@app.get("/api/v1/cluster/accounts")
def list_accounts() -> Dict[str, Any]:
    """List accounts and aggregated gold/silver asset earnings."""
    return {
        "assets": ACCOUNT_MATRIX.get_total_assets(),
        "accounts": ACCOUNT_MATRIX.export_to_dict(),
    }


@app.post("/api/v1/cluster/accounts/{account_id}/rest")
def rest_account(account_id: str) -> Dict[str, Any]:
    """Manually force an account into resting state for anti-bot fatigue management."""
    acc = ACCOUNT_MATRIX.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail=f"Account [{account_id}] not found.")
    acc.trigger_rest()
    return {"status": "resting", "account": acc.to_dict()}


@app.get("/api/v1/cluster/supervisor/status")
def get_supervisor_status() -> Dict[str, Any]:
    """Get 7x24h cluster supervisor watchdog status."""
    return SUPERVISOR.get_status()


@app.post("/api/v1/cluster/supervisor/check")
def trigger_supervisor_check() -> Dict[str, Any]:
    """Trigger an immediate synchronous watchdog inspection pass."""
    return SUPERVISOR.check_once()


# =====================================================================
# Milestone 6: 24h Soak Test Telemetry & API Stress Testing Endpoints
# =====================================================================

SOAK_REPORT_JSON = Path("logs/soak_test_report.json")
SOAK_REPORT_CSV = Path("logs/soak_test_report.csv")
SOAK_PID_FILE = Path("logs/soak_test.pid")


class StartSoakRequest(BaseModel):
    duration_hours: float = Field(default=24.0, description="Test duration in hours")
    instances: int = Field(default=5, description="Number of instances")
    sample_interval_sec: float = Field(default=10.0, description="Telemetry sample interval")
    device_type: str = Field(default="virtual", description="'virtual' or 'adb'")
    inject_faults: bool = Field(default=True, description="Enable periodic chaos fault injection")
    enable_cv_stress: bool = Field(default=True, description="Enable synthetic CV/OCR compute load")


class RunAPIStressRequest(BaseModel):
    target_url: Optional[str] = Field(default=None, description="Target base URL. If omitted or in_process=True, uses in-process ASGI transport.")
    concurrency: int = Field(default=15, description="Number of concurrent virtual clients")
    requests: int = Field(default=300, description="Total number of requests")
    p95_threshold_ms: float = Field(default=500.0, description="P95 latency SLA threshold in ms")
    in_process: bool = Field(default=False, description="Use in-process ASGI transport")


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


@app.get("/api/v1/soak/status")
def get_soak_status() -> Dict[str, Any]:
    """Fetch current 24h soak test execution status, memory drift, and SLA metrics."""
    is_running = False
    pid: Optional[int] = None
    if SOAK_PID_FILE.exists():
        try:
            pid = int(SOAK_PID_FILE.read_text().strip())
            is_running = _is_pid_alive(pid)
        except Exception:
            is_running = False

    telemetry_samples = 0
    baseline_rss_mb = 0.0
    current_rss_mb = 0.0
    memory_drift_pct = 0.0
    elapsed_sec = 0.0
    active_instances = 0
    completed_ops = 0
    faults_recovered = 0
    deadlocks_detected = 0

    if SOAK_REPORT_CSV.exists():
        try:
            with open(SOAK_REPORT_CSV, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                rows = [r for r in reader if len(r) >= 7]
                telemetry_samples = len(rows)
                if rows:
                    first = rows[0]
                    last = rows[-1]
                    baseline_rss_mb = round(float(first[2]), 2)
                    current_rss_mb = round(float(last[2]), 2)
                    memory_drift_pct = round(((current_rss_mb - baseline_rss_mb) / max(baseline_rss_mb, 1.0)) * 100.0, 2)
                    elapsed_sec = round(float(last[1]), 1)
                    active_instances = int(last[3])
                    completed_ops = int(last[4])
                    faults_recovered = int(last[5])
                    deadlocks_detected = int(last[6])
        except Exception as e:
            logger.warning(f"Failed to read soak telemetry CSV: {e}")

    summary_data = {}
    if SOAK_REPORT_JSON.exists():
        try:
            with open(SOAK_REPORT_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                summary_data = data.get("summary", {})
        except Exception:
            pass

    return {
        "is_running": is_running,
        "pid": pid if is_running else None,
        "elapsed_sec": elapsed_sec,
        "baseline_rss_mb": baseline_rss_mb or summary_data.get("baseline_rss_mb", 0.0),
        "current_rss_mb": current_rss_mb or summary_data.get("final_rss_mb", 0.0),
        "memory_drift_pct": memory_drift_pct if telemetry_samples > 0 else summary_data.get("memory_drift_pct", 0.0),
        "active_instances": active_instances or (5 if is_running else 0),
        "total_instances": summary_data.get("num_instances", 5),
        "completed_ops": completed_ops or summary_data.get("total_tasks_completed", 0),
        "faults_recovered": faults_recovered or summary_data.get("total_faults_recovered", 0),
        "deadlocks_detected": deadlocks_detected or summary_data.get("deadlocks_detected", 0),
        "total_samples": telemetry_samples,
        "sla_passed": summary_data.get("passed_sla", abs(memory_drift_pct) <= 5.0 and deadlocks_detected == 0),
        "sla_violations": summary_data.get("sla_violations", []),
    }


@app.get("/api/v1/soak/telemetry")
def get_soak_telemetry(limit: int = 50) -> Dict[str, Any]:
    """Fetch the latest time-series telemetry samples from soak test CSV."""
    if not SOAK_REPORT_CSV.exists():
        return {"samples": [], "total_recorded": 0}

    samples = []
    try:
        with open(SOAK_REPORT_CSV, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for r in reader:
                if len(r) >= 7:
                    samples.append({
                        "timestamp": float(r[0]),
                        "elapsed_sec": float(r[1]),
                        "rss_mb": float(r[2]),
                        "active_instances": int(r[3]),
                        "completed_tasks": int(r[4]),
                        "faults_recovered": int(r[5]),
                        "deadlocks_detected": int(r[6]),
                    })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read CSV: {e}")

    return {
        "samples": samples[-limit:],
        "total_recorded": len(samples),
    }


@app.post("/api/v1/soak/start")
def start_soak_test(req: StartSoakRequest) -> Dict[str, Any]:
    """Start the soak test runner daemon in background."""
    if SOAK_PID_FILE.exists():
        try:
            pid = int(SOAK_PID_FILE.read_text().strip())
            if _is_pid_alive(pid):
                raise HTTPException(status_code=409, detail=f"Soak test is already running (PID: {pid}).")
        except HTTPException:
            raise
        except Exception:
            pass

    cmd = [
        sys.executable,
        "scripts/soak_test_24h.py",
        "--duration-hours", str(req.duration_hours),
        "--sample-interval-sec", str(req.sample_interval_sec),
        "--instances", str(req.instances),
        "--device-type", req.device_type,
        "--report", str(SOAK_REPORT_JSON),
    ]
    if not req.inject_faults:
        cmd.append("--no-faults")
    if not req.enable_cv_stress:
        cmd.append("--no-cv-stress")

    log_path = Path("logs/soak_test_24h.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8")

    proc = subprocess.Popen(cmd, stdout=log_file, stderr=log_file, start_new_session=True)
    SOAK_PID_FILE.write_text(str(proc.pid))
    logger.info(f"Soak test spawned via REST API with PID: {proc.pid}")

    return {
        "status": "started",
        "pid": proc.pid,
        "duration_hours": req.duration_hours,
        "instances": req.instances,
    }


@app.post("/api/v1/soak/stop")
def stop_soak_test() -> Dict[str, Any]:
    """Stop the background soak test process gracefully."""
    if not SOAK_PID_FILE.exists():
        return {"status": "not_running"}

    try:
        pid = int(SOAK_PID_FILE.read_text().strip())
        if _is_pid_alive(pid):
            os.kill(pid, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to soak test PID: {pid}")
            time.sleep(0.5)
            return {"status": "stopped", "pid": pid}
        else:
            return {"status": "already_stopped", "pid": pid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop soak test: {e}")


@app.post("/api/v1/stress/run")
async def run_api_stress(req: RunAPIStressRequest) -> Dict[str, Any]:
    """Trigger an on-demand high-concurrency API stress test against this server."""
    from scripts.api_stress_test import APIStressTester
    base_url = req.target_url or "http://127.0.0.1:8000"
    app_to_test = app if (req.in_process or not req.target_url) else None
    tester = APIStressTester(
        base_url=base_url,
        concurrency=req.concurrency,
        total_requests=req.requests,
        p95_threshold_ms=req.p95_threshold_ms,
        report_path="reports/api_stress_report.json",
        app=app_to_test,
    )
    summary = await tester.run()
    return {
        "status": "completed",
        "passed_sla": summary.passed_sla,
        "qps": summary.qps,
        "overall_p50_ms": summary.overall_p50_ms,
        "overall_p95_ms": summary.overall_p95_ms,
        "overall_p99_ms": summary.overall_p99_ms,
        "total_requests": summary.total_requests,
        "total_success": summary.total_success,
        "sla_violations": summary.sla_violations,
        "endpoints": summary.endpoints,
    }


