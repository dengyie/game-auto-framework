"""
Account Matrix, Asset Accumulation Tracker & Humanized Work-Rest Scheduler.
Enforces realistic human fatigue intervals (2.5~4h online -> 20~40m offline rest),
and maintains gold/silver earnings across multi-account farming operations.
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import threading
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from loguru import logger


class AccountStatus(str, Enum):
    IDLE = "idle"
    IN_USE = "in_use"
    RESTING = "resting"
    BANNED = "banned"
    COMPLETED = "completed"


class AccountConfig(BaseModel):
    """Detailed game account metadata, earnings tracker, and work-rest state."""
    account_id: str
    username: str
    password: str
    server_name: str = "东海湾"
    role_name: Optional[str] = None
    level: int = 69
    sect: str = "大唐官府"
    team_role_preference: str = "solo"  # leader, member, solo
    status: AccountStatus = AccountStatus.IDLE

    # Earnings & In-game Resources
    gold_coins: int = 0
    silver_coins: int = 0
    vitality: int = 500
    daily_active_points: int = 0

    # Physiological Work-Rest Modeling
    accumulated_online_seconds: float = 0.0
    session_start_time: float = 0.0
    max_continuous_online_seconds: float = Field(
        default_factory=lambda: random.uniform(9000.0, 14400.0),  # 2.5 ~ 4.0 hours
        description="Session fatigue threshold (seconds)",
    )
    rest_duration_seconds: float = Field(
        default_factory=lambda: random.uniform(1200.0, 2400.0),   # 20 ~ 40 minutes
        description="Required rest duration before next session",
    )
    resting_until: float = 0.0

    # Cluster Placement
    bound_instance_id: Optional[str] = None
    bound_proxy_id: Optional[str] = None

    def add_income(self, gold: int = 0, silver: int = 0, active_points: int = 0) -> None:
        """Accumulate farming earnings and activity points."""
        self.gold_coins += max(0, gold)
        self.silver_coins += max(0, silver)
        self.daily_active_points = min(100, self.daily_active_points + max(0, active_points))

    def consume_vitality(self, amount: int) -> int:
        """Deduct vitality for crafting/working; returns actually consumed vitality."""
        consumed = min(self.vitality, max(0, amount))
        self.vitality -= consumed
        return consumed

    def start_session(self, instance_id: str, proxy_id: Optional[str] = None) -> None:
        """Mark account as online and bind to instance/proxy."""
        self.status = AccountStatus.IN_USE
        self.bound_instance_id = instance_id
        self.bound_proxy_id = proxy_id
        self.session_start_time = time.time()

    def end_session(self) -> None:
        """Mark account session as ended and accumulate online time."""
        if self.session_start_time > 0:
            elapsed = time.time() - self.session_start_time
            self.accumulated_online_seconds += elapsed
            self.session_start_time = 0.0
        self.bound_instance_id = None
        self.bound_proxy_id = None
        if self.status == AccountStatus.IN_USE:
            self.status = AccountStatus.IDLE

    def is_fatigued(self) -> bool:
        """Check if account exceeded continuous online limit."""
        current_session = 0.0
        if self.session_start_time > 0:
            current_session = time.time() - self.session_start_time
        return (self.accumulated_online_seconds + current_session) >= self.max_continuous_online_seconds

    def trigger_rest(self) -> None:
        """Place account into resting state for simulated physiological rest."""
        self.end_session()
        self.status = AccountStatus.RESTING
        self.resting_until = time.time() + self.rest_duration_seconds
        logger.info(
            f"Account [{self.account_id}] entered rest period for {int(self.rest_duration_seconds)}s."
        )

    def check_rest_recovery(self) -> bool:
        """Check if resting time has concluded and reset fatigue counters."""
        if self.status != AccountStatus.RESTING:
            return False
        if time.time() >= self.resting_until:
            self.status = AccountStatus.IDLE
            self.accumulated_online_seconds = 0.0
            self.resting_until = 0.0
            # Reset next randomized work-rest intervals
            self.max_continuous_online_seconds = random.uniform(9000.0, 14400.0)
            self.rest_duration_seconds = random.uniform(1200.0, 2400.0)
            logger.info(f"Account [{self.account_id}] completed rest; status returned to IDLE.")
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "username": self.username,
            "server_name": self.server_name,
            "role_name": self.role_name,
            "level": self.level,
            "sect": self.sect,
            "team_role_preference": self.team_role_preference,
            "status": self.status.value,
            "gold_coins": self.gold_coins,
            "silver_coins": self.silver_coins,
            "vitality": self.vitality,
            "daily_active_points": self.daily_active_points,
            "accumulated_online_hours": round(self.accumulated_online_seconds / 3600.0, 2),
            "resting_remaining_sec": max(0, int(self.resting_until - time.time())) if self.status == AccountStatus.RESTING else 0,
            "bound_instance_id": self.bound_instance_id,
            "bound_proxy_id": self.bound_proxy_id,
        }


class AccountMatrix:
    """
    Fleet-wide game account repository and asset tracker.
    Coordinates account rotation, assignment, and income records.
    """

    _instance: Optional[AccountMatrix] = None

    def __init__(self) -> None:
        self._accounts: Dict[str, AccountConfig] = {}
        self._lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> AccountMatrix:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_account(self, config: AccountConfig) -> AccountConfig:
        """Register a single account into matrix."""
        with self._lock:
            self._accounts[config.account_id] = config
            logger.info(
                f"Registered account [{config.account_id}] ({config.username} / {config.role_name or 'N/A'}) "
                f"in server [{config.server_name}]."
            )
            return config

    def batch_register(self, configs: List[AccountConfig]) -> int:
        """Register multiple accounts."""
        with self._lock:
            for cfg in configs:
                self._accounts[cfg.account_id] = cfg
            logger.info(f"Batch registered {len(configs)} accounts into matrix.")
            return len(configs)

    def get_account(self, account_id: str) -> Optional[AccountConfig]:
        with self._lock:
            return self._accounts.get(account_id)

    def list_accounts(
        self,
        status: Optional[AccountStatus] = None,
        server_name: Optional[str] = None,
    ) -> List[AccountConfig]:
        """List accounts filtered by status and/or server."""
        with self._lock:
            # Check for rest recoveries first
            for acc in self._accounts.values():
                acc.check_rest_recovery()

            res = list(self._accounts.values())
            if status is not None:
                res = [a for a in res if a.status == status]
            if server_name is not None:
                res = [a for a in res if a.server_name == server_name]
            return res

    def allocate_account(
        self,
        role_preference: Optional[str] = None,
        sect: Optional[str] = None,
        server_name: Optional[str] = None,
    ) -> Optional[AccountConfig]:
        """
        Find and allocate an IDLE, non-fatigued account matching preferences.
        """
        with self._lock:
            # Refresh rest status
            for acc in self._accounts.values():
                acc.check_rest_recovery()

            candidates = [
                a for a in self._accounts.values()
                if a.status == AccountStatus.IDLE and not a.is_fatigued()
            ]

            if server_name:
                candidates = [a for a in candidates if a.server_name == server_name]
            if role_preference:
                pref_matches = [a for a in candidates if a.team_role_preference == role_preference]
                if pref_matches:
                    candidates = pref_matches
            if sect:
                sect_matches = [a for a in candidates if a.sect == sect]
                if sect_matches:
                    candidates = sect_matches

            if not candidates:
                return None

            # Prioritize account with lowest accumulated online time
            candidates.sort(key=lambda a: a.accumulated_online_seconds)
            return candidates[0]

    def release_account(self, account_id: str, reason: str = "finished") -> bool:
        """End session on account and release back to matrix."""
        with self._lock:
            acc = self._accounts.get(account_id)
            if not acc:
                return False

            acc.end_session()
            if acc.is_fatigued():
                acc.trigger_rest()
            else:
                acc.status = AccountStatus.IDLE
            logger.info(f"Released account [{account_id}] (reason: {reason}, status: {acc.status.value}).")
            return True

    def record_income(
        self,
        account_id: str,
        gold: int = 0,
        silver: int = 0,
        active_points: int = 0,
    ) -> None:
        """Add income to a specific account."""
        with self._lock:
            acc = self._accounts.get(account_id)
            if acc:
                acc.add_income(gold=gold, silver=silver, active_points=active_points)

    def rotate_fatigued_accounts(self) -> List[Tuple[str, Optional[str]]]:
        """
        Scan all active accounts. For each fatigued account:
        1. Place it into resting state.
        2. Attempt to allocate an idle replacement account.
        Returns list of (fatigued_id, replacement_id) tuples.
        """
        with self._lock:
            rotations: List[Tuple[str, Optional[str]]] = []
            active_accounts = [a for a in self._accounts.values() if a.status == AccountStatus.IN_USE]

            for acc in active_accounts:
                if acc.is_fatigued():
                    inst_id = acc.bound_instance_id
                    proxy_id = acc.bound_proxy_id
                    acc_id = acc.account_id

                    # Trigger rest
                    acc.trigger_rest()

                    # Find replacement
                    replacement = self.allocate_account(
                        role_preference=acc.team_role_preference,
                        sect=acc.sect,
                        server_name=acc.server_name,
                    )
                    rep_id = None
                    if replacement and inst_id:
                        replacement.start_session(instance_id=inst_id, proxy_id=proxy_id)
                        rep_id = replacement.account_id
                        logger.info(
                            f"Rotated fatigued account [{acc_id}] -> replacement [{rep_id}] on instance [{inst_id}]."
                        )
                    else:
                        logger.warning(
                            f"Account [{acc_id}] fatigued on instance [{inst_id}], but no replacement available."
                        )

                    rotations.append((acc_id, rep_id))

            return rotations

    def get_total_assets(self) -> Dict[str, Any]:
        """Aggregate total revenue and assets across all registered accounts."""
        with self._lock:
            total_gold = sum(a.gold_coins for a in self._accounts.values())
            total_silver = sum(a.silver_coins for a in self._accounts.values())
            total_vitality = sum(a.vitality for a in self._accounts.values())
            total_active = sum(a.daily_active_points for a in self._accounts.values())

            return {
                "total_accounts": len(self._accounts),
                "in_use_accounts": sum(1 for a in self._accounts.values() if a.status == AccountStatus.IN_USE),
                "idle_accounts": sum(1 for a in self._accounts.values() if a.status == AccountStatus.IDLE),
                "resting_accounts": sum(1 for a in self._accounts.values() if a.status == AccountStatus.RESTING),
                "total_gold_coins": total_gold,
                "total_silver_coins": total_silver,
                "total_vitality": total_vitality,
                "total_daily_active_points": total_active,
            }

    def export_to_dict(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [a.to_dict() for a in self._accounts.values()]

    def save_to_json(self, file_path: str) -> bool:
        """Persist all registered account data to JSON file."""
        with self._lock:
            try:
                data = [a.model_dump() for a in self._accounts.values()]
                path = Path(file_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info(f"Saved {len(data)} accounts to {file_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to save accounts to {file_path}: {e}")
                return False

    def load_from_json(self, file_path: str) -> int:
        """Load and register account configurations from JSON file."""
        with self._lock:
            path = Path(file_path)
            if not path.exists():
                logger.warning(f"Account file {file_path} does not exist.")
                return 0
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                loaded = 0
                for item in raw_data:
                    cfg = AccountConfig(**item)
                    self._accounts[cfg.account_id] = cfg
                    loaded += 1
                logger.info(f"Loaded {loaded} accounts from {file_path}")
                return loaded
            except Exception as e:
                logger.error(f"Failed to load accounts from {file_path}: {e}")
                return 0
