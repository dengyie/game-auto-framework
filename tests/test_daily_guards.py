"""Tests for the P2 safety guards added in the 2026-09-30 review:

- _click edge-zone guard (safety redline enforced in code)
- open_activity_panel fallback: 1280x720 constant scaled by real frame size,
  and BACK-degradation after repeated misses (live: (353,64) hit 基础设置 at 1600x900)
- click_dialog_choice fallback degradation: blind default-slot clicks capped at 3,
  reset on any matched choice
- handle_quiz bank-miss header guard: no first-option blind click without a quiz
  header on screen (live: 青丘奇珍 banner reached the miss path)
"""

import numpy as np
import pytest
from unittest.mock import patch

from loguru import logger as loguru_logger

from plugins.mhxy_mobile.custom import daily_handlers as dh
from plugins.mhxy_mobile.custom.daily_handlers import (
    _click,
    click_dialog_choice,
    handle_quiz,
    open_activity_panel,
)
from core.device.adb import AdbDevice
from scripts.run_daily_dailies import ensure_game_foreground
from scheduler.dag import NodeAction, PipelineContext


class DummyOCRItem:
    def __init__(self, text: str, center: tuple, confidence: float = 0.95):
        self.text = text
        self.center = center
        self.confidence = confidence
        self.bbox = (int(center[0]) - 20, int(center[1]) - 10, 40, 20)


class DummyDevice:
    def __init__(self):
        self.clicks = []
        self.keys = []

    def click(self, x, y):
        self.clicks.append((float(x), float(y)))

    def press_key(self, keycode):
        self.keys.append(keycode)


@pytest.fixture
def caplog_records():
    records = []
    handler_id = loguru_logger.add(records.append, level="DEBUG", colorize=False)
    try:
        yield records
    finally:
        loguru_logger.remove(handler_id)


# --- _click edge-zone guard ---------------------------------------------------

def test_click_blocked_outside_frame_bounds():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame"] = np.zeros((900, 1600, 3), dtype=np.uint8)
    _click(ctx, 5, 5)        # bezel
    _click(ctx, 1595, 450)   # right bezel
    _click(ctx, 400, 895)    # bottom bezel
    assert device.clicks == []

    _click(ctx, 400, 300)    # inside -> allowed
    assert device.clicks == [(400.0, 300.0)]


def test_click_allowed_without_frame_info():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    _click(ctx, 50, 50)      # no _last_frame -> guard skipped (tests / pre-classify)
    assert device.clicks == [(50.0, 50.0)]


# --- open_activity_panel fallback ----------------------------------------------

def test_open_panel_fallback_scales_to_frame_size():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    # No 活动 text parsed (overlay covering HUD) on a 1600x900 frame.
    ctx.variables["_last_frame_items"] = []
    ctx.variables["_last_frame"] = np.zeros((900, 1600, 3), dtype=np.uint8)
    open_activity_panel(ctx, NodeAction(type="custom", custom_func="open_activity_panel"))
    assert device.clicks == [(353 * 1.25, 64 * 1.25)]  # (441.25, 80.0) — the real button


def test_open_panel_fallback_degrades_to_back_after_3_misses():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = []
    ctx.variables["_last_frame"] = np.zeros((900, 1600, 3), dtype=np.uint8)
    act = NodeAction(type="custom", custom_func="open_activity_panel")
    for _ in range(3):
        open_activity_panel(ctx, act)
    assert len(device.clicks) == 3
    assert device.keys == []
    open_activity_panel(ctx, act)  # 4th miss: stop clicking, press BACK
    assert len(device.clicks) == 3
    assert device.keys == [4]
    # BACK resets the counter (no latch): the next miss retries the scaled tap
    # instead of pressing BACK forever (which would never open the panel again
    # even after the overlay is gone).
    assert ctx.variables["panel_fallback_count"] == 0
    open_activity_panel(ctx, act)
    assert len(device.clicks) == 4
    assert device.keys == [4]


