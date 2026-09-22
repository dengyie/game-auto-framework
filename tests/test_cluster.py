"""
Comprehensive Test Suite for Milestone 3 (M3: Cluster Scheduling, Proxy Isolation,
Account Matrix & Self-Healing Supervisor).
"""

import time
import pytest
from fastapi.testclient import TestClient

from cluster.instance_pool import (
    DeviceInstance,
    InstancePool,
    InstanceStatus,
    TeamRole,
    TeamTopology,
)
from cluster.proxy import (
    ProxyConfig,
    ProxyManager,
    ProxyProtocol,
    ProxyQuotaExceededError,
    ProxyStatus,
)
from cluster.account import (
    AccountConfig,
    AccountMatrix,
    AccountStatus,
)
from cluster.supervisor import (
    ClusterSupervisor,
    SupervisorConfig,
)
from core.device.virtual import VirtualDevice
from scheduler.dag import PipelineStatus
from scheduler.routine import RoutineConfig, RoutineStatus, TaskRoutineExecutor
from server.app import app


# --------------------------------------------------------------------------
# 1. DeviceInstance & InstancePool Tests
# --------------------------------------------------------------------------

def test_device_instance_lifecycle():
    """Verify single instance lifecycle: connect, run pipeline, stop, and health."""
    inst = DeviceInstance(
        instance_id="test_inst_01",
        device_type="virtual",
        name="Virtual_01",
    )
    assert inst.connect() is True
    assert inst.status == InstanceStatus.IDLE
    assert inst.device.is_connected() is True

    # Capture frame
    frame = inst.screencap()
    assert isinstance(frame, bytes) and len(frame) > 0

    # Start pipeline in synchronous mode (run_in_background=False for deterministic testing)
    success = inst.start_pipeline("daily_shimen", run_in_background=False)
    assert success is True
    assert inst.status == InstanceStatus.BUSY

    # Tick
    p_status = inst.tick()
    assert p_status in (PipelineStatus.RUNNING, PipelineStatus.COMPLETED, PipelineStatus.IDLE)

    health = inst.get_health()
    assert health["instance_id"] == "test_inst_01"
    assert health["is_connected"] is True

    inst.stop()
    assert inst.status == InstanceStatus.IDLE

    inst.disconnect()
    assert inst.status == InstanceStatus.DISCONNECTED


def test_instance_pool_registration_and_allocation():
    """Verify pool registration, allocation, release, and stats."""
    pool = InstancePool()
    i1 = pool.register_instance("vm_1", device_type="virtual")
    i2 = pool.register_instance("vm_2", device_type="virtual")
    assert len(pool.list_instances()) == 2

    # Allocate
    claimed = pool.allocate_instance()
    assert claimed is not None
    claimed.status = InstanceStatus.BUSY

    # Next allocate gets the other idle one
    claimed_2 = pool.allocate_instance()
    assert claimed_2.instance_id != claimed.instance_id

    # Release
    pool.release_instance(claimed.instance_id)
    assert claimed.status == InstanceStatus.IDLE

    stats = pool.get_cluster_stats()
    assert stats["total_instances"] == 2


def test_team_topology_and_coordination():
    """Verify 1 Leader + 4 Members team creation, quota limits, and routines."""
    pool = InstancePool()
    for idx in range(1, 6):
        pool.register_instance(f"inst_t{idx}", device_type="virtual")

    # Create team
    team = pool.create_team(
        team_id="team_alpha",
        leader_id="inst_t1",
        member_ids=["inst_t2", "inst_t3", "inst_t4", "inst_t5"],
        target_activity="team_zhuogui",
    )
    assert team.is_full() is True
    assert len(team.all_instance_ids()) == 5

    # Check team roles
    assert pool.get_instance("inst_t1").team_role == TeamRole.LEADER
    assert pool.get_instance("inst_t2").team_role == TeamRole.MEMBER

    # Reject 5th member (>4 members)
    pool.register_instance("inst_t6", device_type="virtual")
    assert team.add_member("inst_t6") is False

    # Start team routine
    results = pool.start_team_routine(
        team_id="team_alpha",
        leader_pipelines=["zhuogui"],
        member_pipelines=["zhuogui"],
        run_in_background=False,
    )
    assert len(results) == 5
    for inst_id, ok in results.items():
        assert ok is True

    # Stop team
    stop_results = pool.stop_team("team_alpha")
    assert len(stop_results) == 5

    # Dissolve team
    assert pool.dissolve_team("team_alpha") is True
    assert pool.get_instance("inst_t1").team_role == TeamRole.SOLO


# --------------------------------------------------------------------------
# 2. ProxyManager & Anti-Bot Quota Isolation Tests
# --------------------------------------------------------------------------

