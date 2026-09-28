"""Regressions from the live MuMu 12 session.

The emulator reports a portrait panel through ``wm size`` while the touch
viewport and the screencap are landscape. A network ``adb disconnect`` also
drops the shared tunnel used by the cluster, so a driver going idle must not
issue one.
"""

from __future__ import annotations

from core.device.adb import AdbDevice, parse_display_resolution
from plugins.mhxy_mobile.custom import handlers as novice
from scheduler.dag import NodeAction, NodeRecognition, PipelineContext
from server.app import image_media_type


MUMU_WM_SIZE = "Physical size: 900x1600\n"
MUMU_DISPLAY = """
mViewports=[DisplayViewport{type=INTERNAL, orientation=1, logicalFrame=Rect(0, 0 - 1600, 900), physicalFrame=Rect(0, 0 - 1600, 900), deviceWidth=1600, deviceHeight=900}]
DisplayDeviceInfo{"Built-in Screen": uniqueId="local:0", 900 x 1600, modeId 1, defaultModeId 1, supportedModes [{id=1, width=900, height=1600, fps=60.0}], rotation 0}
mCurrentOrientation=1
"""


class _RecordingDevice:
    platform_type = "adb"

    def __init__(self) -> None:
        self.clicks: list[tuple[float, float]] = []

    def click(self, x: float, y: float, radius: float = 6.0) -> tuple[int, int]:
        self.clicks.append((x, y))
        return int(x), int(y)

    def unmap_coordinates(self, x: float, y: float) -> tuple[float, float]:
        return x / 2, y / 2


def test_mumu_viewport_wins_over_portrait_wm_size():
    assert parse_display_resolution(MUMU_WM_SIZE, MUMU_DISPLAY) == (1600, 900)


def test_logical_frame_is_used_when_device_size_is_absent():
    dump = "logicalFrame=Rect(0, 0 - 1600, 900)\nmCurrentOrientation=1\n"
    assert parse_display_resolution(MUMU_WM_SIZE, dump) == (1600, 900)


def test_orientation_swap_remains_for_dumps_without_a_viewport():
    assert parse_display_resolution(MUMU_WM_SIZE, "mCurrentOrientation=1\n") == (1600, 900)
    assert parse_display_resolution("Physical size: 2400x1080\n", "") == (2400, 1080)


def test_network_disconnect_does_not_drop_the_shared_adb_session(monkeypatch):
    calls: list[list[str]] = []

    def _refuse_subprocess(*args, **kwargs):
        calls.append(list(args[0]) if args else [])
        raise AssertionError("disconnect must not spawn adb")

    monkeypatch.setattr("core.device.adb.subprocess.run", _refuse_subprocess)
    device = AdbDevice(serial="127.0.0.1:16384")
    device._connected = True
    device.disconnect()
    assert device._connected is False
    assert calls == []


def test_screenshot_media_type_follows_the_container():
    assert image_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert image_media_type(b"\xff\xd8\xffrest") == "image/jpeg"
    assert image_media_type(b"not-an-image") == "application/octet-stream"


def test_real_novice_handlers_do_not_invent_progress_without_a_frame():
    device = _RecordingDevice()
    ctx = PipelineContext(device=device)
    recognition = NodeRecognition(type="custom")
    action = NodeAction(type="custom")

    assert novice.find_novice_quest_tracker(ctx, None, recognition) is False
    novice.click_novice_quest_tracker(ctx, action)
    assert device.clicks == []
    assert "story_dialog_open" not in ctx.variables

    assert novice.is_story_dialog_open(ctx, None, recognition) is False
    novice.click_skip_or_advance_dialog(ctx, action)
    assert "novice_in_battle" not in ctx.variables

    assert novice.is_novice_battle_active(ctx, None, recognition) is False
    novice.handle_novice_combat_actions(ctx, action)
    assert ctx.variables.get("novice_battle_ended") is not True

    assert novice.is_novice_battle_ended(ctx, None, recognition) is False
    assert novice.is_novice_reward_available(ctx, None, recognition) is False
    novice.click_claim_novice_reward(ctx, action)
    assert "level" not in ctx.variables
    assert device.clicks == []


def test_real_novice_click_keeps_the_baseline_ocr_point(monkeypatch):
    class _Item:
        text = "主线-初探长寿村"
        center = (1128, 196)

    monkeypatch.setattr(novice, "_ocr_any", lambda frame, words: _Item())
    device = _RecordingDevice()
    ctx = PipelineContext(device=device)

    assert novice.find_novice_quest_tracker(ctx, object(), NodeRecognition(type="custom")) is True
    novice.click_novice_quest_tracker(ctx, NodeAction(type="custom"))

    assert ctx.variables["novice_quest_point"] == (1128.0, 196.0)
    assert device.clicks == [(1128.0, 196.0)]
    assert "story_dialog_open" not in ctx.variables


def test_dialog_uses_the_lower_middle_line_and_ignores_corners(monkeypatch):
    class _Item:
        def __init__(self, text: str, center: tuple[int, int]) -> None:
            self.text = text
            self.center = center

    class _Frame:
        shape = (720, 1280, 3)

    story = _Item("药已送到，回门派向师父禀报", (760, 560))
    corner = _Item("好友", (1200, 680))

    monkeypatch.setattr(novice, "_ocr_any", lambda frame, words: None)
    monkeypatch.setattr(novice, "_ocr_items", lambda frame: [corner, story])
    device = _RecordingDevice()
    ctx = PipelineContext(device=device)

    assert novice.is_story_dialog_open(ctx, _Frame(), NodeRecognition(type="custom")) is True
    novice.click_skip_or_advance_dialog(ctx, NodeAction(type="custom"))
    assert device.clicks == [(760.0, 560.0)]
    assert "novice_in_battle" not in ctx.variables