def test_open_panel_fallback_counter_resets_when_panel_opens():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    # Two fallback misses happened, then the scaled tap opened the activity panel.
    ctx.variables["panel_fallback_count"] = 2
    panel_items = [
        DummyOCRItem("日常活动", (150.0, 300.0)),  # left tab column (x < 320)
        DummyOCRItem("活跃度 20", (900.0, 400.0)),  # bottom chest/活跃 strip
    ]
    with patch.object(dh, "_ocr_items", return_value=panel_items):
        dh.classify_screen(ctx, None)
    assert ctx.variables["panel_open"] is True
    assert ctx.variables["panel_fallback_count"] == 0
    # Next fallback miss starts a fresh cycle: blind tap, not BACK.
    ctx.variables["_last_frame_items"] = []
    open_activity_panel(ctx, NodeAction(type="custom", custom_func="open_activity_panel"))
    assert device.clicks and device.keys == []


# --- click_dialog_choice fallback degradation ----------------------------------

def _dialog_items(choice_text=None, y=500.0):
    items = [DummyOCRItem("请选择要做的事", (600.0, 450.0))]
    if choice_text:
        items.append(DummyOCRItem(choice_text, (1085.0, y)))
    return items


def test_dialog_fallback_clicks_default_slot_then_degrades_to_back():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _dialog_items()  # prompt but no valid choice
    act = NodeAction(type="custom", custom_func="click_dialog_choice")
    for _ in range(3):
        click_dialog_choice(ctx, act)
    assert device.clicks == [(1086.0, 468.0)] * 3
    assert device.keys == []
    click_dialog_choice(ctx, act)  # 4th: no more blind clicks
    assert len(device.clicks) == 3
    assert device.keys == [4]
    # BACK resets the counter (no latch): a later OCR-miss dialog gets a fresh
    # 3-try cycle, not an immediate cancel-BACK that would reflexively dismiss it.
    assert ctx.variables["dialog_fallback_count"] == 0
    click_dialog_choice(ctx, act)
    assert len(device.clicks) == 4
    assert device.keys == [4]


def test_dialog_fallback_counter_resets_on_matched_choice():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _dialog_items()
    act = NodeAction(type="custom", custom_func="click_dialog_choice")
    click_dialog_choice(ctx, act)
    click_dialog_choice(ctx, act)
    assert ctx.variables["dialog_fallback_count"] == 2
    # A real matched choice appears -> click it and reset the counter.
    ctx.variables["_last_frame_items"] = _dialog_items("说说话")
    click_dialog_choice(ctx, act)
    assert device.clicks[-1] == (1085.0, 500.0)
    assert ctx.variables["dialog_fallback_count"] == 0
    # Next fallback starts from scratch (blind slot, not BACK).
    ctx.variables["_last_frame_items"] = _dialog_items()
    click_dialog_choice(ctx, act)
    assert device.clicks[-1] == (1086.0, 468.0)


# --- handle_quiz bank-miss header guard ----------------------------------------

_BOGUS_Q = "这是一个完全不存在的题目呀呀呀？"


def _quiz_items(with_header=True):
    items = []
    if with_header:
        items.append(DummyOCRItem("三界奇缘", (700.0, 50.0)))
    items.append(DummyOCRItem(_BOGUS_Q, (700.0, 100.0)))   # question ROI (440..1135, 25..150)
    items.append(DummyOCRItem("选项甲", (500.0, 260.0)))    # option ROI (430..1280, 205..520)
    items.append(DummyOCRItem("选项乙", (900.0, 260.0)))
    return items


def test_quiz_bank_miss_without_header_refuses_blind_click():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _quiz_items(with_header=False)
    handle_quiz(ctx, NodeAction(type="custom", custom_func="handle_quiz"))
    assert device.clicks == [], "bank miss without a quiz header must not blind-click"


def test_quiz_bank_miss_with_header_clicks_first_option():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _quiz_items(with_header=True)
    handle_quiz(ctx, NodeAction(type="custom", custom_func="handle_quiz"))
    # Upstream policy intact inside a genuine quiz window: first option in ROI order.
    assert device.clicks == [(500.0, 260.0)]


