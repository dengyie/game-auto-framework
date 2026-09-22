"""
Device Factory for dynamic cross-platform driver instantiation and automatic probing.
Ensures zero-crash graceful fallback on Linux VPS, Windows, macOS, or Docker.
"""

from __future__ import annotations
import sys
from typing import Any, Dict, Optional
from loguru import logger

from core.device.base import BaseDevice
from core.device.virtual import VirtualDevice
from core.device.adb import AdbDevice


class DeviceFactory:
    """Instantiates the correct device driver according to configuration and operating system."""

    @staticmethod
    def create(
        device_type: str = "auto",
        name: str = "default_device",
        serial: Optional[str] = None,
        resolution: tuple[int, int] = (1280, 720),
        **kwargs: Any,
    ) -> BaseDevice:
        """
        Create and return a BaseDevice instance.

        Args:
            device_type: "auto", "adb", "virtual", "windows", "macos"
            name: friendly instance name
            serial: ADB target address (e.g. "127.0.0.1:5555" or "emulator-5554")
            resolution: target standard resolution (width, height)
        """
        # Explicit device types
        if device_type == "virtual":
            logger.info(f"Instantiating VirtualDevice: [{name}]")
            return VirtualDevice(name=name, resolution=resolution)

        if device_type == "adb":
            target_serial = serial or "127.0.0.1:5555"
            logger.info(f"Instantiating AdbDevice: [{name}] targeting [{target_serial}]")
            return AdbDevice(serial=target_serial, name=name, resolution=resolution)

        # Automatic Probing based on OS platform
        if device_type == "auto":
            current_os = sys.platform
            logger.info(f"Auto-detecting device driver for OS: [{current_os}]")

            # On Linux (e.g. VPS / Cloud Server) -> ADB is standard
            if current_os.startswith("linux"):
                target_serial = serial or "127.0.0.1:5555"
                logger.info(f"Linux VPS detected: defaulting to AdbDevice [{target_serial}]")
                dev = AdbDevice(serial=target_serial, name=name, resolution=resolution)
                if dev.connect():
                    return dev
                logger.warning("ADB target unreachable, falling back to VirtualDevice for simulation")
                return VirtualDevice(name=name, resolution=resolution)

            # On macOS
            if current_os == "darwin":
                if serial:
                    return AdbDevice(serial=serial, name=name, resolution=resolution)
                logger.info("macOS detected: initializing Virtual/Simulator device")
                return VirtualDevice(name=name, resolution=resolution)

            # On Windows
            if current_os.startswith("win"):
                if serial:
                    return AdbDevice(serial=serial, name=name, resolution=resolution)
                return VirtualDevice(name=name, resolution=resolution)

        # Default fallback
        logger.warning(f"Unknown or unconfigured device_type [{device_type}]; using VirtualDevice")
        return VirtualDevice(name=name, resolution=resolution)
