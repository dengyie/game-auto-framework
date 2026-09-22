"""
Virtual / Mock Device for Headless Testing, Simulation, and CI/CD pipelines.
"""

from __future__ import annotations
import io
from typing import Optional, Tuple
from PIL import Image

from core.device.base import BaseDevice
from core.input.driver import BaseInputDriver, VirtualInputDriver


class VirtualDevice(BaseDevice):
    """Simulated device that runs purely in memory without external window or ADB daemon."""

    def __init__(self, name: str = "virtual_mock", resolution: Tuple[int, int] = (1280, 720)) -> None:
        super().__init__(name=name, resolution=resolution)
        self._driver = VirtualInputDriver()
        self._current_frame: Optional[bytes] = None
        self._generate_default_frame()

    @property
    def platform_type(self) -> str:
        return "virtual"

    @property
    def input_driver(self) -> BaseInputDriver:
        return self._driver

    def _generate_default_frame(self) -> None:
        """Create a placeholder solid image buffer."""
        img = Image.new("RGB", self.resolution, color=(35, 39, 42))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        self._current_frame = buf.getvalue()

    def set_mock_frame(self, image_bytes: bytes) -> None:
        """Update current mock screenshot frame."""
        self._current_frame = image_bytes

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def screencap(self) -> bytes:
        if not self._connected:
            raise RuntimeError(f"Device {self.name} is not connected.")
        if self._current_frame is None:
            self._generate_default_frame()
        return self._current_frame or b""
