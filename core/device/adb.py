"""
ADB Device Driver for Linux / VPS / Windows / macOS.
Supports network TCP/IP connection to remote emulators, cloud phones, and physical devices.
"""

from __future__ import annotations
import struct
import subprocess
import time
from typing import Any, Optional, Tuple
import cv2
from loguru import logger
import numpy as np

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
        auto_scale: bool = True,
        resize_frame_to_baseline: bool = True,
    ) -> None:
        super().__init__(name=name, resolution=resolution)
        self.serial = serial
        self.auto_scale = auto_scale
        self.resize_frame_to_baseline = resize_frame_to_baseline
        self.actual_resolution: Optional[Tuple[int, int]] = None
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
                    self._probe_device_specs()
                    return True
            except Exception as e:
                logger.warning(f"ADB connection attempt error for [{self.serial}]: {e}")

        # Check if device is in adb devices list
        try:
            res = subprocess.run(["adb", "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            if self.serial in res.stdout.decode("utf-8", errors="ignore"):
                self._connected = True
                self._probe_device_specs()
                return True
        except Exception as e:
            logger.error(f"Failed to check adb devices: {e}")

        self._connected = False
        return False

    def _probe_device_specs(self) -> None:
        """Probe physical screen resolution and configuration from ADB."""
        try:
            import re
            cmd = ["adb", "-s", self.serial, "shell", "wm", "size"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            out = res.stdout.decode("utf-8", errors="ignore")
            m = re.findall(r"(\d+)x(\d+)", out)
            if m:
                w, h = int(m[-1][0]), int(m[-1][1])
                cmd_ori = ["adb", "-s", self.serial, "shell", "dumpsys", "display"]
                res_ori = subprocess.run(cmd_ori, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
                ori_out = res_ori.stdout.decode("utf-8", errors="ignore")
                is_landscape = "mCurrentOrientation=1" in ori_out or "mCurrentOrientation=3" in ori_out
                if is_landscape and w < h:
                    w, h = h, w
                self.actual_resolution = (w, h)
                logger.info(f"Detected ADB device [{self.serial}] resolution: {self.actual_resolution}")
        except Exception as e:
            logger.warning(f"Failed to probe device specs: {e}")

    def disconnect(self) -> None:
        if ":" in self.serial and self._connected:
            try:
                subprocess.run(["adb", "disconnect", self.serial], timeout=5)
            except Exception:
                pass
        self._connected = False

    def map_coordinates(self, x: float, y: float) -> Tuple[float, float]:
        """Map canonical baseline coordinates (e.g. 1280x720) to physical device coordinates."""
        if not self.auto_scale or not self.actual_resolution:
            return x, y
        actual_w, actual_h = self.actual_resolution
        base_w, base_h = self.resolution
        if base_w <= 0 or base_h <= 0:
            return x, y
        scale_x = actual_w / base_w
        scale_y = actual_h / base_h
        return x * scale_x, y * scale_y

    def unmap_coordinates(self, x: float, y: float) -> Tuple[float, float]:
        """Map physical device coordinates back to canonical baseline coordinates."""
        if not self.auto_scale or not self.actual_resolution:
            return x, y
        actual_w, actual_h = self.actual_resolution
        base_w, base_h = self.resolution
        if actual_w <= 0 or actual_h <= 0:
            return x, y
        return x * (base_w / actual_w), y * (base_h / actual_h)

    def screencap(self, raw: bool = False) -> bytes:
        """
        Capture screen frame via ADB screencap binary stream.
        If resize_frame_to_baseline is enabled and raw is False, returns frame resized to baseline resolution.
        """
        if not self._connected:
            raise RuntimeError(f"ADB device [{self.serial}] is disconnected")

        cmd = ["adb", "-s", self.serial, "exec-out", "screencap", "-p"]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=6)
            if res.returncode == 0 and len(res.stdout) > 0:
                raw_bytes = res.stdout
                if len(raw_bytes) >= 24 and raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                    pw, ph = struct.unpack(">II", raw_bytes[16:24])
                    self.actual_resolution = (pw, ph)

                if raw or not self.resize_frame_to_baseline:
                    return raw_bytes

                target_w, target_h = self.resolution
                if self.actual_resolution and self.actual_resolution != (target_w, target_h):
                    img = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
                        success, encoded = cv2.imencode(".png", resized)
                        if success:
                            return encoded.tobytes()

                return raw_bytes
            raise RuntimeError(f"screencap failed with code {res.returncode}: {res.stderr.decode()}")
        except Exception as e:
            logger.error(f"ADB screencap failed on [{self.serial}]: {e}")
            raise

    def screencap_raw(self) -> bytes:
        """Direct raw frame capture without any resolution scaling."""
        return self.screencap(raw=True)

    def click(self, x: float, y: float, radius: float = 6.0) -> Tuple[int, int]:
        """Override click to dispatch ADB tap with automatic coordinate scaling and Gaussian offset."""
        from core.input.bezier import generate_gaussian_target
        mx, my = self.map_coordinates(x, y)
        tx, ty = generate_gaussian_target(mx, my, radius_x=radius, radius_y=radius)
        self._driver.tap(tx, ty)
        time.sleep(0.1)
        return tx, ty

    def swipe(self, sx: float, sy: float, ex: float, ey: float, steps: int = 25) -> Any:
        """Override swipe to dispatch ADB swipe command with coordinate scaling."""
        from core.input.bezier import generate_gaussian_target
        msx, msy = self.map_coordinates(sx, sy)
        mex, mey = self.map_coordinates(ex, ey)
        tx1, ty1 = generate_gaussian_target(msx, msy, 4.0, 4.0)
        tx2, ty2 = generate_gaussian_target(mex, mey, 4.0, 4.0)
        duration_ms = int(steps * 15)
        self._driver.swipe(tx1, ty1, tx2, ty2, duration_ms=duration_ms)
        time.sleep(0.15)
        return [(tx1, ty1), (tx2, ty2)]

    def set_device_resolution(self, width: int = 1280, height: int = 720) -> bool:
        """Override physical display resolution using wm size."""
        size_str = f"{width}x{height}"
        self._driver._run_adb("wm", "size", size_str)
        self._probe_device_specs()
        return True

    def reset_device_resolution(self) -> bool:
        """Reset display resolution to device physical default."""
        self._driver._run_adb("wm", "size", "reset")
        self._probe_device_specs()
        return True

    def install_apk(self, apk_path: str) -> bool:
        """Install an APK file onto the connected ADB device."""
        try:
            logger.info(f"Installing APK [{apk_path}] to device [{self.serial}]")
            cmd = ["adb", "-s", self.serial, "install", "-r", apk_path]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            success = res.returncode == 0 and "success" in res.stdout.decode("utf-8", errors="ignore").lower()
            if success:
                logger.info(f"Successfully installed APK [{apk_path}]")
            else:
                logger.error(f"APK installation failed: {res.stdout.decode()} {res.stderr.decode()}")
            return success
        except Exception as e:
            logger.error(f"APK installation error: {e}")
            return False

    def start_app(self, package_name: str, activity: Optional[str] = None) -> bool:
        """Start an application via monkey or am start."""
        try:
            if activity:
                target = f"{package_name}/{activity}"
                out = self._driver._run_adb("am", "start", "-n", target)
            else:
                out = self._driver._run_adb("monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1")
            return "events injected: 1" in out.lower() or "starting" in out.lower() or out.strip() == ""
        except Exception as e:
            logger.error(f"Failed to start app [{package_name}]: {e}")
            return False

    def stop_app(self, package_name: str) -> bool:
        """Force stop an application."""
        try:
            self._driver._run_adb("am", "force-stop", package_name)
            return True
        except Exception as e:
            logger.error(f"Failed to stop app [{package_name}]: {e}")
            return False

    def is_app_running(self, package_name: str) -> bool:
        """Check if an app process is currently active."""
        try:
            out = self._driver._run_adb("pidof", package_name)
            return len(out.strip()) > 0
        except Exception:
            return False