# --- Fix A/B/C: cross-game promo carousel incident (live 2026-09-30 11:xx) -----
# The 每日新发现 full-screen ad page (no ×, no 关闭) mis-routed the run: banner text
# landed in the quiz question ROI, and its 领取 button looped click_dialog_choice 28
# times. Three guards: classify routes it to dismiss (single BACK, never 领取),
# the 领取-match streak degrades to BACK, and the same-coord-repeat counter covers
# the static-frame watchdog's animated blind spot.


def _promo_items():
    return [
        DummyOCRItem("每日新发现", (700.0, 50.0)),
        DummyOCRItem("上线领全武将", (700.0, 120.0)),
        DummyOCRItem("9月23日首发，可以逛的武侠小说", (700.0, 300.0)),
        DummyOCRItem("领取", (1184.0, 497.0)),
    ]


def test_promo_carousel_routes_to_popup_despite_dialog():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    with patch.object(dh, "_ocr_items", return_value=_promo_items()):
        dh.classify_screen(ctx, None)
    v = ctx.variables
    assert v["promo_carousel"] is True
    assert v["popup_open"] is True
    # The 领取 button registers as a dialog choice — popup must still win
    # (the popup branch is evaluated before dialog in daily_dailies.json).
    assert v["dialog_open"] is True
    # banner_noise veto keeps the banner out of the quiz router.
    assert v["quiz_open"] is False


def test_promo_carousel_dismisses_via_single_back_never_claim():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _promo_items()
    dh.dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert device.keys == [4]
    assert device.clicks == [], "never click the promo 领取"


def test_promo_back_streak_suspends_after_burst():
    """Live 2026-10-02: 30 consecutive promo BACKs walked the client to the launcher.
    The burst must be bounded: after 8 BACKs the handler suspends and waits."""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _promo_items()
    act = NodeAction(type="custom", custom_func="dismiss_popups")
    for _ in range(8):
        dh.dismiss_popups(ctx, act)
    assert device.keys == [4] * 8
    dh.dismiss_popups(ctx, act)  # streak 9: suspended — no further BACK
    assert device.keys == [4] * 8
    assert ctx.variables["promo_back_streak"] == 9


def test_classify_screen_clears_promo_back_streak_when_no_popup():
    """Each promo episode gets its own bounded burst: a tick with no popup at all
    clears the streak (e.g. the game re-launched into a clean main city)."""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["promo_back_streak"] = 7
    items = [
        DummyOCRItem("指引", (270.0, 63.0)),
        DummyOCRItem("活动", (352.0, 63.0)),
    ]
    with patch.object(dh, "_ocr_items", return_value=items):
        dh.classify_screen(ctx, None)
    assert "promo_back_streak" not in ctx.variables


# --- chat composer guard (2026-10-02 live: a walk-out/relaunch left the compose
# bar focused; popup_open stayed False and the runner blind-tapped 活动 through
# the input bar until the same-coord watchdog fired) ----------------------------

def _composer_items():
    return [
        DummyOCRItem("点击这里输入", (700.0, 30.0)),
        DummyOCRItem("发送", (640.0, 85.0)),
        DummyOCRItem("取消", (1479.0, 30.0)),
        DummyOCRItem("确定", (1560.0, 30.0)),
        DummyOCRItem("世界", (75.0, 240.0)),
    ]


def test_classify_screen_routes_chat_composer_to_popup():
    ctx = PipelineContext(device=DummyDevice())
    with patch.object(dh, "_ocr_items", return_value=_composer_items()):
        dh.classify_screen(ctx, None)
    v = ctx.variables
    assert v["chat_input_open"] is True
    assert v["popup_open"] is True, "composer must route sense -> dismiss_popups"


def test_chat_composer_closes_via_cancel_never_confirm():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = _composer_items()
    ctx.variables["chat_input_open"] = True
    dh.dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert device.clicks == [(1479.0, 30.0)], "close via the system 取消 — never 确定/发送"
    assert device.keys == []


def test_chat_composer_without_parsed_cancel_presses_back():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("点击这里输入", (700.0, 30.0)),
        DummyOCRItem("发送", (640.0, 85.0)),
    ]
    dh.dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert device.clicks == []
    assert device.keys == [4]


# --- runner foreground guard ---------------------------------------------------

