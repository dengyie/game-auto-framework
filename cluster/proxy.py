"""
Dedicated Socks5 / HTTP Proxy Manager & Anti-Bot Quota Isolation Controller.
Enforces the anti-bot quota rule (<= 5 game accounts / 1 team per public egress IP)
to prevent studio account aggregation bans.
"""

from __future__ import annotations

import socket
import threading
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field
from loguru import logger


class ProxyQuotaExceededError(Exception):
    """Raised when an operation would exceed the maximum instance quota (<=5) per proxy."""
    pass


class ProxyProtocol(str, Enum):
    SOCKS5 = "socks5"
    HTTP = "http"
    HTTPS = "https"


class ProxyStatus(str, Enum):
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


class ProxyConfig(BaseModel):
    """Configuration and state for a single dedicated proxy."""
    proxy_id: str
    protocol: ProxyProtocol = ProxyProtocol.SOCKS5
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    max_instances: int = Field(
        default=5,
        description="Strict anti-bot quota ceiling: max 1 team (<=5 accounts) per public IP",
    )
    active_instance_ids: Set[str] = Field(default_factory=set)
    status: ProxyStatus = ProxyStatus.ACTIVE
    last_checked_at: float = 0.0
    latency_ms: float = 0.0
    error_message: Optional[str] = None

    @property
    def url(self) -> str:
        """Formatted URL representation."""
        auth = f"{self.username}:{self.password}@" if self.username and self.password else ""
        return f"{self.protocol.value}://{auth}{self.host}:{self.port}"

    @property
    def available_slots(self) -> int:
        return max(0, self.max_instances - len(self.active_instance_ids))

    @property
    def is_available(self) -> bool:
        return self.status == ProxyStatus.ACTIVE and self.available_slots > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proxy_id": self.proxy_id,
            "protocol": self.protocol.value,
            "host": self.host,
            "port": self.port,
            "has_auth": bool(self.username and self.password),
            "max_instances": self.max_instances,
            "active_count": len(self.active_instance_ids),
            "active_instance_ids": list(self.active_instance_ids),
            "available_slots": self.available_slots,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "error_message": self.error_message,
        }


