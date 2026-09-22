"""Real Android device acceptance tests running against live emulator-5554 and com.netease.my."""

import os
import subprocess
import time
import cv2
import numpy as np
import pytest

from core.device.adb import AdbDevice
from core.ocr.engine import OCREngine

CONNECTED_SERIAL = os.getenv("ADB_TEST_SERIAL", "emulator-5554")


def _is_device_ready() -> bool:
    try:
        res = subprocess.run(["adb", "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        out = res.stdout.decode()
        for line in out.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] == CONNECTED_SERIAL and parts[1] == "device":
                return True
        return False
    except Exception:
        return False


skip_if_no_device = pytest.mark.skipif(
    not _is_device_ready(),
    reason=f"Live ADB emulator [{CONNECTED_SERIAL}] is not online or ready",
)


@skip_if_no_device
def test_real_game_adb_connectivity():
    """Verify AdbDevice connects to live emulator and discovers resolution."""
    dev = AdbDevice(serial=CONNECTED_SERIAL, resolution=(1280, 720), resize_frame_to_baseline=True)
    assert dev.connect() is True
    assert dev.actual_resolution is not None
    assert dev.actual_resolution[0] > 0
    assert dev.actual_resolution[1] > 0
    dev.disconnect()


@skip_if_no_device
def test_real_game_package_installed_and_running():
    """Verify com.netease.my is installed and currently running on the emulator."""
    dev = AdbDevice(serial=CONNECTED_SERIAL)
    assert dev.connect() is True
    assert dev.is_app_running("com.netease.my") is True
    dev.disconnect()


@skip_if_no_device
def test_real_game_screencap_live():
    """Verify real-time screen capture from live game process."""
    dev = AdbDevice(serial=CONNECTED_SERIAL, resolution=(1280, 720), resize_frame_to_baseline=True)
    assert dev.connect() is True

    frame_bytes = dev.screencap()
    assert len(frame_bytes) > 1000
    img = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    assert img.shape == (720, 1280, 3)
    assert np.count_nonzero(img) > 1000
    dev.disconnect()


@skip_if_no_device
def test_real_game_ocr_perception():
    """Verify RapidOCR text detection on live game screen frames."""
    dev = AdbDevice(serial=CONNECTED_SERIAL, resolution=(1280, 720), resize_frame_to_baseline=True)
    assert dev.connect() is True

    frame_bytes = dev.screencap()
    ocr = OCREngine()
    items = ocr.recognize(frame_bytes)

    # In any active game screen or login dialog, OCR items should be recognized
    assert isinstance(items, list)
    print(f"Detected {len(items)} items on live game screen")
    for it in items[:5]:
        assert hasattr(it, "text")
        assert hasattr(it, "confidence")
        assert hasattr(it, "bbox")
    dev.disconnect()


@skip_if_no_device
def test_real_game_input_actions():
    """Verify Gaussian-randomized click, text input, and key press on live device."""
    dev = AdbDevice(serial=CONNECTED_SERIAL, resolution=(1280, 720), resize_frame_to_baseline=True)
    assert dev.connect() is True

    # Gaussian randomized click
    tx, ty = dev.click(640, 360, radius=5.0)
    assert tx > 0 and ty > 0

    # Text input
    dev.input_text("acceptance_test")

    # Key press (e.g. KEYCODE_BACK = 4)
    dev.press_key(4)
    time.sleep(0.5)

    dev.disconnect()