class _FgDevice:
    def __init__(self, foreground: bool):
        self.foreground = foreground
        self.starts = []

    def is_foreground_app(self, package_name):
        return self.foreground

    def start_app(self, package_name):
        self.starts.append(package_name)
        return True


def test_ensure_game_foreground_healthy_resets_streak_without_relaunch():
    dev = _FgDevice(foreground=True)
    assert ensure_game_foreground(dev, "com.netease.my", 2) == 0
    assert dev.starts == []


def test_ensure_game_foreground_relaunches_and_accumulates_streak():
    dev = _FgDevice(foreground=False)
    assert ensure_game_foreground(dev, "com.netease.my", 0) == 1
    assert dev.starts == ["com.netease.my"]
    assert ensure_game_foreground(dev, "com.netease.my", 1) == 2
    assert len(dev.starts) == 2


def test_adb_is_foreground_app_parses_focus_line_and_fails_open():
    dev = AdbDevice(serial="mock_device:5555")
    focused_game = (
        "  mCurrentFocus=Window{79aeef4 u0 com.netease.my/com.netease.game.MessiahNativeActivity}\n"
    )
    focused_launcher = "  mCurrentFocus=Window{d4d981a u0 app.lawnchair/app.lawnchair.LawnchairLauncher}\n"
    with patch.object(dev._driver, "_run_adb", return_value=focused_game):
        assert dev.is_foreground_app("com.netease.my") is True
    with patch.object(dev._driver, "_run_adb", return_value=focused_launcher):
        # MuMu mini-window: the game process stays alive (pidof hits) but the
        # launcher owns the focus — this False is what the guard acts on.
        assert dev.is_foreground_app("com.netease.my") is False
    with patch.object(dev._driver, "_run_adb", return_value=""):
        assert dev.is_foreground_app("com.netease.my") is True  # fail open


def test_ensure_game_foreground_swallows_start_app_error():
    """start_app raising must not propagate out of the guard: the streak still
    accumulates so the caller's abort limit stays the single failure exit."""
    class _BrokenDevice(_FgDevice):
        def start_app(self, package_name):
            raise RuntimeError("adb gone")

    dev = _BrokenDevice(foreground=False)
    assert ensure_game_foreground(dev, "com.netease.my", 0) == 1


def test_adb_start_app_retries_inconclusive_dumpsys_without_monkey_fallback():
    """A transient empty dumpsys must not lie (old pidof behavior) nor trigger the
    monkey fallback: retry once, then honor the parsed focus line."""
    dev = AdbDevice(serial="mock_device:5555")
    focused_game = (
        "  mCurrentFocus=Window{79aeef4 u0 com.netease.my/com.netease.game.MessiahNativeActivity}\n"
    )
    calls = []

    def fake_run_adb(*args):
        calls.append(args[0])
        if args[0] == "dumpsys":
            return "" if calls.count("dumpsys") == 1 else focused_game
        if args[0] == "cmd":
            return "priority=0\n  com.netease.my/com.netease.game.LauncherActivity\n"
        return "Starting: Intent...\n"

    with patch.object(dev._driver, "_run_adb", side_effect=fake_run_adb):
        assert dev.start_app("com.netease.my") is True
    assert calls.count("monkey") == 0, "inconclusive dumpsys must not fire the monkey fallback"


def test_adb_start_app_monkey_fallback_on_lost_focus():
    """am start that does not take focus (launcher owns it) must fall back to monkey,
    which then takes focus — the 2026-10-02 live failure."""
    dev = AdbDevice(serial="mock_device:5555")
    focused_launcher = "  mCurrentFocus=Window{d4d981a u0 app.lawnchair/app.lawnchair.LawnchairLauncher}\n"
    focused_game = "  mCurrentFocus=Window{79aeef4 u0 com.netease.my/com.netease.game.MessiahNativeActivity}\n"
    resolve = "priority=0\n  com.netease.my/com.netease.game.LauncherActivity\n"
    dumpsys_calls = 0

    def fake_run_adb(*args):
        nonlocal dumpsys_calls
        if args[0] == "cmd":
            return resolve
        if args[0] == "dumpsys":
            dumpsys_calls += 1
            return focused_launcher if dumpsys_calls == 1 else focused_game
        return "ok\n"

    with patch.object(dev._driver, "_run_adb", side_effect=fake_run_adb):
        assert dev.start_app("com.netease.my") is True


