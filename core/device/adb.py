"""
ADB Device Driver for Linux / VPS / Windows / macOS.
Supports network TCP/IP connection to remote emulators, cloud phones, and physical devices.
"""

from __future__ import annotations
import subprocess
import time
from typing import Optional, Tuple
from loguru import logger

from core.device.base import BaseDevice
from core.input.driver import BaseInputDriver


class AdbInputDriver(BaseInputDriver):
    """Input driver that translates commands to ADB shell input events."""

    def __init__(self, serial: str) -> None:
        self.serial = serial

    def _run_adb(self, *args: str) -> str:
        cmd = ["adb", "-s", self.serial, "shell", *args]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            return res.stdout.decode("utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"ADB execution failed: {cmd} -> {e}")
            return ""

    def move_to(self, x: int, y: int) -> None:
        # ADB touch devices do not have an airborne hover cursor; no-op
        pass

    def mouse_down(self, x: int, y: int) -> None:
        # Touch down via adb sendevent or motionevent
        pass

    def mouse_up(self, x: int, y: int) -> None:
        pass

    def tap(self, x: int, y: int) -> None:
        self._run_adb("input", "tap", str(x), str(y))

    def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int = 300) -> None:
        self._run_adb("input", "swipe", str(sx), str(sy), str(ex), str(ey), str(duration_ms))

    def key_down(self, key_code: str) -> None:
        self._run_adb("input", "keyevent", key_code)

    def key_up(self, key_code: str) -> None:
        pass


class AdbDevice(BaseDevice):
    """Android device or emulator controlled via ADB (ideal for Linux VPS deployment)."""

    def __init__(
        self,
        serial: str = "127.0.0.1:5555",
        name: str = "adb_device",
        resolution: Tuple[int, int] = (1280, 720),
    ) -> None:
        super().__init__(name=name, resolution=resolution)
        self.serial = serial
        self._driver = AdbInputDriver(self.serial)

    @property
    def platform_type(self) -> str:
        return "linux_adb"

    @property
    def input_driver(self) -> BaseInputDriver:
        return self._driver

    def connect(self) -> bool:
        """Connect to remote device via adb connect if IP:port format."""
        logger.info(f"Connecting to ADB target: {self.serial}")
        if ":" in self.serial:
            try:
                res = subprocess.run(
                    ["adb", "connect", self.serial],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=8,
                )
                output = res.stdout.decode("utf-8", errors="ignore")
                if "connected" in output.lower() or "already connected" in output.lower():
                    self._connected = True
                    logger.info(f"ADB device [{self.serial}] successfully connected")
                    return True
            except Exception as e:
                logger.warning(f"ADB connection attempt error for [{self.serial}]: {e}")

        # Check if device is in adb devices list
        try:
            res = subprocess.run(["adb", "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            if self.serial in res.stdout.decode("utf-8", errors="ignore"):
                self._connected = True
                return True
        except Exception as e:
            logger.error(f"Failed to check adb devices: {e}")

        self._connected = False
        return False

    def disconnect(self) -> None:
        if ":" in self.serial and self._connected:
            try:
                subprocess.run(["adb", "disconnect", self.serial], timeout=5)
            except Exception:
                pass
        self._connected = False

    def screencap(self) -> bytes:
        """Capture screen frame via ADB screencap binary stream."""
        if not self._connected:
            raise RuntimeError(f"ADB device [{self.serial}] is disconnected")

        cmd = ["adb", "-s", self.serial, "exec-out", "screencap", "-p"]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=6)
            if res.returncode == 0 and len(res.stdout) > 0:
                return res.stdout
            raise RuntimeError(f"screencap failed with code {res.returncode}: {res.stderr.decode()}")
        except Exception as e:
            logger.error(f"ADB screencap failed on [{self.serial}]: {e}")
            raise

    def click(self, x: float, y: float, radius: float = 6.0) -> Tuple[int, int]:
        """Override click to dispatch ADB tap directly with Gaussian offset."""
        from core.input.bezier import generate_gaussian_target
        tx, ty = generate_gaussian_target(x, y, radius_x=radius, radius_y=radius)
        self._driver.tap(tx, ty)
        time.sleep(0.1)
        return tx, ty

    def swipe(self, sx: float, sy: float, ex: float, ey: float, steps: int = 25) -> Any:
        """Override swipe to dispatch ADB swipe command."""
        from core.input.bezier import generate_gaussian_target
        tx1, ty1 = generate_gaussian_target(sx, sy, 4.0, 4.0)
        tx2, ty2 = generate_gaussian_target(ex, ey, 4.0, 4.0)
        duration_ms = int(steps * 15)
        self._driver.swipe(tx1, ty1, tx2, ty2, duration_ms=duration_ms)
        time.sleep(0.15)
        return [(tx1, ty1), (tx2, ty2)]
