"""
Cluster Management, Multi-Instance Scheduling, Dedicated Proxy Isolation,
Account Matrix, and Self-Healing Supervisor for Game Auto Framework.
"""

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

__all__ = [
    "DeviceInstance",
    "InstancePool",
    "InstanceStatus",
    "TeamRole",
    "TeamTopology",
    "ProxyConfig",
    "ProxyManager",
    "ProxyProtocol",
    "ProxyQuotaExceededError",
    "ProxyStatus",
    "AccountConfig",
    "AccountMatrix",
    "AccountStatus",
    "ClusterSupervisor",
    "SupervisorConfig",
]
