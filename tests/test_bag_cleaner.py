"""
Unit tests for the dedicated bag-cleanup module (bag_cleaner):
- needs_bag_clean recognition (bag-full latch + one-pass-per-session)
- Empty whitelist = scan-only no-op (nothing clicked, contents logged)
- Never-touch list beats the whitelist (藏宝图/仙玉/装备 never clicked)
- Sell flow clicks are OCR-verified and capped per session
- Confirm safety: no 确定 click without sell wording; 仙玉/离开游戏 abort
- Latch clearing when space is actually freed
"""

import json
from unittest.mock import patch

import pytest

from plugins.mhxy_mobile.custom import bag_cleaner as bc
from plugins.mhxy_mobile.custom.bag_cleaner import (
    needs_bag_clean,
    run_bag_clean_pass,
)
from scheduler.dag import NodeAction, PipelineContext


class DummyOCRItem:
    def __init__(self, text: str, center: tuple[float, float], confidence: float = 0.95):
        self.text = text
        self.center = center
        self.confidence = confidence
        self.bbox = (int(center[0]) - 20, int(center[1]) - 10, 40, 20)


class DummyDevice:
    def __init__(self):
        self.clicks = []
        self.swipes = []
        self.keys = []

    def click(self, x: float, y: float):
        self.clicks.append((float(x), float(y)))

    def press_key(self, keycode):
        self.keys.append(keycode)

    def swipe(self, sx, sy, ex, ey, steps=25):
        self.swipes.append((sx, sy, ex, ey))


def _whitelist(sellable, cap=10):
    return {"sellable": sellable, "max_items_per_session": cap}


def _pass(ctx, wl, screens):
    """Run one cleanup pass with a scripted whitelist and OCR queue."""
    with patch.object(bc, "_load_whitelist", return_value=wl), patch(
        "plugins.mhxy_mobile.custom.bag_cleaner.time.sleep"
    ):
        ctx.variables["_bag_clean_ocr_queue"] = screens
        run_bag_clean_pass(ctx, NodeAction(type="custom", custom_func="run_bag_clean_pass"))


def test_needs_bag_clean_gated_and_one_pass_per_session():
    ctx = PipelineContext(device=DummyDevice())
    assert needs_bag_clean(ctx, None) is False, "no bag-full latch -> no clean"
    ctx.variables["shop_blocked_bag_full"] = True
    assert needs_bag_clean(ctx, None) is True
    ctx.variables["bag_clean_attempted"] = True
    assert needs_bag_clean(ctx, None) is False, "one pass per session"


def test_empty_whitelist_is_scan_only_noop():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["shop_blocked_bag_full"] = True
    screens = [
        [DummyOCRItem("背包", (1500.0, 800.0))],
        [DummyOCRItem("背包", (1500.0, 800.0)), DummyOCRItem("月华露", (400.0, 300.0)),
         DummyOCRItem("关闭", (1200.0, 100.0))],
        [DummyOCRItem("关闭", (1200.0, 100.0))],
    ]
    _pass(ctx, _whitelist([]), screens)
    assert device.clicks == [(1500.0, 800.0), (1200.0, 100.0)], "only the bag button is acted on — no item actions, then closed"
    assert ctx.variables["bag_clean_attempted"] is True


def test_never_touch_list_beats_whitelist():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["shop_blocked_bag_full"] = True
    screens = [
        [DummyOCRItem("背包", (1500.0, 800.0))],
        [DummyOCRItem("藏宝图x3", (400.0, 300.0)), DummyOCRItem("关闭", (1200.0, 100.0))],
        [DummyOCRItem("关闭", (1200.0, 100.0))],
    ]
    _pass(ctx, _whitelist(["藏宝图x3", "月华露"]), screens)
    assert device.clicks == [(1500.0, 800.0), (1200.0, 100.0)], "never-touch names must never be clicked"


