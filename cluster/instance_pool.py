"""
Multi-instance Window/Device Cluster Pool & Team Topology Orchestrator.
Manages concurrent ADB and Virtual device instances, isolated execution threads,
and 1 Leader + 4 Members team coordination for game automation.
"""

from __future__ import annotations

import sys
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
from loguru import logger

from core.device.base import BaseDevice
from core.device.factory import DeviceFactory
from plugins.base import BaseGamePlugin
from plugins.registry import GamePluginRegistry
from scheduler.dag import PipelineStatus
from scheduler.routine import RoutineConfig, RoutineStatus, TaskRoutineExecutor


class InstanceStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    DISCONNECTED = "disconnected"
    MAINTENANCE = "maintenance"


class TeamRole(str, Enum):
    LEADER = "leader"
    MEMBER = "member"
    SOLO = "solo"


class DeviceInstance:
    """Represents a single managed device execution container."""

    def __init__(
        self,
        instance_id: str,
        device_type: str = "auto",
        serial: Optional[str] = None,
        name: Optional[str] = None,
        resolution: Tuple[int, int] = (1280, 720),
    ) -> None:
        self.instance_id = instance_id
        self.device_type = device_type
        self.serial = serial
        self.name = name or f"inst_{instance_id}"
        self.resolution = resolution

        self.device: Optional[BaseDevice] = None
        self.plugin: Optional[BaseGamePlugin] = None
        self.routine_executor: Optional[TaskRoutineExecutor] = None
        self.pipeline_name: Optional[str] = None
        self.is_routine: bool = False

        self.status = InstanceStatus.IDLE
        self.pipeline_status = PipelineStatus.IDLE
        self.team_id: Optional[str] = None
        self.team_role = TeamRole.SOLO
        self.assigned_account_id: Optional[str] = None
        self.assigned_proxy_id: Optional[str] = None

        self.start_time: float = 0.0
        self.last_heartbeat_time: float = time.time()
        self.last_tick_time: float = 0.0
        self.error_message: Optional[str] = None
        self.completed_cycles: int = 0

        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self._state_lock = threading.RLock()
        self._exec_lock = threading.Lock()
        self._lock = self._state_lock  # Backward compatibility alias

    def connect(self) -> bool:
        """Initialize and connect the underlying device."""
        with self._state_lock:
            try:
                if self.device is None:
                    self.device = DeviceFactory.create(
                        device_type=self.device_type,
                        serial=self.serial,
                        name=self.name,
                        resolution=self.resolution,
                    )
                connected = self.device.connect()
                if connected:
                    self.status = InstanceStatus.IDLE
                    self.last_heartbeat_time = time.time()
                    self.error_message = None
                    logger.info(f"Instance [{self.instance_id}] connected successfully.")
                    return True
                else:
                    self.status = InstanceStatus.DISCONNECTED
                    self.error_message = f"Failed to connect device {self.serial or self.device_type}"
                    logger.warning(f"Instance [{self.instance_id}] connection failed.")
                    return False
            except Exception as e:
                self.status = InstanceStatus.ERROR
                self.error_message = str(e)
                logger.error(f"Instance [{self.instance_id}] error during connect: {e}")
                return False

    def heartbeat(self) -> None:
        """Update last heartbeat timestamp to now."""
        with self._state_lock:
            self.last_heartbeat_time = time.time()

    def disconnect(self) -> None:
        """Stop any running task and disconnect device."""
        with self._state_lock:
            self.stop()
            if self.device and self.device.is_connected():
                try:
                    self.device.disconnect()
                except Exception as e:
                    logger.warning(f"Instance [{self.instance_id}] error during disconnect: {e}")
            self.status = InstanceStatus.DISCONNECTED

    def start_pipeline(
        self,
        pipeline_name: str,
        variables: Optional[Dict[str, Any]] = None,
        plugin_cls: Optional[Type[BaseGamePlugin]] = None,
        plugin_id: str = "mhxy_mobile",
        run_in_background: bool = True,
    ) -> bool:
        """Start a single automation pipeline on this instance."""
        with self._state_lock:
            if self.status == InstanceStatus.BUSY:
                logger.warning(f"Instance [{self.instance_id}] is already BUSY.")
                return False

            if not self.device or not self.device.is_connected():
                if not self.connect():
                    return False

            # Initialize plugin
            if plugin_cls is not None:
                self.plugin = plugin_cls(device=self.device)
            else:
                self.plugin = GamePluginRegistry.create(plugin_id, device=self.device)
            if variables:
                for k, v in variables.items():
                    self.plugin.context.variables[k] = v

            self.pipeline_name = pipeline_name
            self.routine_executor = None
            self.is_routine = False
            self.status = InstanceStatus.BUSY
            self.pipeline_status = PipelineStatus.RUNNING
            self.start_time = time.time()
            self.last_heartbeat_time = time.time()
            self.error_message = None
            self.stop_event.clear()

            if run_in_background:
                self.worker_thread = threading.Thread(
                    target=self._worker_loop,
                    name=f"Worker-{self.instance_id}",
                    daemon=True,
                )
                self.worker_thread.start()
            return True

    def start_routine(
        self,
        routine_name: str,
        pipelines: List[str],
        variables: Optional[Dict[str, Any]] = None,
        plugin_cls: Optional[Type[BaseGamePlugin]] = None,
        plugin_id: str = "mhxy_mobile",
        stop_on_failure: bool = True,
        max_anti_bot_fails: int = 2,
        retry_pipeline_times: int = 1,
        run_in_background: bool = True,
    ) -> bool:
        """Start an ordered routine task chain on this instance."""
        with self._state_lock:
            if self.status == InstanceStatus.BUSY:
                logger.warning(f"Instance [{self.instance_id}] is already BUSY.")
                return False

            if not self.device or not self.device.is_connected():
                if not self.connect():
                    return False

            if plugin_cls is not None:
                self.plugin = plugin_cls(device=self.device)
            else:
                self.plugin = GamePluginRegistry.create(plugin_id, device=self.device)
            if variables:
                for k, v in variables.items():
                    self.plugin.context.variables[k] = v

            config = RoutineConfig(
                name=routine_name,
                pipelines=pipelines,
                stop_on_failure=stop_on_failure,
                max_anti_bot_fails=max_anti_bot_fails,
                retry_pipeline_times=retry_pipeline_times,
            )
            self.routine_executor = TaskRoutineExecutor(plugin=self.plugin, config=config)
            self.routine_executor.start()

            self.pipeline_name = None
            self.is_routine = True
            self.status = InstanceStatus.BUSY
            self.pipeline_status = PipelineStatus.RUNNING
            self.start_time = time.time()
            self.last_heartbeat_time = time.time()
            self.error_message = None
            self.stop_event.clear()

            if run_in_background:
                self.worker_thread = threading.Thread(
                    target=self._worker_loop,
                    name=f"Worker-{self.instance_id}",
                    daemon=True,
                )
                self.worker_thread.start()
            return True

    def tick(self) -> Any:
        """Perform a single step tick with granular lock separation."""
        with self._exec_lock:
            with self._state_lock:
                if not self.plugin or self.status != InstanceStatus.BUSY:
                    return None
                self.last_heartbeat_time = time.time()
                is_routine = self.is_routine
                routine_exec = self.routine_executor
                p_name = self.pipeline_name
                plugin = self.plugin

            # Heavy perception/action execution happens outside state lock
            try:
                if is_routine and routine_exec:
                    r_status = routine_exec.tick()
                    with self._state_lock:
                        self.last_tick_time = time.time()
                        if r_status in (
                            RoutineStatus.COMPLETED,
                            RoutineStatus.FAILED,
                            RoutineStatus.CIRCUIT_BROKEN,
                            RoutineStatus.STOPPED,
                        ):
                            self.status = InstanceStatus.IDLE
                            self.completed_cycles += 1
                            if r_status == RoutineStatus.COMPLETED:
                                self.pipeline_status = PipelineStatus.COMPLETED
                            else:
                                self.pipeline_status = PipelineStatus.FAILED
                                self.error_message = routine_exec.error_message
                    return r_status
                elif p_name:
                    p_status = plugin.run_pipeline_step(p_name)
                    with self._state_lock:
                        self.pipeline_status = p_status
                        self.last_tick_time = time.time()
                        if p_status in (
                            PipelineStatus.COMPLETED,
                            PipelineStatus.FAILED,
                            PipelineStatus.TIMEOUT,
                        ):
                            self.status = InstanceStatus.IDLE
                            self.completed_cycles += 1
                    return p_status
            except Exception as e:
                logger.error(f"Instance [{self.instance_id}] tick failed: {e}")
                with self._state_lock:
                    self.status = InstanceStatus.ERROR
                    self.pipeline_status = PipelineStatus.FAILED
                    self.error_message = str(e)
                return PipelineStatus.FAILED

    def stop(self) -> None:
        """Stop background execution immediately."""
        with self._state_lock:
            self.stop_event.set()
            if self.routine_executor:
                self.routine_executor.stop()
            if self.worker_thread and self.worker_thread.is_alive():
                self.worker_thread.join(timeout=1.0)
                self.worker_thread = None
            if self.status == InstanceStatus.BUSY:
                self.status = InstanceStatus.IDLE
            self.pipeline_status = PipelineStatus.IDLE

    def _worker_loop(self) -> None:
        """Background thread executing ticks until stopped or completed."""
        logger.info(f"Worker thread started for instance [{self.instance_id}].")
        try:
            while not self.stop_event.is_set() and self.status == InstanceStatus.BUSY:
                res = self.tick()
                if self.status != InstanceStatus.BUSY:
                    break
                self.stop_event.wait(0.2)
        except Exception as e:
            logger.error(f"Worker thread [{self.instance_id}] died unexpectedly: {e}")
            with self._state_lock:
                self.status = InstanceStatus.ERROR
                self.error_message = str(e)
        finally:
            with self._state_lock:
                if self.status == InstanceStatus.BUSY:
                    self.status = InstanceStatus.IDLE
            logger.info(f"Worker thread for instance [{self.instance_id}] exited.")

    def screencap(self, raw: bool = False) -> bytes:
        """Capture screenshot frame from this instance's device without blocking health inquiries."""
        with self._state_lock:
            dev = self.device
            connected = dev.is_connected() if dev else False

        if not dev or not connected:
            if not self.connect():
                raise RuntimeError(f"Device for instance [{self.instance_id}] failed to connect.")
            with self._state_lock:
                dev = self.device

        # Capture frame outside state lock
        data = dev.screencap()
        with self._state_lock:
            self.last_heartbeat_time = time.time()
        return data

    def get_health(self) -> Dict[str, Any]:
        """Return diagnostic health information for this instance instantaneously (<0.1ms)."""
        with self._state_lock:
            active_pipeline = self.pipeline_name
            if self.is_routine and self.routine_executor:
                active_pipeline = self.routine_executor.current_pipeline_name

            routine_prog = self.routine_executor.get_progress() if self.routine_executor else None

            return {
                "instance_id": self.instance_id,
                "name": self.name,
                "device_type": self.device_type,
                "serial": self.serial,
                "status": self.status.value,
                "pipeline_status": self.pipeline_status.value,
                "is_connected": self.device.is_connected() if self.device else False,
                "team_id": self.team_id,
                "team_role": self.team_role.value,
                "assigned_account_id": self.assigned_account_id,
                "assigned_proxy_id": self.assigned_proxy_id,
                "active_pipeline": active_pipeline,
                "uptime_sec": int(time.time() - self.start_time) if self.status == InstanceStatus.BUSY else 0,
                "last_heartbeat_ago": round(time.time() - self.last_heartbeat_time, 2),
                "completed_cycles": self.completed_cycles,
                "routine_progress": routine_prog,
                "error_message": self.error_message,
            }