class ProxyManager:
    """
    Thread-safe manager for dedicated proxy pooling, allocation, and quota enforcement.
    """

    _instance: Optional[ProxyManager] = None

    def __init__(self) -> None:
        self._proxies: Dict[str, ProxyConfig] = {}
        self._instance_to_proxy: Dict[str, str] = {}
        self._lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> ProxyManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_proxy(
        self,
        proxy_id: str,
        host: str,
        port: int,
        protocol: str = "socks5",
        username: Optional[str] = None,
        password: Optional[str] = None,
        max_instances: int = 5,
    ) -> ProxyConfig:
        """Register a new proxy endpoint into the pool."""
        with self._lock:
            # Enforce hard ceiling of <= 5 per proxy
            max_inst = min(max_instances, 5)
            proto = ProxyProtocol(protocol.lower())
            config = ProxyConfig(
                proxy_id=proxy_id,
                protocol=proto,
                host=host,
                port=port,
                username=username,
                password=password,
                max_instances=max_inst,
            )
            self._proxies[proxy_id] = config
            logger.info(
                f"Registered proxy [{proxy_id}] ({config.url}) with max_quota={config.max_instances}."
            )
            return config

    def unregister_proxy(self, proxy_id: str) -> bool:
        """Remove a proxy from the pool and unbind all assigned instances."""
        with self._lock:
            proxy = self._proxies.get(proxy_id)
            if not proxy:
                return False

            for inst_id in list(proxy.active_instance_ids):
                self._instance_to_proxy.pop(inst_id, None)

            del self._proxies[proxy_id]
            logger.info(f"Unregistered proxy [{proxy_id}].")
            return True

    def get_proxy(self, proxy_id: str) -> Optional[ProxyConfig]:
        with self._lock:
            return self._proxies.get(proxy_id)

    def list_proxies(self, status: Optional[ProxyStatus] = None) -> List[ProxyConfig]:
        with self._lock:
            if status is None:
                return list(self._proxies.values())
            return [p for p in self._proxies.values() if p.status == status]

    def bind_instance_to_proxy(self, instance_id: str, proxy_id: str) -> bool:
        """
        Bind a device instance to a dedicated proxy.
        Enforces the quota rule: strictly <= 5 instances per proxy.
        """
        with self._lock:
            proxy = self._proxies.get(proxy_id)
            if not proxy:
                raise ValueError(f"Proxy [{proxy_id}] does not exist.")

            # If already bound to this proxy, succeed idempotently
            if instance_id in proxy.active_instance_ids:
                return True

            # If bound to another proxy, unbind from the previous one first
            old_proxy_id = self._instance_to_proxy.get(instance_id)
            if old_proxy_id and old_proxy_id in self._proxies:
                self._proxies[old_proxy_id].active_instance_ids.discard(instance_id)

            # Check quota rule
            if len(proxy.active_instance_ids) >= proxy.max_instances:
                raise ProxyQuotaExceededError(
                    f"Proxy [{proxy_id}] quota reached: {len(proxy.active_instance_ids)}/{proxy.max_instances}. "
                    f"Exceeding 5 instances per public IP violates anti-bot security rule."
                )

            proxy.active_instance_ids.add(instance_id)
            self._instance_to_proxy[instance_id] = proxy_id
            logger.info(
                f"Bound instance [{instance_id}] to proxy [{proxy_id}] "
                f"({len(proxy.active_instance_ids)}/{proxy.max_instances} used)."
            )
            return True

    def unbind_instance(self, instance_id: str) -> bool:
        """Unbind an instance from its proxy, releasing quota."""
        with self._lock:
            proxy_id = self._instance_to_proxy.pop(instance_id, None)
            if not proxy_id:
                return False

            proxy = self._proxies.get(proxy_id)
            if proxy:
                proxy.active_instance_ids.discard(instance_id)
                logger.info(
                    f"Unbound instance [{instance_id}] from proxy [{proxy_id}]. "
                    f"Remaining slots: {proxy.available_slots}."
                )
            return True

    def get_proxy_for_instance(self, instance_id: str) -> Optional[ProxyConfig]:
        with self._lock:
            proxy_id = self._instance_to_proxy.get(instance_id)
            if proxy_id:
                return self._proxies.get(proxy_id)
            return None

    def get_available_proxy(self) -> Optional[ProxyConfig]:
        """Find an active proxy with remaining quota slots, prioritizing lowest load."""
        with self._lock:
            candidates = [p for p in self._proxies.values() if p.is_available]
            if not candidates:
                return None
            # Sort by currently used count ascending (load balancing)
            candidates.sort(key=lambda p: len(p.active_instance_ids))
            return candidates[0]

    def check_proxy_health(self, proxy_id: str, timeout: float = 2.0) -> bool:
        """
        Test proxy socket reachability and calculate latency.
        """
        with self._lock:
            proxy = self._proxies.get(proxy_id)
            if not proxy:
                return False

            t0 = time.time()
            try:
                with socket.create_connection((proxy.host, proxy.port), timeout=timeout):
                    latency = (time.time() - t0) * 1000.0
                    proxy.latency_ms = latency
                    proxy.last_checked_at = time.time()
                    proxy.status = ProxyStatus.ACTIVE
                    proxy.error_message = None
                    return True
            except Exception as e:
                proxy.last_checked_at = time.time()
                proxy.status = ProxyStatus.ERROR
                proxy.error_message = str(e)
                proxy.latency_ms = -1.0
                logger.warning(f"Proxy [{proxy_id}] health check failed: {e}")
                return False

    def check_all_proxies(self, timeout: float = 2.0) -> Dict[str, bool]:
        """Run health check across all proxies."""
        with self._lock:
            results = {}
            for pid in list(self._proxies.keys()):
                results[pid] = self.check_proxy_health(pid, timeout=timeout)
            return results

    def get_proxy_stats(self) -> Dict[str, Any]:
        """Summary of proxy pool capacity and allocations."""
        with self._lock:
            total = len(self._proxies)
            active = sum(1 for p in self._proxies.values() if p.status == ProxyStatus.ACTIVE)
            total_slots = sum(p.max_instances for p in self._proxies.values())
            used_slots = len(self._instance_to_proxy)
            free_slots = total_slots - used_slots

            return {
                "total_proxies": total,
                "active_proxies": active,
                "total_slots": total_slots,
                "used_slots": used_slots,
                "free_slots": free_slots,
                "bound_instances_count": len(self._instance_to_proxy),
            }
