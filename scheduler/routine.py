"""
Task Routine Chaining & Circuit Breaker Manager.
Orchestrates sequential execution of daily pipelines (e.g. shimen -> baotu -> yuntong),
with anti-bot circuit breaker, failure fallback policies, and progress tracking.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from loguru import logger

from plugins.base import BaseGamePlugin
from scheduler.dag import PipelineStatus


class RoutineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CIRCUIT_BROKEN = "circuit_broken"
    STOPPED = "stopped"


class RoutineConfig(BaseModel):
    name: str = Field(default="daily_routine", description="Routine name")
    pipelines: List[str] = Field(default_factory=list, description="Ordered list of pipeline names")
    stop_on_failure: bool = Field(default=True, description="Whether a failed pipeline halts the entire routine")
    max_anti_bot_fails: int = Field(default=2, description="Circuit breaker threshold for anti-bot failures")
    retry_pipeline_times: int = Field(default=1, description="Number of retries allowed for a failing pipeline")


class TaskRoutineExecutor:
    """Executes an ordered chain of automation pipelines."""

    def __init__(self, plugin: BaseGamePlugin, config: RoutineConfig) -> None:
        self.plugin = plugin
        self.config = config
        self.status = RoutineStatus.IDLE
        self.current_index: int = 0
        self.completed_pipelines: List[str] = []
        self.failed_pipelines: List[str] = []
        self.pipeline_retries: Dict[str, int] = {}
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.error_message: Optional[str] = None

        # Resolve pipeline aliases if necessary
        self._normalized_pipelines = self._normalize_pipeline_names(config.pipelines)

    def _normalize_pipeline_names(self, pipeline_names: List[str]) -> List[str]:
        """Resolve common shorthand names to actual pipeline names loaded in the plugin."""
        resolved = []
        available = set(self.plugin.pipelines.keys())
        for name in pipeline_names:
            if name in available:
                resolved.append(name)
            elif f"daily_{name}" in available:
                resolved.append(f"daily_{name}")
            else:
                # Keep as requested; will be validated on start
                resolved.append(name)
        return resolved

    @property
    def current_pipeline_name(self) -> Optional[str]:
        if 0 <= self.current_index < len(self._normalized_pipelines):
            return self._normalized_pipelines[self.current_index]
        return None

    def start(self) -> None:
        """Start the routine from the first pipeline."""
        if not self._normalized_pipelines:
            self.status = RoutineStatus.FAILED
            self.error_message = "No pipelines configured for routine"
            logger.error("Cannot start empty routine")
            return

        self.status = RoutineStatus.RUNNING
        self.current_index = 0
        self.completed_pipelines.clear()
        self.failed_pipelines.clear()
        self.pipeline_retries.clear()
        self.start_time = time.time()
        self.end_time = 0.0
        self.error_message = None

        # Reset anti-bot failure tracker in plugin context
        self.plugin.context.variables["anti_bot_failed_count"] = 0

        logger.info(
            f"Routine [{self.config.name}] started with {len(self._normalized_pipelines)} pipelines: "
            f"{self._normalized_pipelines}"
        )

    def stop(self) -> None:
        """Manually stop the routine."""
        self.status = RoutineStatus.STOPPED
        self.end_time = time.time()
        logger.info(f"Routine [{self.config.name}] stopped manually")

    def tick(self) -> RoutineStatus:
        """Execute one tick of the routine."""
        if self.status != RoutineStatus.RUNNING:
            return self.status

        # 1. Anti-Bot Circuit Breaker Check
        anti_bot_fails = self.plugin.context.variables.get("anti_bot_failed_count", 0)
        if anti_bot_fails >= self.config.max_anti_bot_fails:
            self.status = RoutineStatus.CIRCUIT_BROKEN
            self.end_time = time.time()
            self.error_message = (
                f"Anti-bot circuit breaker triggered: {anti_bot_fails} consecutive failures "
                f"(threshold={self.config.max_anti_bot_fails})"
            )
            logger.critical(self.error_message)
            return self.status

        # 2. Check if all pipelines finished
        if self.current_index >= len(self._normalized_pipelines):
            self.status = RoutineStatus.COMPLETED
            self.end_time = time.time()
            logger.info(
                f"Routine [{self.config.name}] completed successfully: "
                f"{len(self.completed_pipelines)}/{len(self._normalized_pipelines)} passed"
            )
            return self.status

        pipeline_name = self._normalized_pipelines[self.current_index]

        # 3. Verify pipeline exists
        if pipeline_name not in self.plugin.pipelines:
            self.failed_pipelines.append(pipeline_name)
            logger.error(f"Pipeline [{pipeline_name}] does not exist in plugin [{self.plugin.plugin_id}]")
            if self.config.stop_on_failure:
                self.status = RoutineStatus.FAILED
                self.end_time = time.time()
                self.error_message = f"Pipeline [{pipeline_name}] not found"
                return self.status
            else:
                self.current_index += 1
                return self.status

        # 4. Execute a single tick of the current pipeline
        step_status = self.plugin.run_pipeline_step(pipeline_name)

        if step_status == PipelineStatus.RUNNING:
            return self.status

        if step_status == PipelineStatus.COMPLETED:
            logger.info(f"Pipeline [{pipeline_name}] completed ({self.current_index + 1}/{len(self._normalized_pipelines)})")
            self.completed_pipelines.append(pipeline_name)
            self.current_index += 1

            if self.current_index >= len(self._normalized_pipelines):
                self.status = RoutineStatus.COMPLETED
                self.end_time = time.time()
                logger.info(f"All {len(self._normalized_pipelines)} pipelines in routine [{self.config.name}] finished!")

            return self.status

        if step_status in (PipelineStatus.FAILED, PipelineStatus.TIMEOUT):
            retries = self.pipeline_retries.get(pipeline_name, 0)
            if retries < self.config.retry_pipeline_times:
                self.pipeline_retries[pipeline_name] = retries + 1
                logger.warning(
                    f"Pipeline [{pipeline_name}] failed with [{step_status.value}]. "
                    f"Retrying ({retries + 1}/{self.config.retry_pipeline_times})..."
                )
                # Reset pipeline to IDLE to re-enter
                p = self.plugin.get_pipeline(pipeline_name)
                if p:
                    p.status = PipelineStatus.IDLE
                return self.status

            # Retries exhausted
            logger.error(f"Pipeline [{pipeline_name}] failed definitively with [{step_status.value}]")
            self.failed_pipelines.append(pipeline_name)

            if self.config.stop_on_failure:
                self.status = RoutineStatus.FAILED
                self.end_time = time.time()
                self.error_message = f"Pipeline [{pipeline_name}] failed ({step_status.value})"
                return self.status
            else:
                self.current_index += 1
                if self.current_index >= len(self._normalized_pipelines):
                    self.status = RoutineStatus.COMPLETED if not self.failed_pipelines else RoutineStatus.FAILED
                    self.end_time = time.time()
                return self.status

        return self.status

    def get_progress(self) -> Dict[str, Any]:
        """Return rich progress summary for API / monitoring."""
        total = len(self._normalized_pipelines)
        pct = 0.0
        if total > 0:
            pct = round((len(self.completed_pipelines) / total) * 100, 1)

        uptime = 0
        if self.start_time > 0:
            end = self.end_time if self.end_time > 0 else time.time()
            uptime = int(end - self.start_time)

        return {
            "routine_name": self.config.name,
            "status": self.status.value,
            "current_index": self.current_index,
            "current_pipeline": self.current_pipeline_name,
            "total_pipelines": total,
            "completed_pipelines": list(self.completed_pipelines),
            "failed_pipelines": list(self.failed_pipelines),
            "progress_percent": pct,
            "uptime_sec": uptime,
            "error_message": self.error_message,
        }
