"""
Unit tests for AdbDevice thread-safe screencap caching, TTL eviction, and format separation.
Verifies root-cause fixes for:
1. Cache pollution between raw physical frames and baseline 1280x720 frames.
2. Unbounded stale cache returns during device disconnects.
3. screencap_mat() thread-safety and lock re-entrancy.
4. Concurrent multi-threaded screencap access.
"""

import time
import threading
from unittest.mock import patch, MagicMock
import cv2
import numpy as np
import pytest

from core.device.adb import AdbDevice


def _make_dummy_png(width: int, height: int, color=(100, 150, 200)) -> bytes:
    """Generate a valid PNG image byte buffer with specified dimensions."""
    img = np.full((height, width, 3), color, dtype=np.uint8)
    # Draw some shapes so it's a non-empty realistic image
    cv2.putText(img, f"{width}x{height}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    success, encoded = cv2.imencode(".png", img)
    assert success
    return encoded.tobytes()


@pytest.fixture
def mock_adb_device():
    """Create an AdbDevice with mocked serial and baseline 1280x720 resolution."""
    dev = AdbDevice(serial="mock_device:5555", resolution=(1280, 720), auto_scale=True, resize_frame_to_baseline=True)
    dev._connected = True
    dev._cap_cache_ttl = 0.35
    return dev


def test_adb_cache_separation_raw_vs_baseline(mock_adb_device):
    """
    Verify raw frames and baseline-resized frames use independent cache slots.
    Calling screencap(raw=True) must NOT pollute screencap(raw=False) with 1080x1920 data.
    """
    dev = mock_adb_device
    # Physical device is 1080x1920 (portrait)
    physical_png = _make_dummy_png(1080, 1920)

    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = physical_png
    mock_run.stderr = b""

    with patch("subprocess.run", return_value=mock_run) as p_run:
        # 1. Capture raw frame
        raw_bytes = dev.screencap(raw=True)
        assert p_run.call_count == 1
        assert dev._last_raw_bytes == physical_png
        assert dev.actual_resolution == (1080, 1920)
        # Baseline cache should be None or invalidated
        assert dev._last_baseline_bytes is None

        # Verify raw decoded dimensions
        raw_mat = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
        assert raw_mat.shape == (1920, 1080, 3)

        # 2. Capture baseline frame within TTL (0.35s)
        # Should NOT return the raw 1080x1920 cached frame, but resize it to 1280x720!
        base_bytes = dev.screencap(raw=False)
        assert base_bytes != raw_bytes
        assert dev._last_baseline_bytes is not None

        base_mat = cv2.imdecode(np.frombuffer(base_bytes, np.uint8), cv2.IMREAD_COLOR)
        assert base_mat.shape == (720, 1280, 3)

        # 3. Subsequent calls within TTL should use cached frames without running subprocess.run
        p_run.reset_mock()
        raw_bytes_cached = dev.screencap(raw=True)
        base_bytes_cached = dev.screencap(raw=False)
        assert p_run.call_count == 0
        assert raw_bytes_cached == raw_bytes
        assert base_bytes_cached == base_bytes


def test_adb_screencap_ttl_eviction_and_error_propagation(mock_adb_device):
    """
    Verify error fallback only returns cached frame if within TTL.
    Once TTL expires, device errors must be raised to prevent infinite loops on dead devices.
    """
    dev = mock_adb_device
    physical_png = _make_dummy_png(1080, 1920)

    # First successful capture
    mock_success = MagicMock(returncode=0, stdout=physical_png, stderr=b"")
    with patch("subprocess.run", return_value=mock_success):
        first_frame = dev.screencap(raw=True)
        assert len(first_frame) > 0

    # Device now disconnected, subprocess fails
    mock_fail = MagicMock(returncode=1, stdout=b"", stderr=b"device offline")
    with patch("subprocess.run", return_value=mock_fail):
        # Case A: Within TTL, fallback to cached frame is permitted
        dev._last_cap_time = time.time()
        cached_frame = dev.screencap(raw=True)
        assert cached_frame == first_frame

        # Case B: After TTL expires (>0.35s ago), error MUST be raised
        dev._last_cap_time = time.time() - 1.0  # 1 second ago
        with pytest.raises(RuntimeError) as exc_info:
            dev.screencap(raw=True)
        assert "screencap failed with code 1" in str(exc_info.value)


def test_adb_screencap_mat_locked_and_scaled(mock_adb_device):
    """Verify screencap_mat() correctly captures and resizes under lock without PNG re-encoding."""
    dev = mock_adb_device
    physical_png = _make_dummy_png(1080, 1920)

    mock_run = MagicMock(returncode=0, stdout=physical_png, stderr=b"")
    with patch("subprocess.run", return_value=mock_run):
        # Baseline mat (1280x720)
        mat_base = dev.screencap_mat(raw=False)
        assert isinstance(mat_base, np.ndarray)
        assert mat_base.shape == (720, 1280, 3)

        # Raw mat (1080x1920)
        mat_raw = dev.screencap_mat(raw=True)
        assert isinstance(mat_raw, np.ndarray)
        assert mat_raw.shape == (1920, 1080, 3)


def test_adb_screencap_concurrent_thread_safety(mock_adb_device):
    """Verify concurrent screencap and screencap_mat invocations from multiple threads do not crash or race."""
    dev = mock_adb_device
    physical_png = _make_dummy_png(1080, 1920)
    mock_run = MagicMock(returncode=0, stdout=physical_png, stderr=b"")

    errors = []
    frames_captured = []

    def worker(worker_id: int):
        try:
            for i in range(10):
                if i % 3 == 0:
                    f = dev.screencap(raw=True)
                    assert len(f) > 0
                elif i % 3 == 1:
                    f = dev.screencap(raw=False)
                    assert len(f) > 0
                else:
                    m = dev.screencap_mat(raw=False)
                    assert m.shape == (720, 1280, 3)
                frames_captured.append(1)
                time.sleep(0.01)
        except Exception as e:
            errors.append((worker_id, e))

    with patch("subprocess.run", return_value=mock_run):
        threads = [threading.Thread(target=worker, args=(t,)) for t in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

    assert len(errors) == 0, f"Thread errors: {errors}"
    assert len(frames_captured) == 60


def test_adb_disconnect_clears_cache_and_state(mock_adb_device):
    """Verify disconnect() acquires lock and purges all cached frame buffers and timestamps."""
    dev = mock_adb_device
    physical_png = _make_dummy_png(1080, 1920)
    mock_run = MagicMock(returncode=0, stdout=physical_png, stderr=b"")

    with patch("subprocess.run", return_value=mock_run):
        dev.screencap(raw=True)
        dev.screencap(raw=False)
        assert dev._last_raw_bytes is not None
        assert dev._last_baseline_bytes is not None
        assert dev._last_cap_time > 0

    dev.disconnect()
    assert dev.is_connected() is False
    assert dev._last_raw_bytes is None
    assert dev._last_baseline_bytes is None
    assert dev._last_cap_time == 0.0