def test_promo_block_latch_set_after_sustained_ignore_and_cleared_by_classify():
    """A promo that ignores BACK past the burst budget must latch promo_block_latch
    (the run cannot report success) and stop pressing; classify clears the latch when
    the promo overlay is gone so a later legitimate completion is not masked."""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    act = NodeAction(type="custom", custom_func="dismiss_popups")
    promo = [
        DummyOCRItem("每日新发现", (700.0, 300.0)),
        DummyOCRItem("领取", (1184.0, 497.0)),
    ]
    for _ in range(dh.PROMO_BLOCK_STREAK + 1):
        ctx.variables["_last_frame_items"] = promo
        with patch("plugins.mhxy_mobile.custom.daily_handlers.time.sleep"):
            dh.dismiss_popups(ctx, act)
    # burst budget 8 pressed BACK once each; past it, no more key presses
    assert len(device.keys) == 8
    assert ctx.variables["promo_block_latch"] is True

    ctx.variables["promo_back_streak"] = 21
    items = [DummyOCRItem("活动", (352.0, 63.0))]
    with patch.object(dh, "_ocr_items", return_value=items):
        dh.classify_screen(ctx, None)
    assert "promo_block_latch" not in ctx.variables
    assert "promo_back_streak" not in ctx.variables


def test_dialog_claim_streak_degrades_to_back_after_3():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("请选择要做的事", (600.0, 450.0)),
        DummyOCRItem("领取", (1184.0, 497.0)),
    ]
    act = NodeAction(type="custom", custom_func="click_dialog_choice")
    click_dialog_choice(ctx, act)  # streak 1: click
    click_dialog_choice(ctx, act)  # streak 2: click
    assert device.clicks == [(1184.0, 497.0)] * 2
    assert device.keys == []
    click_dialog_choice(ctx, act)  # streak 3: no more claim clicks — BACK
    assert device.clicks == [(1184.0, 497.0)] * 2
    assert device.keys == [4]
    # BACK resets the streak (no latch): a later genuine claim gets a fresh cycle.
    assert ctx.variables["dialog_claim_streak"] == 0
    click_dialog_choice(ctx, act)
    assert device.clicks == [(1184.0, 497.0)] * 3
    assert device.keys == [4]


def test_dialog_claim_streak_resets_on_non_claim_match():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    claim_items = [
        DummyOCRItem("请选择要做的事", (600.0, 450.0)),
        DummyOCRItem("领取", (1184.0, 497.0)),
    ]
    task_items = [
        DummyOCRItem("请选择要做的事", (600.0, 450.0)),
        DummyOCRItem("师门任务", (1085.0, 420.0)),
    ]
    act = NodeAction(type="custom", custom_func="click_dialog_choice")
    ctx.variables["_last_frame_items"] = claim_items
    click_dialog_choice(ctx, act)
    click_dialog_choice(ctx, act)  # streak 2
    ctx.variables["_last_frame_items"] = task_items
    click_dialog_choice(ctx, act)  # real task choice resets the streak
    assert ctx.variables["dialog_claim_streak"] == 0
    ctx.variables["_last_frame_items"] = claim_items
    click_dialog_choice(ctx, act)  # fresh cycle: click 领取, not instant BACK
    assert device.clicks[-1] == (1184.0, 497.0)
    assert device.clicks[-2] == (1085.0, 420.0)  # the earlier real task choice
    assert device.keys == []


def test_dialog_claim_streak_cleared_when_no_dialog_on_screen():
    ctx = PipelineContext(device=DummyDevice())
    ctx.variables["dialog_claim_streak"] = 2
    panel_items = [
        DummyOCRItem("日常活动", (150.0, 300.0)),
        DummyOCRItem("活跃度 20", (900.0, 400.0)),
    ]
    with patch.object(dh, "_ocr_items", return_value=panel_items):
        dh.classify_screen(ctx, None)
    assert ctx.variables["panel_open"] is True
    assert "dialog_claim_streak" not in ctx.variables