def test_proxy_manager_registration_and_url():
    """Verify proxy registration, auth formatting, and stats."""
    pm = ProxyManager()
    p1 = pm.register_proxy("p1", host="10.0.0.1", port=1080, protocol="socks5")
    assert p1.url == "socks5://10.0.0.1:1080"
    assert p1.max_instances == 5
    assert p1.available_slots == 5

    p2 = pm.register_proxy(
        "p2", host="10.0.0.2", port=8080, protocol="http", username="usr", password="pwd"
    )
    assert p2.url == "http://usr:pwd@10.0.0.2:8080"


def test_proxy_strict_quota_enforcement():
    """
    CRITICAL ANTI-BOT TEST: Verify that binding <= 5 instances succeeds,
    and the 6th instance raises ProxyQuotaExceededError.
    """
    pm = ProxyManager()
    p = pm.register_proxy("p_dedicated", host="127.0.0.1", port=1080, max_instances=5)

    # Bind 5 instances (1 full team)
    for i in range(1, 6):
        assert pm.bind_instance_to_proxy(f"device_{i}", "p_dedicated") is True

    assert p.available_slots == 0
    assert p.is_available is False

    # 6th attempt MUST fail with ProxyQuotaExceededError
    with pytest.raises(ProxyQuotaExceededError) as exc_info:
        pm.bind_instance_to_proxy("device_6", "p_dedicated")

    assert "quota reached" in str(exc_info.value).lower()
    assert "anti-bot" in str(exc_info.value).lower()

    # Unbind one instance -> slot restored
    assert pm.unbind_instance("device_1") is True
    assert p.available_slots == 1

    # Now device_6 can bind
    assert pm.bind_instance_to_proxy("device_6", "p_dedicated") is True
    assert p.available_slots == 0


def test_proxy_load_balancing_selection():
    """Verify get_available_proxy chooses the proxy with lowest active load."""
    pm = ProxyManager()
    pm.register_proxy("px_a", host="1.1.1.1", port=1080)
    pm.register_proxy("px_b", host="2.2.2.2", port=1080)

    pm.bind_instance_to_proxy("dev_1", "px_a")
    pm.bind_instance_to_proxy("dev_2", "px_a")
    pm.bind_instance_to_proxy("dev_3", "px_b")

    # px_b has 1 instance, px_a has 2 instances -> should choose px_b
    chosen = pm.get_available_proxy()
    assert chosen.proxy_id == "px_b"


# --------------------------------------------------------------------------
# 3. AccountMatrix & Humanized Work-Rest Scheduler Tests
# --------------------------------------------------------------------------

def test_account_income_and_vitality():
    """Verify earnings accumulation and vitality consumption."""
    acc = AccountConfig(
        account_id="acc_01",
        username="player01@163.com",
        password="Password123",
        role_name="逍遥生",
        sect="大唐官府",
    )
    acc.add_income(gold=5000, silver=150000, active_points=40)
    assert acc.gold_coins == 5000
    assert acc.silver_coins == 150000
    assert acc.daily_active_points == 40

    consumed = acc.consume_vitality(100)
    assert consumed == 100
    assert acc.vitality == 400


def test_account_fatigue_and_rest_cycle():
    """Verify physiological fatigue detection and rest recovery."""
    acc = AccountConfig(
        account_id="acc_fatigue_test",
        username="test@163.com",
        password="pwd",
        max_continuous_online_seconds=10.0,  # 10s for fast testing
        rest_duration_seconds=2.0,           # 2s rest
    )
    acc.start_session("inst_1", "proxy_1")
    assert acc.status == AccountStatus.IN_USE

    # Not fatigued yet
    assert acc.is_fatigued() is False

    # Force simulated online time
    acc.accumulated_online_seconds = 15.0
    assert acc.is_fatigued() is True

    # Trigger rest
    acc.trigger_rest()
    assert acc.status == AccountStatus.RESTING
    assert acc.bound_instance_id is None

    # Check recovery before time elapsed
    assert acc.check_rest_recovery() is False

    # Fast forward rest time
    acc.resting_until = time.time() - 1.0
    assert acc.check_rest_recovery() is True
    assert acc.status == AccountStatus.IDLE
    assert acc.accumulated_online_seconds == 0.0


def test_account_matrix_rotation():
    """Verify automatic rotation of fatigued account to idle backup account."""
    matrix = AccountMatrix()

    # Active account
    a1 = AccountConfig(
        account_id="acc_main",
        username="main@163.com",
        password="pwd",
        team_role_preference="leader",
        sect="方寸山",
        max_continuous_online_seconds=5.0,
    )
    # Standby replacement account
    a2 = AccountConfig(
        account_id="acc_backup",
        username="backup@163.com",
        password="pwd",
        team_role_preference="leader",
        sect="方寸山",
    )
    matrix.register_account(a1)
    matrix.register_account(a2)

    a1.start_session(instance_id="inst_leader", proxy_id="proxy_1")
    a1.accumulated_online_seconds = 10.0  # Fatigued!

    # Execute rotation
    rotations = matrix.rotate_fatigued_accounts()
    assert len(rotations) == 1
    fatigued_id, rep_id = rotations[0]
    assert fatigued_id == "acc_main"
    assert rep_id == "acc_backup"

    # Verify states
    assert a1.status == AccountStatus.RESTING
    assert a2.status == AccountStatus.IN_USE
    assert a2.bound_instance_id == "inst_leader"

    # Assets summary
    assets = matrix.get_total_assets()
    assert assets["total_accounts"] >= 2


