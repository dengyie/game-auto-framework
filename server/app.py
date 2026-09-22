"""
FastAPI Server for Remote Invocation on Linux VPS / Windows / macOS.
Provides REST endpoints to start/stop pipelines, monitor progress, chain routines, and stream screenshots.
"""

from __future__ import annotations
from pathlib import Path
import sys
import threading
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
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
@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard() -> HTMLResponse:
    """Serve the embedded modern dark-mode Web Dashboard."""
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


# =====================================================================
# Milestone 3: Cluster, Multi-Instance, Proxy & Account REST Endpoints
# =====================================================================

CLUSTER_POOL = InstancePool.get_pool()
PROXY_MANAGER = ProxyManager.get_instance()
ACCOUNT_MATRIX = AccountMatrix.get_instance()
SUPERVISOR = ClusterSupervisor.get_instance()


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

