"""
Base Device Abstraction for cross-platform hardware/emulator support.
Defines unified contracts across Windows, macOS, Linux (ADB / Headless), and Virtual.
"""

from __future__ import annotations
import abc
from typing import Any, Optional, Tuple
from loguru import logger

from core.input.driver import BaseInputDriver, HumanizedController


class BaseDevice(abc.ABC):
    """Abstract base device representing a game client container (OS window, ADB instance, etc.)."""

    def __init__(self, name: str, resolution: Tuple[int, int] = (1280, 720)) -> None:
        self.name = name
        self.resolution = resolution
        self._connected = False
        self._controller: Optional[HumanizedController] = None

    @property
    @abc.abstractmethod
    def platform_type(self) -> str:
        """Return platform identifier: 'windows', 'macos', 'linux_adb', 'virtual'."""
        pass

    @property
    @abc.abstractmethod
    def input_driver(self) -> BaseInputDriver:
        """Underlying input driver for hardware/virtual event injection."""
        pass

    @property
    def controller(self) -> HumanizedController:
        """High-level controller with humanized behavioral dynamics."""
        if self._controller is None:
            self._controller = HumanizedController(self.input_driver)
        return self._controller

    @abc.abstractmethod
    def connect(self) -> bool:
        """Establish connection to the target device/window/socket."""
        pass

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Tear down connection and release resources."""
        pass

    def is_connected(self) -> bool:
        return self._connected

    @abc.abstractmethod
    def screencap(self) -> bytes:
        """
        Capture current frame.
        Returns raw image bytes (JPEG / PNG) or frame buffer.
        """
        pass

    def click(self, x: float, y: float, radius: float = 6.0) -> Tuple[int, int]:
        """Convenience method to execute humanized click."""
        return self.controller.human_click(x, y, radius_x=radius, radius_y=radius)

    def swipe(self, sx: float, sy: float, ex: float, ey: float, steps: int = 25) -> Any:
        """Convenience method to execute humanized Bezier swipe."""
        return self.controller.human_swipe(sx, sy, ex, ey, steps=steps)
