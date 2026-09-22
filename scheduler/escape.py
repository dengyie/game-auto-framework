"""
Three-Tier Self-Healing Escape Sequence.
Inspired by Alas deadlock mitigation and automated recovery patterns.
"""

from __future__ import annotations
import time
from enum import IntEnum
from typing import Callable, Optional
from loguru import logger


class EscapeLevel(IntEnum):
    LEVEL_1_MINOR = 1   # Quick back-off: ESC / Close dialogs / Click return
    LEVEL_2_MEDIUM = 2  # Safe teleport: Return to main hub / reset quest tracker
    LEVEL_3_MAJOR = 3   # Hard restart: Terminate process / reboot emulator / re-login


class SelfHealingEscapeManager:
    """Manages progressive escalation of recovery actions when execution is stalled."""

    def __init__(
        self,
        stall_threshold_sec: float = 30.0,
        max_level_1_attempts: int = 3,
        on_minor_escape: Optional[Callable[[], None]] = None,
        on_medium_escape: Optional[Callable[[], None]] = None,
        on_major_escape: Optional[Callable[[], None]] = None,
    ) -> None:
        self.stall_threshold_sec = stall_threshold_sec
        self.max_level_1_attempts = max_level_1_attempts
        self.level_1_count = 0
        self.last_progress_time = time.time()

        self._on_minor = on_minor_escape or self._default_minor
        self._on_medium = on_medium_escape or self._default_medium
        self._on_major = on_major_escape or self._default_major

    def record_progress(self) -> None:
        """Called whenever a valid pipeline step or recognition succeeds."""
        self.last_progress_time = time.time()
        self.level_1_count = 0

    def check_and_heal(self) -> Optional[EscapeLevel]:
        """Check if execution is stalled and trigger the appropriate recovery tier."""
        stalled_time = time.time() - self.last_progress_time
        if stalled_time < self.stall_threshold_sec:
            return None

        # Tier 1: Minor escape attempts
        if self.level_1_count < self.max_level_1_attempts:
            self.level_1_count += 1
            logger.warning(
                f"[Escape Tier 1] Stalled for {stalled_time:.1f}s. "
                f"Executing minor backoff attempt ({self.level_1_count}/{self.max_level_1_attempts})"
            )
            self._on_minor()
            self.last_progress_time = time.time()  # Give grace period
            return EscapeLevel.LEVEL_1_MINOR

        # Tier 2: Medium escape (e.g. Teleport to Chang'an)
        if stalled_time < self.stall_threshold_sec * 3:
            logger.warning(f"[Escape Tier 2] Tier 1 exhausted. Executing medium hub teleport recovery.")
            self._on_medium()
            self.last_progress_time = time.time()
            return EscapeLevel.LEVEL_2_MEDIUM

        # Tier 3: Major hard restart
        logger.critical(f"[Escape Tier 3] Persistent stall for {stalled_time:.1f}s. Triggering process hard restart.")
        self._on_major()
        self.record_progress()
        return EscapeLevel.LEVEL_3_MAJOR

    def _default_minor(self) -> None:
        logger.info("Executing default Minor Escape: Send ESC key x2, click Return button")

    def _default_medium(self) -> None:
        logger.info("Executing default Medium Escape: Teleport to Chang'an City, reopen main UI")

    def _default_major(self) -> None:
        logger.info("Executing default Major Escape: Kill and restart emulator process")
