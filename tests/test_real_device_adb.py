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
    """Verify humanized click and swipe dispatch on real ADB device."""
    dev = DeviceFactory.create(device_type="adb", serial=CONNECTED_SERIAL)
    assert dev.connect() is True

    # Humanized click with Gaussian offset
    target_x, target_y = dev.click(400, 600, radius=5.0)
    assert 380 <= target_x <= 420
    assert 580 <= target_y <= 620

    # Humanized Bezier swipe
    swipe_res = dev.swipe(500, 1200, 500, 600, steps=15)
    assert len(swipe_res) >= 2


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