class TeamTopology:
    """
    Defines a cooperative 5-account team topology:
    1 Leader + up to 4 Members (max 5 accounts).
    """

    def __init__(
        self,
        team_id: str,
        leader_instance_id: Optional[str] = None,
        member_instance_ids: Optional[List[str]] = None,
        target_activity: str = "team_zhuogui",
    ) -> None:
        self.team_id = team_id
        self.leader_instance_id = leader_instance_id
        self.member_instance_ids: List[str] = member_instance_ids or []
        self.target_activity = target_activity
        self.created_at = time.time()

    def is_full(self) -> bool:
        """A full team consists of 1 leader and 4 members (5 total)."""
        return bool(self.leader_instance_id) and len(self.member_instance_ids) == 4

    def all_instance_ids(self) -> List[str]:
        ids = []
        if self.leader_instance_id:
            ids.append(self.leader_instance_id)
        ids.extend(self.member_instance_ids)
        return ids

    def add_member(self, instance_id: str) -> bool:
        """Add a member instance to team (max 4 members)."""
        if instance_id == self.leader_instance_id:
            return False
        if instance_id in self.member_instance_ids:
            return True
        if len(self.member_instance_ids) >= 4:
            logger.warning(f"Team [{self.team_id}] members full (max 4).")
            return False
        self.member_instance_ids.append(instance_id)
        return True

    def remove_member(self, instance_id: str) -> bool:
        if instance_id in self.member_instance_ids:
            self.member_instance_ids.remove(instance_id)
            return True
        return False

    def set_leader(self, instance_id: str) -> None:
        if instance_id in self.member_instance_ids:
            self.member_instance_ids.remove(instance_id)
        self.leader_instance_id = instance_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "team_id": self.team_id,
            "leader_instance_id": self.leader_instance_id,
            "member_instance_ids": list(self.member_instance_ids),
            "target_activity": self.target_activity,
            "total_count": len(self.all_instance_ids()),
            "is_full": self.is_full(),
        }


