"""
7x24h Cluster Supervisor, Watchdog Daemon & Self-Healing Engine.
Performs periodic heartbeat inspection, ADB connection recovery, game crash auto-restart,
anti-bot circuit breaker capture, and multi-channel webhook alert escalation.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from loguru import logger

from cluster.account import AccountMatrix
from cluster.instance_pool import DeviceInstance, InstancePool, InstanceStatus
from cluster.proxy import ProxyManager
from core.notify.webhook import WebhookNotifier
from scheduler.routine import RoutineStatus


class SupervisorConfig(BaseModel):
    """Configuration for cluster watchdog thresholds and healing policies."""
    check_interval_sec: float = Field(default=5.0, description="Watchdog polling interval")
    stall_threshold_sec: float = Field(default=60.0, description="Max allowed silent period for busy instance")
    max_reconnect_attempts: int = Field(default=3, description="Max ADB reconnection retries before ERROR state")
    max_app_restarts: int = Field(default=3, description="Max client process restarts per instance")
    enable_app_watchdog: bool = Field(default=True, description="Detect and auto-restart crashed game processes")
    target_package: str = Field(default="com.netease.my", description="Monitored game package name")
    enable_webhook_alerts: bool = Field(default=True, description="Send notifications via Feishu/WeChat/Telegram")
    enable_account_rotation: bool = Field(default=True, description="Periodically rotate fatigued accounts")


class ClusterSupervisor:
    """
    Central self-healing daemon monitoring health across all pool instances.
    """

    _instance: Optional[ClusterSupervisor] = None

    def __init__(
        self,
        instance_pool: Optional[InstancePool] = None,
        proxy_manager: Optional[ProxyManager] = None,
        account_matrix: Optional[AccountMatrix] = None,
        config: Optional[SupervisorConfig] = None,
        notifier: Optional[WebhookNotifier] = None,
    ) -> None:
        self._instance_pool = instance_pool
        self._proxy_manager = proxy_manager
        self._account_matrix = account_matrix
        self.config = config or SupervisorConfig()
        self.notifier = notifier or WebhookNotifier.get_instance()

        self.reconnect_counts: Dict[str, int] = {}
        self.app_restart_counts: Dict[str, int] = {}
        self.total_healed_events: int = 0
        self.total_alerts_sent: int = 0
        self.last_check_time: float = 0.0

        self.running: bool = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    @property
    def instance_pool(self) -> InstancePool:
        if self._instance_pool is not None:
            return self._instance_pool
        return InstancePool.get_pool()

    @instance_pool.setter
    def instance_pool(self, val: Optional[InstancePool]) -> None:
        self._instance_pool = val

    @property
    def proxy_manager(self) -> ProxyManager:
        if self._proxy_manager is not None:
            return self._proxy_manager
        return ProxyManager.get_instance()

    @proxy_manager.setter
    def proxy_manager(self, val: Optional[ProxyManager]) -> None:
        self._proxy_manager = val

    @property
    def account_matrix(self) -> AccountMatrix:
        if self._account_matrix is not None:
            return self._account_matrix
        return AccountMatrix.get_instance()

    @account_matrix.setter
    def account_matrix(self, val: Optional[AccountMatrix]) -> None:
        self._account_matrix = val

    @classmethod
    def get_instance(cls) -> ClusterSupervisor:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        """Start the supervisor background watchdog thread."""
        with self._lock:
            if self.running:
                logger.info("ClusterSupervisor is already running.")
                return

            self.running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._watchdog_loop,
                name="ClusterSupervisorWatchdog",
                daemon=True,
            )
            self._thread.start()
            logger.info("ClusterSupervisor background watchdog thread started.")

    def stop(self) -> None:
        """Stop supervisor thread."""
        with self._lock:
            if not self.running:
                return

            self._stop_event.set()
            self.running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
                self._thread = None
            logger.info("ClusterSupervisor background watchdog thread stopped.")

    def _watchdog_loop(self) -> None:
        """Internal daemon loop executing periodic health inspections."""
        while not self._stop_event.is_set():
            try:
                self.check_once()
            except Exception as e:
                logger.error(f"Error during supervisor health inspection: {e}")

            self._stop_event.wait(self.config.check_interval_sec)

    def check_once(self) -> Dict[str, Any]:
        """
        Execute a single synchronous cluster inspection pass.
        Returns diagnostic statistics of detected and healed anomalies.
        """
        with self._lock:
            self.last_check_time = time.time()
            now = time.time()
            stalled_instances: List[str] = []
            reconnected_instances: List[str] = []
            restarted_apps: List[str] = []
            circuit_broken_instances: List[str] = []

            instances = self.instance_pool.list_instances()

            for inst in instances:
                inst_id = inst.instance_id

                # 1. Device Connection Inspection & Auto-Reconnect
                if not inst.device or not inst.device.is_connected() or inst.status == InstanceStatus.DISCONNECTED:
                    attempts = self.reconnect_counts.get(inst_id, 0)
                    if attempts < self.config.max_reconnect_attempts:
                        logger.warning(
                            f"Supervisor: Instance [{inst_id}] disconnected. Attempting reconnect ({attempts + 1}/{self.config.max_reconnect_attempts})..."
                        )
                        if inst.connect():
                            self.reconnect_counts[inst_id] = 0
                            self.total_healed_events += 1
                            reconnected_instances.append(inst_id)
                            logger.info(f"Supervisor: Reconnected instance [{inst_id}] successfully.")
                        else:
                            self.reconnect_counts[inst_id] = attempts + 1
                    else:
                        inst.status = InstanceStatus.ERROR
                        inst.error_message = f"ADB disconnection unresolved after {attempts} attempts."
                        self._dispatch_alert(
                            title=f"集群实例掉线严重告警 [{inst_id}]",
                            message=f"实例 [{inst_id}] 连续 {attempts} 次重连 ADB 失败，已被标记为 ERROR 状态，请人工介入检查宿主或网络。",
                        )

                # 2. Heartbeat Stall Inspection
                if inst.status == InstanceStatus.BUSY:
                    silent_time = now - inst.last_heartbeat_time
                    if silent_time > self.config.stall_threshold_sec:
                        logger.warning(
                            f"Supervisor: Instance [{inst_id}] stalled for {int(silent_time)}s "
                            f"(threshold: {int(self.config.stall_threshold_sec)}s)."
                        )
                        stalled_instances.append(inst_id)
                        # Soft recover by stopping active task
                        inst.stop()
                        inst.status = InstanceStatus.ERROR
                        inst.error_message = f"Task stalled for {int(silent_time)}s without heartbeat."
                        self.total_healed_events += 1
                        self._dispatch_alert(
                            title=f"实例任务假死预警 [{inst_id}]",
                            message=f"实例 [{inst_id}] 超过 {int(silent_time)} 秒未产生有效心跳，看门狗已执行安全强制刹车。",
                        )

                # 3. Game Process Crash Detection & Auto-Restart
                if (
                    self.config.enable_app_watchdog
                    and inst.status == InstanceStatus.BUSY
                    and inst.device
                    and inst.device.is_connected()
                    and hasattr(inst.device, "is_app_running")
                    and hasattr(inst.device, "start_app")
                ):
                    try:
                        is_running = inst.device.is_app_running(self.config.target_package)
                        if not is_running:
                            restarts = self.app_restart_counts.get(inst_id, 0)
                            if restarts < self.config.max_app_restarts:
                                logger.warning(
                                    f"Supervisor: Game client [{self.config.target_package}] crashed on [{inst_id}]. "
                                    f"Attempting auto-restart ({restarts + 1}/{self.config.max_app_restarts})..."
                                )
                                if hasattr(inst.device, "stop_app"):
                                    inst.device.stop_app(self.config.target_package)
                                time.sleep(0.5)
                                started = inst.device.start_app(self.config.target_package)
                                self.app_restart_counts[inst_id] = restarts + 1
                                self.total_healed_events += 1
                                restarted_apps.append(inst_id)

                                self._dispatch_alert(
                                    title=f"游戏客户端异常崩溃自愈 [{inst_id}]",
                                    message=f"检测到实例 [{inst_id}] 上的游戏进程 [{self.config.target_package}] 异常闪退，看门狗已自动拉起重启（第 {restarts + 1} 次）。",
                                )
                            else:
                                inst.status = InstanceStatus.ERROR
                                inst.error_message = f"Game crashed exceeded max restarts ({restarts})."
                                self._dispatch_alert(
                                    title=f"客户端反复崩溃熔断 [{inst_id}]",
                                    message=f"实例 [{inst_id}] 上的游戏客户端反复崩溃达 {restarts} 次，已终止自愈并置为 ERROR。",
                                )
                    except Exception as e:
                        logger.error(f"Supervisor: App running check error on [{inst_id}]: {e}")

                # 4. Anti-Bot Circuit Breaker Escalation
                if (
                    inst.routine_executor
                    and inst.routine_executor.status == RoutineStatus.CIRCUIT_BROKEN
                ):
                    circuit_broken_instances.append(inst_id)
                    inst.status = InstanceStatus.ERROR
                    inst.error_message = "Anti-bot circuit breaker tripped."

                    # Capture emergency screenshot
                    screenshot_bytes = None
                    try:
                        screenshot_bytes = inst.screencap(raw=True)
                    except Exception as e:
                        logger.warning(f"Failed to capture emergency screenshot on [{inst_id}]: {e}")

                    self._dispatch_alert(
                        title=f"防挂机熔断紧急告警 [{inst_id}]",
                        message=f"实例 [{inst_id}] 触发连续防挂机识别失败熔断，自动化已强制制动，请立即人工核验！",
                        screenshot_bytes=screenshot_bytes,
                    )

            # 5. Account Fatigue Rotation
            rotated_accounts = []
            if self.config.enable_account_rotation and self.account_matrix:
                try:
                    rotated_accounts = self.account_matrix.rotate_fatigued_accounts()
                except Exception as e:
                    logger.error(f"Supervisor error during account rotation: {e}")

            return {
                "inspected_instances": len(instances),
                "stalled_instances": stalled_instances,
                "reconnected_instances": reconnected_instances,
                "restarted_apps": restarted_apps,
                "circuit_broken_instances": circuit_broken_instances,
                "rotated_accounts_count": len(rotated_accounts),
                "total_healed_events": self.total_healed_events,
            }

    def _dispatch_alert(
        self,
        title: str,
        message: str,
        screenshot_bytes: Optional[bytes] = None,
    ) -> None:
        """Forward alert to configured Webhook channels."""
        if not self.config.enable_webhook_alerts or not self.notifier:
            return

        self.total_alerts_sent += 1
        try:
            if hasattr(self.notifier, "send_alert"):
                self.notifier.send_alert(
                    title=title,
                    message=message,
                    level="warning",
                    image_bytes=screenshot_bytes,
                )
            elif hasattr(self.notifier, "broadcast_alert"):
                self.notifier.broadcast_alert(
                    title=title,
                    message=message,
                    screenshot_bytes=screenshot_bytes,
                )
        except Exception as e:
            logger.warning(f"Failed to broadcast webhook alert: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Diagnostic state of the supervisor."""
        with self._lock:
            return {
                "running": self.running,
                "check_interval_sec": self.config.check_interval_sec,
                "stall_threshold_sec": self.config.stall_threshold_sec,
                "last_check_ago_sec": round(time.time() - self.last_check_time, 2) if self.last_check_time > 0 else -1,
                "total_healed_events": self.total_healed_events,
                "total_alerts_sent": self.total_alerts_sent,
                "reconnect_counts": dict(self.reconnect_counts),
                "app_restart_counts": dict(self.app_restart_counts),
            }