def test_sells_whitelisted_item_and_clears_latch():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["shop_blocked_bag_full"] = True
    screens = [
        [DummyOCRItem("背包", (1500.0, 800.0))],
        [DummyOCRItem("月华露x2", (400.0, 300.0)), DummyOCRItem("关闭", (1200.0, 100.0))],
        # after selecting the item: the item detail with 出售
        [DummyOCRItem("月华露x2", (400.0, 300.0)), DummyOCRItem("出售", (900.0, 500.0)),
         DummyOCRItem("关闭", (1200.0, 100.0))],
        # confirm dialog with sell wording + 确定
        [DummyOCRItem("确定要出售月华露x2", (640.0, 300.0)), DummyOCRItem("确定", (747.0, 420.0)),
         DummyOCRItem("取消", (880.0, 420.0))],
        # closing: bag panel with 关闭
        [DummyOCRItem("关闭", (1200.0, 100.0))],
    ]
    _pass(ctx, _whitelist(["月华露"]), screens)
    assert len(device.clicks) == 5, "bag button + item + 出售 + 确定 + close"
    assert ctx.variables["bag_clean_attempted"] is True
    assert "shop_blocked_bag_full" not in ctx.variables, "freed space lifts the daily gate"


def test_confirm_without_sell_wording_never_confirms():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["shop_blocked_bag_full"] = True
    screens = [
        [DummyOCRItem("背包", (1500.0, 800.0))],
        [DummyOCRItem("月华露x2", (400.0, 300.0)), DummyOCRItem("关闭", (1200.0, 100.0))],
        [DummyOCRItem("月华露x2", (400.0, 300.0)), DummyOCRItem("出售", (900.0, 500.0)),
         DummyOCRItem("关闭", (1200.0, 100.0))],
        # a confirm dialog with NO sell wording (e.g. a stray notice) — 确定 must not fire
        [DummyOCRItem("活动公告", (640.0, 300.0)), DummyOCRItem("确定", (747.0, 420.0))],
        [DummyOCRItem("关闭", (1200.0, 100.0))],
    ]
    _pass(ctx, _whitelist(["月华露"]), screens)
    assert (747.0, 420.0) not in device.clicks, "bare 确定 without sell wording must never be clicked"
    assert "shop_blocked_bag_full" in ctx.variables, "nothing sold -> gate stays latched"


def test_xianyu_dialog_aborts_confirm():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["shop_blocked_bag_full"] = True
    screens = [
        [DummyOCRItem("背包", (1500.0, 800.0))],
        [DummyOCRItem("月华露x2", (400.0, 300.0)), DummyOCRItem("关闭", (1200.0, 100.0))],
        [DummyOCRItem("月华露x2", (400.0, 300.0)), DummyOCRItem("出售", (900.0, 500.0)),
         DummyOCRItem("关闭", (1200.0, 100.0))],
        # a 仙玉 dialog must abort the confirm outright
        [DummyOCRItem("花费10仙玉", (640.0, 300.0)), DummyOCRItem("确定", (747.0, 420.0))],
        [DummyOCRItem("关闭", (1200.0, 100.0))],
    ]
    _pass(ctx, _whitelist(["月华露"]), screens)
    assert (747.0, 420.0) not in device.clicks, "仙玉 dialog confirm is a safety red line"


def test_session_cap_bounds_the_pass():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["shop_blocked_bag_full"] = True
    screens = [
        [DummyOCRItem("背包", (1500.0, 800.0))],
        [DummyOCRItem("月华露x2", (400.0, 300.0)), DummyOCRItem("关闭", (1200.0, 100.0))],
        [DummyOCRItem("月华露x2", (400.0, 300.0)), DummyOCRItem("出售", (900.0, 500.0)),
         DummyOCRItem("关闭", (1200.0, 100.0))],
        [DummyOCRItem("确定要出售月华露x2", (640.0, 300.0)), DummyOCRItem("确定", (747.0, 420.0))],
    ]
    _pass(ctx, _whitelist(["月华露"], cap=1), screens)
    confirm_clicks = [c for c in device.clicks if c == (747.0, 420.0)]
    assert len(confirm_clicks) == 1, "session cap bounds the pass to 1 sale"


def test_missing_bag_button_skips_without_blind_clicks():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["shop_blocked_bag_full"] = True
    screens = [
        [DummyOCRItem("月宫", (640.0, 300.0))],  # no 背包 button visible
    ]
    _pass(ctx, _whitelist(["月华露"]), screens)
    assert device.clicks == [], "no OCR-verified bag button -> no blind coordinates"
    assert ctx.variables["bag_clean_attempted"] is True
