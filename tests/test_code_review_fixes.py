"""
Unit tests validating root-cause fixes from the production code quality review:
1. Strict ADB device connection check (never trusting 'already connected' on offline devices).
2. Strict PNG magic byte verification during screencap (rejecting stdout error text).
3. Reconnection cooldown guard on DeviceInstance.screencap() to prevent 10 FPS reconnect storms.
4. Server-side unified frame transcoding with hash LRU memoization.
"""

import time
import subprocess
from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import pytest

from core.device.adb import AdbDevice
from cluster.instance_pool import DeviceInstance, InstanceStatus
from server.app import transcode_frame_to_jpeg, _TRANSCODE_CACHE


def test_adb_connect_rejects_offline_device():
    """Verify connect() does not false-positive on 'already connected' when device is offline in adb devices."""
    dev = AdbDevice(serial="127.0.0.1:16384")

    def mock_subprocess_run(cmd, *args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        if cmd[1] == "connect":
            mock_res.stdout = b"already connected to 127.0.0.1:16384\n"
        elif cmd[1] == "devices":
            mock_res.stdout = b"List of devices attached\n127.0.0.1:16384\toffline\n"
        return mock_res

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        ok = dev.connect()
        assert ok is False
        assert dev.is_connected() is False


def test_adb_connect_succeeds_when_device_is_online():
    """Verify connect() succeeds only when device is in 'device' state in adb devices."""
    dev = AdbDevice(serial="127.0.0.1:16384")

    def mock_subprocess_run(cmd, *args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        if cmd[1] == "connect":
            mock_res.stdout = b"connected to 127.0.0.1:16384\n"
        elif cmd[1] == "devices":
            mock_res.stdout = b"List of devices attached\n127.0.0.1:16384\tdevice\n"
        elif "dumpsys" in cmd:
            mock_res.stdout = b"displayId=0 ... w=1280 h=720"
        return mock_res

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        ok = dev.connect()
        assert ok is True
        assert dev.is_connected() is True


def test_adb_screencap_rejects_non_png_error_text():
    """Verify screencap rejects stdout error text with returncode 0 and does not cache invalid bytes."""
    dev = AdbDevice(serial="127.0.0.1:16384")
    dev._connected = True

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = b"error: device offline\n"
    mock_res.stderr = b""

    with patch("subprocess.run", return_value=mock_res):
        with pytest.raises(RuntimeError) as exc_info:
            dev.screencap()
        assert "invalid PNG header" in str(exc_info.value)
        assert dev.is_connected() is False
        assert dev._last_raw_bytes is None


def test_instance_screencap_reconnection_cooldown():
    """Verify DeviceInstance.screencap() throttles connection retries to prevent process storms."""
    inst = DeviceInstance(instance_id="test_throttle_inst", device_type="adb", serial="127.0.0.1:9999")
    inst._reconnect_cooldown_sec = 2.0

    connect_calls = 0

    def mock_connect():
        nonlocal connect_calls
        connect_calls += 1
        return False

    inst.connect = mock_connect

    # First attempt: triggers connect() and fails
    with pytest.raises(RuntimeError) as exc1:
        inst.screencap()
    assert "failed to connect" in str(exc1.value)
    assert connect_calls == 1

    # Second immediate attempt: caught by cooldown guard without calling connect()
    with pytest.raises(RuntimeError) as exc2:
        inst.screencap()
    assert "cooldown active" in str(exc2.value)
    assert connect_calls == 1

    # After cooldown expires: allows retry
    inst._last_reconnect_time = time.time() - 3.0
    with pytest.raises(RuntimeError) as exc3:
        inst.screencap()
    assert "failed to connect" in str(exc3.value)
    assert connect_calls == 2


def test_transcode_frame_to_jpeg_and_lru_cache():
    """Verify transcode_frame_to_jpeg converts PNG to JPEG, downscales large dimensions, and hits LRU cache."""
    # 1. Create a synthetic test PNG frame (1920x1080)
    mat = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cv2.rectangle(mat, (100, 100), (500, 500), (0, 255, 0), -1)
    ok, png_bytes = cv2.imencode(".png", mat)
    assert ok is True
    png_data = png_bytes.tobytes()

    # 2. Transcode
    jpg_data = transcode_frame_to_jpeg(png_data, max_dim=1280, quality=70)
    assert jpg_data.startswith(b"\xff\xd8")  # JPEG SOI marker
    assert len(jpg_data) > 0

    # Decode and check dimensions are scaled to max_dim=1280
    decoded = cv2.imdecode(np.frombuffer(jpg_data, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[1] == 1280
    assert decoded.shape[0] == 720

    # 3. Verify LRU Cache hit
    frame_hash = hash(png_data)
    assert frame_hash in _TRANSCODE_CACHE
    cached_bytes = transcode_frame_to_jpeg(png_data, max_dim=1280, quality=70)
    assert cached_bytes is jpg_data  # Exact same cached object reference

    # Non-PNG frames should pass through unchanged
    raw_dummy = b"not_a_png_or_jpeg"
    assert transcode_frame_to_jpeg(raw_dummy) == raw_dummy
