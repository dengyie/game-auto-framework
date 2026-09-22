"""
Unified Input Driver Abstraction with Humanized Execution.
Supports Virtual/Mock (testing), ADB, and OS-level HID drivers.
"""

from __future__ import annotations
import abc
import random
import time
from typing import List, Optional, Tuple
from loguru import logger

from core.input.bezier import generate_bezier_trajectory, generate_gaussian_target


class BaseInputDriver(abc.ABC):
    """Abstract base class for all hardware/OS/ADB input drivers."""

    @abc.abstractmethod
    def move_to(self, x: int, y: int) -> None:
        """Instantly move cursor/pointer."""
        pass

    @abc.abstractmethod
    def mouse_down(self, x: int, y: int) -> None:
        """Press mouse left button or touch down."""
        pass

    @abc.abstractmethod
    def mouse_up(self, x: int, y: int) -> None:
        """Release mouse left button or touch up."""
        pass

    @abc.abstractmethod
    def key_down(self, key_code: str) -> None:
        """Press down a key."""
        pass

    @abc.abstractmethod
    def key_up(self, key_code: str) -> None:
        """Release a key."""
        pass


class VirtualInputDriver(BaseInputDriver):
    """In-memory virtual input driver for testing, simulation, and headless observation."""

    def __init__(self) -> None:
        self.cursor_pos = (0, 0)
        self.is_down = False
        self.event_log: List[str] = []

    def move_to(self, x: int, y: int) -> None:
        self.cursor_pos = (x, y)
        self.event_log.append(f"MOVE({x}, {y})")

    def mouse_down(self, x: int, y: int) -> None:
        self.cursor_pos = (x, y)
        self.is_down = True
        self.event_log.append(f"DOWN({x}, {y})")

    def mouse_up(self, x: int, y: int) -> None:
        self.cursor_pos = (x, y)
        self.is_down = False
        self.event_log.append(f"UP({x}, {y})")

    def key_down(self, key_code: str) -> None:
        self.event_log.append(f"KEY_DOWN({key_code})")

    def key_up(self, key_code: str) -> None:
        self.event_log.append(f"KEY_UP({key_code})")


class HumanizedController:
    """High-level controller applying behavioral dynamics onto any BaseInputDriver."""

    def __init__(self, driver: BaseInputDriver) -> None:
        self.driver = driver

    def human_click(
        self,
        center_x: float,
        center_y: float,
        radius_x: float = 8.0,
        radius_y: float = 8.0,
        press_duration_range: Tuple[float, float] = (0.045, 0.110),
    ) -> Tuple[int, int]:
        """Click with 2D Gaussian offset and human-like press duration."""
        tx, ty = generate_gaussian_target(center_x, center_y, radius_x, radius_y)
        self.driver.move_to(tx, ty)
        self.driver.mouse_down(tx, ty)
        duration = random.uniform(*press_duration_range)
        time.sleep(duration)
        self.driver.mouse_up(tx, ty)
        # Post-click idle hesitation
        time.sleep(random.uniform(0.08, 0.22))
        return tx, ty

    def human_swipe(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        steps: int = 25,
    ) -> List[Tuple[int, int]]:
        """Swipe along a cubic Bézier curve with physics easing."""
        sx, sy = generate_gaussian_target(start_x, start_y, 4.0, 4.0)
        ex, ey = generate_gaussian_target(end_x, end_y, 4.0, 4.0)

        trajectory = generate_bezier_trajectory((sx, sy), (ex, ey), steps=steps)
        if not trajectory:
            return []

        # Touch down at starting point
        self.driver.mouse_down(trajectory[0][0], trajectory[0][1])
        points_visited: List[Tuple[int, int]] = []

        for px, py, delay_ms in trajectory:
            self.driver.move_to(px, py)
            points_visited.append((px, py))
            time.sleep(delay_ms / 1000.0)

        # Touch up at end point
        self.driver.mouse_up(trajectory[-1][0], trajectory[-1][1])
        time.sleep(random.uniform(0.12, 0.25))
        return points_visited