# --------------------------------------------------------------------------
# 4. ClusterSupervisor & Self-Healing Watchdog Tests
# --------------------------------------------------------------------------

class MockCrashingDevice(VirtualDevice):
    """Virtual device that simulates app crashes and recovery."""

    def __init__(self, name: str = "mock_crash_dev") -> None:
        super().__init__(name=name)
        self._app_running = True
        self.stop_app_called = 0
        self.start_app_called = 0

    def is_app_running(self, package_name: str) -> bool:
        return self._app_running

    def stop_app(self, package_name: str) -> bool:
        self.stop_app_called += 1
        self._app_running = False
        return True

    def start_app(self, package_name: str, activity: str = None) -> bool:
        self.start_app_called += 1
        self._app_running = True
        return True


def test_supervisor_crash_detection_and_self_healing():
    """Verify supervisor automatically detects game process death and restarts it."""
    pool = InstancePool()
    inst = pool.register_instance("crash_inst", device_type="virtual")
    crash_dev = MockCrashingDevice()
    crash_dev.connect()
    inst.device = crash_dev
    inst.status = InstanceStatus.BUSY

    # Simulate app crash
    crash_dev._app_running = False

    supervisor = ClusterSupervisor(
        instance_pool=pool,
        config=SupervisorConfig(enable_webhook_alerts=False),
    )

    # Perform health inspection pass
    res = supervisor.check_once()
    assert "crash_inst" in res["restarted_apps"]
    assert crash_dev.start_app_called == 1
    assert supervisor.total_healed_events == 1
    assert crash_dev.is_app_running("com.netease.my") is True


def test_supervisor_reconnect_disconnected_device():
    """Verify supervisor attempts reconnection when device is disconnected."""
    pool = InstancePool()
    inst = pool.register_instance("dc_inst", device_type="virtual")
    inst.connect()
    inst.device.disconnect()  # Force disconnect

    supervisor = ClusterSupervisor(
        instance_pool=pool,
        config=SupervisorConfig(enable_webhook_alerts=False),
    )
    res = supervisor.check_once()
    assert "dc_inst" in res["reconnected_instances"]
    assert inst.device.is_connected() is True


# --------------------------------------------------------------------------
# 5. Server REST API Cluster Endpoints Integration Tests
# --------------------------------------------------------------------------

def test_api_cluster_endpoints():
    """Verify FastAPI cluster REST endpoints work end-to-end."""
    client = TestClient(app)

    # 1. Cluster Status
    resp = client.get("/api/v1/cluster/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "cluster" in data and "proxy" in data and "assets" in data

    # 2. Register Instance
    resp = client.post(
        "/api/v1/cluster/instances/register",
        json={"instance_id": "api_inst_01", "device_type": "virtual", "name": "API_V1"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "registered"

    # 3. List Instances
    resp = client.get("/api/v1/cluster/instances")
    assert resp.status_code == 200
    instances = resp.json()
    assert any(i["instance_id"] == "api_inst_01" for i in instances)

    # 4. Get Screenshot
    resp = client.get("/api/v1/cluster/instances/api_inst_01/screenshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"

    # 5. Register Proxy
    resp = client.post(
        "/api/v1/cluster/proxies/register",
        json={
            "proxy_id": "api_proxy_01",
            "host": "127.0.0.1",
            "port": 1080,
            "protocol": "socks5",
            "max_instances": 5,
        },
    )
    assert resp.status_code == 200

    # 6. Bind Proxy
    resp = client.post(
        "/api/v1/cluster/proxies/bind",
        json={"instance_id": "api_inst_01", "proxy_id": "api_proxy_01"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "bound"

    # 7. Register Account
    resp = client.post(
        "/api/v1/cluster/accounts/register",
        json={
            "account_id": "api_acc_01",
            "username": "api_test@163.com",
            "password": "Password123",
            "server_name": "东海湾",
            "role_name": "测试号",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "registered"

    # 8. List Accounts
    resp = client.get("/api/v1/cluster/accounts")
    assert resp.status_code == 200
    assert "assets" in resp.json()

    # 9. Trigger Supervisor Check
    resp = client.post("/api/v1/cluster/supervisor/check")
    assert resp.status_code == 200
    assert "inspected_instances" in resp.json()

    # 10. Stop Instance
    resp = client.post("/api/v1/cluster/instances/api_inst_01/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
