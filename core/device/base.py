"""
Base Device Abstraction for cross-platform hardware/emulator support.
Defines unified contracts across Windows, macOS, Linux (ADB / Headless), and Virtual.
"""

from __future__ import annotations
import abc
from typing import Any, Optional, Tuple, Union
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

    def probe(self) -> bool:
        """Lightweight liveness check; default trusts the cached connection flag.

        The cached flag only flips when an operation on this device fails, so a
        device that dies while its instance sits idle is otherwise invisible to
        the watchdog until the next task touches it. Subclasses backed by an
        external process (ADB) should override with a cheap real check.
        """
        return self._connected

    @abc.abstractmethod
    def screencap(self) -> bytes:
        """
        Capture current frame.
        Returns raw image bytes (JPEG / PNG) or frame buffer.
        """
        pass

    def screencap_mat(self) -> Any:
        """
        Capture current frame directly as OpenCV numpy array.
        Subclasses can override with zero-reencode fast paths.
        """
        import cv2
        import numpy as np

        raw_bytes = self.screencap()
        if not raw_bytes:
            return None
        return cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)

    def click(self, x: float, y: float, radius: float = 6.0) -> Tuple[int, int]:
        """Convenience method to execute humanized click."""
        return self.controller.human_click(x, y, radius_x=radius, radius_y=radius)

    def swipe(self, sx: float, sy: float, ex: float, ey: float, steps: int = 25) -> Any:
        """Convenience method to execute humanized Bezier swipe."""
        return self.controller.human_swipe(sx, sy, ex, ey, steps=steps)

    def input_text(self, content: str) -> None:
        """Type text string onto device."""
        if hasattr(self.input_driver, "text"):
            self.input_driver.text(content)

    def press_key(self, key_code: Union[int, str]) -> None:
        """Send key press event to device."""
        if hasattr(self.input_driver, "key_down"):
            self.input_driver.key_down(str(key_code))

    def key_event(self, key_code: Union[int, str]) -> None:
        """Alias for press_key for unified cross-driver compatibility."""
        self.press_key(key_code)
