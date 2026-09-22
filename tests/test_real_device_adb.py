"""
End-to-End Real ADB Base Device & Emulator Integration Tests.
Executes live hardware/emulator screencap, OCR text recognition, and humanized touch dispatch.
Automatically skipped if no live ADB device is connected.
"""

import subprocess
import pytest
import cv2
import numpy as np

from core.device.factory import DeviceFactory
from core.ocr.engine import OCREngine
from fastapi.testclient import TestClient
from server.app import app


def get_first_connected_adb_serial():
    try:
        res = subprocess.run(["adb", "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        lines = res.stdout.decode("utf-8").strip().splitlines()
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                return parts[0]
    except Exception:
        pass
    return None


CONNECTED_SERIAL = get_first_connected_adb_serial()
skip_if_no_adb = pytest.mark.skipif(
    CONNECTED_SERIAL is None,
    reason="No live ADB device/emulator connected to host",
)


@skip_if_no_adb
def test_real_adb_device_screencap_and_ocr():
    """Verify live screen capture and RapidOCR text recognition on real ADB device."""
    dev = DeviceFactory.create(device_type="adb", serial=CONNECTED_SERIAL)
    assert dev.connect() is True
    assert dev.is_connected() is True

    frame_bytes = dev.screencap()
    assert len(frame_bytes) > 10000

    # Verify frame is valid image
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    assert img is not None
    assert img.shape[0] > 100
    assert img.shape[1] > 100

    # Run OCR on live screen frame
    ocr = OCREngine.get_instance()
    results = ocr.recognize(img)
    assert isinstance(results, list)


@skip_if_no_adb
def test_real_adb_device_touch_input():
    """Verify humanized click and swipe dispatch on real ADB device with auto-scaling."""
    from core.device.adb import AdbDevice
    dev = AdbDevice(serial=CONNECTED_SERIAL, resolution=(1280, 720), auto_scale=True)
    assert dev.connect() is True
    assert dev.actual_resolution is not None

    # Verify coordinate mapping
    act_w, act_h = dev.actual_resolution
    expected_x = 400 * (act_w / 1280)
    expected_y = 600 * (act_h / 720)

    # Humanized click with Gaussian offset around scaled coordinates
    target_x, target_y = dev.click(400, 600, radius=5.0)
    assert (expected_x - 20) <= target_x <= (expected_x + 20)
    assert (expected_y - 20) <= target_y <= (expected_y + 20)

    # Test unmap symmetry
    orig_x, orig_y = dev.unmap_coordinates(expected_x, expected_y)
    assert abs(orig_x - 400) < 1e-3
    assert abs(orig_y - 600) < 1e-3

    # Humanized Bezier swipe
    swipe_res = dev.swipe(100, 200, 300, 400, steps=15)
    assert len(swipe_res) >= 2


@skip_if_no_adb
def test_real_adb_device_frame_resizing():
    """Verify screencap resizing to canonical baseline and raw mode."""
    from core.device.adb import AdbDevice
    dev = AdbDevice(serial=CONNECTED_SERIAL, resolution=(1280, 720), resize_frame_to_baseline=True)
    assert dev.connect() is True

    # 1. Baseline screencap (should be 1280x720)
    baseline_bytes = dev.screencap()
    base_img = cv2.imdecode(np.frombuffer(baseline_bytes, np.uint8), cv2.IMREAD_COLOR)
    assert base_img.shape == (720, 1280, 3)

    # 2. Raw screencap (should be physical size, e.g. 1080x2400)
    raw_bytes = dev.screencap_raw()
    raw_img = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
    assert raw_img.shape[0] == dev.actual_resolution[1]
    assert raw_img.shape[1] == dev.actual_resolution[0]


@skip_if_no_adb
def test_real_adb_device_app_lifecycle():
    """Verify app management on real device (Appium Settings test app)."""
    from core.device.adb import AdbDevice
    dev = AdbDevice(serial=CONNECTED_SERIAL)
    assert dev.connect() is True

    pkg = "io.appium.settings"
    # Stop app first
    dev.stop_app(pkg)
    assert dev.is_app_running(pkg) is False

    # Start app
    start_ok = dev.start_app(pkg)
    assert start_ok is True

    # Clean up
    dev.stop_app(pkg)


@skip_if_no_adb
def test_real_adb_server_api_pipeline():
    """Verify FastAPI VPS server start, screenshot, and stop lifecycle against real ADB device."""
    client = TestClient(app)

    start_payload = {
        "plugin": "mhxy_mobile",
        "pipeline": "daily_shimen",
        "device_type": "adb",
        "device_serial": CONNECTED_SERIAL,
        "variables": {"has_shimen_quest": True},
    }
    start_res = client.post("/api/v1/tasks/start", json=start_payload)
    assert start_res.status_code == 200

    status_res = client.get("/api/v1/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["is_running"] is True
    assert status_data["device_connected"] is True
    assert status_data["device_type"] == "linux_adb"

    shot_res = client.get("/api/v1/screenshot")
    assert shot_res.status_code == 200
    assert shot_res.headers["content-type"] == "image/jpeg"
    assert len(shot_res.content) > 10000

    stop_res = client.post("/api/v1/tasks/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "stopped"

    final_status = client.get("/api/v1/status").json()
    assert final_status["is_running"] is False