class InstancePool:
    """
    Thread-safe Central Registry & Dispatcher for multi-device instances.
    Coordinates device creation, allocation, team assembly, and lifecycle.
    """

    _instance: Optional[InstancePool] = None

    def __init__(self) -> None:
        self._instances: Dict[str, DeviceInstance] = {}
        self._teams: Dict[str, TeamTopology] = {}
        self._lock = threading.RLock()

    @classmethod
    def get_pool(cls) -> InstancePool:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_instance(
        self,
        instance_id: str,
        device_type: str = "auto",
        serial: Optional[str] = None,
        name: Optional[str] = None,
        resolution: Tuple[int, int] = (1280, 720),
    ) -> DeviceInstance:
        """Register or retrieve an existing device instance."""
        with self._lock:
            if instance_id in self._instances:
                logger.info(f"Instance [{instance_id}] already registered.")
                return self._instances[instance_id]

            inst = DeviceInstance(
                instance_id=instance_id,
                device_type=device_type,
                serial=serial,
                name=name,
                resolution=resolution,
            )
            self._instances[instance_id] = inst
            logger.info(f"Registered instance [{instance_id}] (type={device_type}, serial={serial}).")
            return inst

    def unregister_instance(self, instance_id: str) -> bool:
        """Unregister an instance, stopping its tasks and removing it from teams."""
        with self._lock:
            inst = self._instances.get(instance_id)
            if not inst:
                return False

            inst.stop()
            inst.disconnect()

            # Remove from any team
            if inst.team_id and inst.team_id in self._teams:
                team = self._teams[inst.team_id]
                if team.leader_instance_id == instance_id:
                    team.leader_instance_id = None
                team.remove_member(instance_id)

            del self._instances[instance_id]
            logger.info(f"Unregistered instance [{instance_id}].")
            return True

    def get_instance(self, instance_id: str) -> Optional[DeviceInstance]:
        with self._lock:
            return self._instances.get(instance_id)

    def list_instances(self, status: Optional[InstanceStatus] = None) -> List[DeviceInstance]:
        with self._lock:
            if status is None:
                return list(self._instances.values())
            return [inst for inst in self._instances.values() if inst.status == status]

    # Alias for convenience
    get_instances = list_instances

    def allocate_instance(self, preferred_id: Optional[str] = None) -> Optional[DeviceInstance]:
        """Find and claim an available IDLE instance."""
        with self._lock:
            if preferred_id:
                inst = self._instances.get(preferred_id)
                if inst and inst.status == InstanceStatus.IDLE:
                    return inst
                return None

            for inst in self._instances.values():
                if inst.status == InstanceStatus.IDLE:
                    return inst
            return None

    def release_instance(self, instance_id: str) -> None:
        """Release an instance back to IDLE status."""
        with self._lock:
            inst = self._instances.get(instance_id)
            if inst:
                inst.stop()
                inst.status = InstanceStatus.IDLE

    # --- Team Topology Management ---

    def create_team(
        self,
        team_id: str,
        leader_id: str,
        member_ids: Optional[List[str]] = None,
        target_activity: str = "team_zhuogui",
    ) -> TeamTopology:
        """Assemble a team and bind instances to roles."""
        with self._lock:
            if leader_id not in self._instances:
                raise ValueError(f"Leader instance [{leader_id}] not found in pool.")

            member_ids = member_ids or []
            if len(member_ids) > 4:
                raise ValueError(f"Cannot add more than 4 members to a team (attempted {len(member_ids)}).")

            for mid in member_ids:
                if mid not in self._instances:
                    raise ValueError(f"Member instance [{mid}] not found in pool.")

            team = TeamTopology(
                team_id=team_id,
                leader_instance_id=leader_id,
                member_instance_ids=list(member_ids),
                target_activity=target_activity,
            )
            self._teams[team_id] = team

            # Update instance states
            leader_inst = self._instances[leader_id]
            leader_inst.team_id = team_id
            leader_inst.team_role = TeamRole.LEADER

            for mid in member_ids:
                m_inst = self._instances[mid]
                m_inst.team_id = team_id
                m_inst.team_role = TeamRole.MEMBER

            logger.info(
                f"Created team [{team_id}]: Leader={leader_id}, Members={member_ids}, Activity={target_activity}"
            )
            return team

    def get_team(self, team_id: str) -> Optional[TeamTopology]:
        with self._lock:
            return self._teams.get(team_id)

    def list_teams(self) -> List[TeamTopology]:
        with self._lock:
            return list(self._teams.values())

    def dissolve_team(self, team_id: str) -> bool:
        """Dissolve a team and reset members to solo role."""
        with self._lock:
            team = self._teams.get(team_id)
            if not team:
                return False

            for inst_id in team.all_instance_ids():
                inst = self._instances.get(inst_id)
                if inst:
                    inst.team_id = None
                    inst.team_role = TeamRole.SOLO

            del self._teams[team_id]
            logger.info(f"Dissolved team [{team_id}].")
            return True

    def start_team_routine(
        self,
        team_id: str,
        leader_pipelines: List[str],
        member_pipelines: List[str],
        leader_vars: Optional[Dict[str, Any]] = None,
        member_vars: Optional[Dict[str, Any]] = None,
        run_in_background: bool = True,
    ) -> Dict[str, bool]:
        """
        Concurrently start the routine on all team members.
        Leader receives leader_pipelines + leader_vars (team_role="leader").
        Members receive member_pipelines + member_vars (team_role="member").
        """
        with self._lock:
            team = self._teams.get(team_id)
            if not team:
                raise ValueError(f"Team [{team_id}] not found.")

            results: Dict[str, bool] = {}

            # Prepare leader vars
            l_vars = dict(leader_vars or {})
            l_vars["team_role"] = "leader"
            l_vars["team_id"] = team_id

            if team.leader_instance_id:
                leader_inst = self._instances.get(team.leader_instance_id)
                if leader_inst:
                    results[team.leader_instance_id] = leader_inst.start_routine(
                        routine_name=f"{team_id}_leader_routine",
                        pipelines=leader_pipelines,
                        variables=l_vars,
                        run_in_background=run_in_background,
                    )

            # Prepare member vars
            m_vars = dict(member_vars or {})
            m_vars["team_role"] = "member"
            m_vars["team_id"] = team_id

            for mid in team.member_instance_ids:
                m_inst = self._instances.get(mid)
                if m_inst:
                    results[mid] = m_inst.start_routine(
                        routine_name=f"{team_id}_member_{mid}_routine",
                        pipelines=member_pipelines,
                        variables=m_vars,
                        run_in_background=run_in_background,
                    )

            return results

    def stop_team(self, team_id: str) -> Dict[str, bool]:
        """Stop all running tasks in a team."""
        with self._lock:
            team = self._teams.get(team_id)
            if not team:
                return {}

            results: Dict[str, bool] = {}
            for inst_id in team.all_instance_ids():
                inst = self._instances.get(inst_id)
                if inst:
                    inst.stop()
                    results[inst_id] = True
            return results

    def stop_all(self) -> None:
        """Stop all instances across the entire pool."""
        with self._lock:
            for inst in self._instances.values():
                inst.stop()
            logger.info("Stopped all instances in cluster pool.")

    def get_cluster_stats(self) -> Dict[str, Any]:
        """Summary statistics of the cluster."""
        with self._lock:
            total = len(self._instances)
            busy = sum(1 for i in self._instances.values() if i.status == InstanceStatus.BUSY)
            idle = sum(1 for i in self._instances.values() if i.status == InstanceStatus.IDLE)
            error = sum(1 for i in self._instances.values() if i.status == InstanceStatus.ERROR)
            disconnected = sum(1 for i in self._instances.values() if i.status == InstanceStatus.DISCONNECTED)

            return {
                "total_instances": total,
                "busy_instances": busy,
                "idle_instances": idle,
                "error_instances": error,
                "disconnected_instances": disconnected,
                "total_teams": len(self._teams),
            }
