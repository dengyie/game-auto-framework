"""Tests for DeviceFactory cross-platform probing and driver instantiation."""

import pytest
from core.device.factory import DeviceFactory
from core.device.virtual import VirtualDevice
from core.device.adb import AdbDevice


def test_device_factory_virtual():
    dev = DeviceFactory.create(device_type="virtual", name="test_virtual")
    assert isinstance(dev, VirtualDevice)
    assert dev.platform_type == "virtual"
    assert dev.connect() is True
    assert dev.is_connected() is True

    frame = dev.screencap()
    assert len(frame) > 0
    assert frame.startswith(b"\xff\xd8")  # JPEG SOI header

    # Test click and swipe
    tx, ty = dev.click(500, 300)
    assert 480 <= tx <= 520
    assert 280 <= ty <= 320

    dev.disconnect()
    assert dev.is_connected() is False


def test_device_factory_auto():
    # Calling auto on any system must return a valid non-crashing BaseDevice
    dev = DeviceFactory.create(device_type="auto")
    assert dev is not None
    assert dev.name is not None


def test_device_factory_adb_instance():
    dev = DeviceFactory.create(device_type="adb", serial="127.0.0.1:5555")
    assert isinstance(dev, AdbDevice)
    assert dev.platform_type == "linux_adb"
    assert dev.serial == "127.0.0.1:5555"