def test_click_same_coord_counter_with_jitter_tolerance():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    for x, y in ((1184.0, 497.0), (1186.0, 495.0), (1182.0, 499.0), (1185.0, 496.0)):
        _click(ctx, x, y)
    # ±3px OCR jitter on the same button still accumulates (no grid straddling).
    assert ctx.variables["_click_repeat"] == 4
    _click(ctx, 500.0, 300.0)  # target moved on -> streak restarts
    assert ctx.variables["_click_repeat"] == 1


def test_click_repeat_counter_cleared_by_classify_progress():
    ctx = PipelineContext(device=DummyDevice())
    ctx.variables["_click_repeat"] = 9
    ctx.variables["_last_click_xy"] = (1184.0, 497.0)
    ctx.variables["_click_cells"] = [(1184, 496)] * 6
    panel_items = [
        DummyOCRItem("日常活动", (150.0, 300.0)),
        DummyOCRItem("活跃度 20", (900.0, 400.0)),
    ]
    with patch.object(dh, "_ocr_items", return_value=panel_items):
        dh.classify_screen(ctx, None)
    # Reaching the panel is unambiguous progress — a stale streak must not linger
    # to penalize the next dead screen with an instant fuse.
    assert "_click_repeat" not in ctx.variables
    assert "_last_click_xy" not in ctx.variables
    assert "_click_cells" not in ctx.variables


def test_click_repeat_sliding_window_survives_interleaved_different_click():
    """P1 root cause (live 2026-09-30 20:27): open_panel taps -> BACK -> quit-confirm
    取消 loop repeated 150 ticks with zero progress. The old counter compared only
    against the *previous* click, so each cycle's 取消 at a different coordinate reset
    it to 1 and the fuse never fired. The sliding-window count of the loop's own
    anchor cell must keep climbing across cycles."""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    # Cycle: tap 活动 (353,64) x3, then the dismiss handler taps 取消 (621,419).
    loop = [(353.0, 64.0)] * 3 + [(621.0, 419.0)]
    peaks = []
    for x, y in loop * 4:  # 16 clicks
        _click(ctx, x, y)
        peaks.append(int(ctx.variables["_click_repeat"]))
    # At an 活动-anchor click mid-cycle the window is dominated by (353,64):
    # the loop's repeat count reaches the fuse (>=10) even though 取消 jitters in.
    assert max(peaks) >= 10, f"peak repeat {max(peaks)} never reached fuse (loop evaded watchdog)"
    # The very last window state is the 取消 anchor — asserting a >=10 peak, not the
    # tail value, is the point: the fuse fires on an anchor tick, not on the tail.
    assert ctx.variables["_click_repeat"] < 10  # tail is the 取消 anchor


def test_promo_carousel_not_on_real_dialog():
    """P2: a genuine NPC dialog (请选择要做的事 prompt) must never be classified as the
    cross-game promo carousel — a misfire would BACK a real task dialog open."""
    ctx = PipelineContext(device=DummyDevice())
    real_dialog = [
        DummyOCRItem("请选择要做的事", (600.0, 450.0)),
        DummyOCRItem("邀你战三界", (700.0, 100.0)),  # coincidental event copy
        DummyOCRItem("领取", (1184.0, 497.0)),
    ]
    with patch.object(dh, "_ocr_items", return_value=real_dialog):
        dh.classify_screen(ctx, None)
    assert ctx.variables["promo_carousel"] is False
    # It stays a dialog (popup only from genuine promo, which this is not).
    assert ctx.variables["dialog_open"] is True
    assert ctx.variables["popup_open"] is False


def test_dismiss_promo_never_steals_reward_summary():
    """P2: a task-completion reward page (任务完成 + 确定) must be collected, never
    backed out of — even if it coincidentally carries a promo campaign line."""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("任务完成", (600.0, 300.0)),
        DummyOCRItem("邀你战三界", (700.0, 100.0)),
        DummyOCRItem("确定", (660.0, 500.0)),
    ]
    dh.dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert device.keys == [], "reward summary must not be dismissed with BACK"
    assert device.clicks, "reward summary 确定 must be collected"
    assert device.clicks[-1] == (660.0, 500.0)
