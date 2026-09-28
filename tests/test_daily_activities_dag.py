"""
Unit tests for the autonomous daily activities DAG and interaction handlers:
- Activity panel card parsing (_parse_activity_panel)
- Multi-task queue selection and 参加 click (handle_activity_panel)
- Activity chest claiming upon daily completion
- Screen classification for shop, turnin, dialog, use item, tracker, walking
- Action handlers for shop buy, turnin, dialogue, item use, tracker navigation
"""

from unittest.mock import patch
import pytest

from core.device.virtual import VirtualDevice
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from plugins.mhxy_mobile.custom import daily_handlers as dh
from plugins.mhxy_mobile.custom.daily_handlers import (
    _parse_activity_panel,
    _extract_huoyue,
    _extract_huoyue_from_frame,
    handle_activity_panel,
    classify_screen,
    dismiss_popups,
    click_shimen_board,
    click_shop_buy,
    click_turnin,
    click_use_item,
    click_dialog_choice,
    click_task_tracker,
    open_activity_panel,
    TOPBAR_ACTIVITY,
    PANEL_CLOSE,
    ESCORT_JOIN,
)
from scheduler.dag import NodeAction, PipelineContext, PipelineStatus


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

    def swipe(self, sx: float, sy: float, ex: float, ey: float, steps: int = 25):
        self.swipes.append((float(sx), float(sy), float(ex), float(ey)))

    def screencap(self, raw: bool = False):
        return b""


def test_parse_activity_panel_cards():
    items = [
        DummyOCRItem("师门任务", (883.0, 122.0)),
        DummyOCRItem("经验金币", (883.0, 149.0)),
        DummyOCRItem("参加", (1077.0, 148.0)),
        DummyOCRItem("次数0/10活跃0/20", (921.0, 178.0)),

        DummyOCRItem("宝图任务", (883.0, 236.0)),
        DummyOCRItem("银币金币", (883.0, 263.0)),
        DummyOCRItem("参加", (1077.0, 263.0)),
        DummyOCRItem("次数10/10活跃10/10", (921.0, 291.0)),

        DummyOCRItem("运镖", (450.0, 352.0)),
        DummyOCRItem("参加", (669.0, 377.0)),
        DummyOCRItem("次数0/3", (461.0, 408.0)),
    ]

    cards = _parse_activity_panel(items)
    cards_dict = {c["name"]: c for c in cards}

    assert "师门任务" in cards_dict
    assert cards_dict["师门任务"]["is_done"] is False
    assert cards_dict["师门任务"]["current_cnt"] == 0
    assert cards_dict["师门任务"]["max_cnt"] == 10
    assert cards_dict["师门任务"]["join_btn"] == (1077.0, 148.0)

    assert "宝图任务" in cards_dict
    assert cards_dict["宝图任务"]["is_done"] is True
    assert cards_dict["宝图任务"]["current_cnt"] == 10
    assert cards_dict["宝图任务"]["max_cnt"] == 10

    assert "运镖" in cards_dict
    assert cards_dict["运镖"]["is_done"] is False
    assert cards_dict["运镖"]["current_cnt"] == 0
    assert cards_dict["运镖"]["max_cnt"] == 3
    assert cards_dict["运镖"]["join_btn"] == (669.0, 377.0)


def test_handle_activity_panel_dispatches_first_uncompleted_task():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "宝图任务", "运镖"]
    ctx.variables["completed_tasks"] = []
    # Panel already fully scanned: dispatch may proceed without scrolling.
    ctx.variables["panel_scroll_count"] = 6

    items = [
        DummyOCRItem("师门任务", (883.0, 122.0)),
        DummyOCRItem("参加", (1077.0, 148.0)),
        DummyOCRItem("次数0/10活跃0/20", (921.0, 178.0)),

        DummyOCRItem("宝图任务", (883.0, 236.0)),
        DummyOCRItem("参加", (1077.0, 263.0)),
        DummyOCRItem("次数0/10", (921.0, 291.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    # Should click 参加 on 师门任务 @ (1077, 148)
    assert len(device.clicks) == 1
    assert device.clicks[0] == (1077.0, 148.0)
    assert ctx.variables.get("current_task_name") == "师门任务"


def test_handle_activity_panel_claims_chests_when_all_completed():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "宝图任务"]
    ctx.variables["completed_tasks"] = ["师门任务", "宝图任务"]

    items = [
        DummyOCRItem("师门任务", (883.0, 122.0)),
        DummyOCRItem("已完成", (921.0, 178.0)),
        DummyOCRItem("宝图任务", (883.0, 236.0)),
        DummyOCRItem("已完成", (921.0, 291.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    # Should click 5 activity chests + close panel button
    assert len(device.clicks) == 6
    chest_coords = [(457.0, 570.0), (609.0, 570.0), (760.0, 570.0), (911.0, 570.0), (1063.0, 570.0)]
    for i, c in enumerate(chest_coords):
        assert device.clicks[i] == c
    assert device.clicks[5] == (float(PANEL_CLOSE[0]), float(PANEL_CLOSE[1]))
    assert ctx.variables.get("all_dailies_done") is True


def test_unparsed_queued_task_keeps_the_day_open():
    """回归 2026-09-27：科举乡试卡片始终没被 OCR 读到、三界奇缘读到但 0/10，
    收尾逻辑仍把 all_dailies_done 置真并走 daily_finish，当天不再回来做它们。
    队列里还有未完成项时只能关面板，不能宣布今日完成。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["科举乡试", "三界奇缘"]
    ctx.variables["current_huoyue"] = 47
    items = [
        DummyOCRItem("三界奇缘", (594.0, 371.0)),
        DummyOCRItem("次数0/10", (582.0, 442.0)),
        DummyOCRItem("活跃0/10", (701.0, 442.0)),
    ]
    ctx.variables["_last_frame_items"] = items
    ctx.variables["_last_frame"] = None

    handle_activity_panel(ctx, NodeAction(type="custom", custom_func="handle_activity_panel"))

    assert "科举乡试" not in ctx.variables["completed_tasks"]
    assert "三界奇缘" not in ctx.variables["completed_tasks"]
    assert ctx.variables.get("all_dailies_done") is not True
    # 科举从未读到，应滚动面板继续找，而不是关面板宣布完成。
    assert device.clicks == []
    assert ctx.variables.get("panel_scroll_count") == 1
    assert device.swipes


def test_classify_screen_shop_and_dialog_states():
    ctx = PipelineContext()
    frame = None

    # Test Shop Open (with close button × present)
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("×", (1143.0, 49.0)),
            DummyOCRItem("天蚕丝带", (323.0, 146.0)),
            DummyOCRItem("购买数量", (853.0, 392.0)),
            DummyOCRItem("购买", (972.0, 586.0)),
        ]
        classify_screen(ctx, frame)
        assert ctx.variables["shop_open"] is True
        assert ctx.variables["popup_open"] is False  # Functional shop must NOT be misclassified as generic popup
        assert ctx.variables["in_battle"] is False
        assert ctx.variables["turnin_open"] is False

    # Test Turn-in Open (with close button × present)
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("×", (1143.0, 49.0)),
            DummyOCRItem("请上交所需物品", (600.0, 200.0)),
            DummyOCRItem("上交", (1059.0, 593.0)),
        ]
        classify_screen(ctx, frame)
        assert ctx.variables["turnin_open"] is True
        assert ctx.variables["popup_open"] is False  # Functional turnin must NOT be misclassified as generic popup
        assert ctx.variables["shop_open"] is False

    # Test Auto Walking
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("自动寻路中", (746.0, 333.0)),
            DummyOCRItem("师门-阴晴圆缺（2/10）", (1151.0, 195.0)),
        ]
        classify_screen(ctx, frame)
        assert ctx.variables["auto_walking"] is True
        assert ctx.variables["tracker_active"] is True


def test_interaction_handlers_shop_turnin_dialog():
    device = DummyDevice()
    ctx = PipelineContext(device=device)

    # 1. Shop Buy
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("血色茶花", (323.0, 146.0)),
        DummyOCRItem("购买", (972.0, 586.0)),
    ]
    click_shop_buy(ctx, NodeAction(type="custom", custom_func="click_shop_buy"))
    assert device.clicks[-1] == (972.0, 586.0)

    # 2. Turn-in
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("上交", (850.0, 480.0)),
    ]
    click_turnin(ctx, NodeAction(type="custom", custom_func="click_turnin"))
    assert device.clicks[-1] == (850.0, 480.0)

    # 3. Use Item
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("藏宝图", (640.0, 300.0)),
        DummyOCRItem("使用", (720.0, 520.0)),
    ]
    click_use_item(ctx, NodeAction(type="custom", custom_func="click_use_item"))
    assert device.clicks[-1] == (720.0, 520.0)

    # 4. Dialog Choice
    ctx.variables["current_task_name"] = "师门任务"
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("请选择要做的事：", (1025.0, 388.0)),
        DummyOCRItem("师门集物-阴晴圆缺", (1086.0, 468.0)),
    ]
    click_dialog_choice(ctx, NodeAction(type="custom", custom_func="click_dialog_choice"))
    assert device.clicks[-1] == (1086.0, 468.0)

    # 5. Task Tracker
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("师门-阴晴圆缺（3/10）", (1151.0, 195.0)),
        DummyOCRItem("买个天蚕丝带给白姑娘", (1146.0, 229.0)),
    ]
    click_task_tracker(ctx, NodeAction(type="custom", custom_func="click_task_tracker"))
    assert device.clicks[-1] == (1151.0, 195.0)


def test_classify_screen_panel_open_without_close_button():
    ctx = PipelineContext()
    frame = None

    # Activity panel open without '×' button detected by OCR
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("活 动", (639.0, 47.0)),
            DummyOCRItem("日常活动", (216.0, 123.0)),
            DummyOCRItem("运镖", (450.0, 236.0)),
            DummyOCRItem("参加", (669.0, 263.0)),
            DummyOCRItem("20活跃", (457.0, 570.0)),
            DummyOCRItem("40活跃", (609.0, 570.0)),
        ]
        classify_screen(ctx, frame)
        assert ctx.variables["panel_open"] is True
        assert ctx.variables["need_open_panel"] is False
        assert ctx.variables["in_battle"] is False


def test_extract_huoyue():
    items = [
        DummyOCRItem("活 动", (639.0, 47.0)),
        DummyOCRItem("日常活动", (216.0, 123.0)),
        DummyOCRItem("30", (534.5, 632.0)),
        DummyOCRItem("20活跃", (457.0, 570.0)),
        DummyOCRItem("40活跃", (609.0, 570.0)),
    ]
    assert _extract_huoyue(items) == 30

    items_text = [
        DummyOCRItem("当前活跃度 55 点", (600.0, 630.0)),
    ]
    assert _extract_huoyue(items_text) == 55

    empty_items = [
        DummyOCRItem("杂项文本", (100.0, 100.0)),
    ]
    assert _extract_huoyue(empty_items) == 0


def test_handle_activity_panel_abandons_escort_when_all_done_and_huoyue_under_50():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "宝图任务", "运镖"]
    ctx.variables["completed_tasks"] = []
    # Panel already fully scanned (both scrolls used): terminal close-out must run.
    ctx.variables["panel_scroll_count"] = 6

    # Shimen & Baotu already completed, Escort is visible with 参加 button
    # But current huoyue is 30 (< 50 required for 运镖)
    items = [
        DummyOCRItem("运镖", (450.0, 236.0)),
        DummyOCRItem("参加", (669.0, 263.0)),
        DummyOCRItem("次数0/3", (461.0, 292.0)),
        DummyOCRItem("30", (534.5, 632.0)),
        DummyOCRItem("20活跃", (457.0, 570.0)),
        DummyOCRItem("40活跃", (609.0, 570.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    # Escort was deferred during dispatch (no other task left to raise huoyue),
    # then terminally abandoned at the chest path for this run.
    assert ctx.variables.get("escort_deferred") is True
    assert "运镖" in ctx.variables["completed_tasks"]
    # 师门/宝图 never appeared on the panel, so they stay unfinished for the next
    # pass instead of being declared done on an OCR miss (live 2026-09-26).
    assert "师门任务" not in ctx.variables["completed_tasks"]
    assert "宝图任务" not in ctx.variables["completed_tasks"]
    # 师门/宝图 were never parsed, so the day stays open for the next pass instead of
    # being declared done on an OCR miss (live 2026-09-27: 科举乡试 never seen, yet
    # all_dailies_done ended the run).
    assert ctx.variables.get("all_dailies_done") is not True

    # Chests are not claimed while tasks are still queued; the panel is just closed.
    assert (457.0, 570.0) not in device.clicks
    # 40, 60, 80, 100 chests are locked and should not be clicked
    assert (609.0, 666.0) not in device.clicks
    assert device.clicks[-1] == (float(PANEL_CLOSE[0]), float(PANEL_CLOSE[1]))


def test_handle_activity_panel_defers_escort_and_dispatches_next_task():
    """活跃度不足 50 时运镖被延迟（不得永久标记完成），队列后续任务照常派发。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "运镖", "宝图任务"]
    ctx.variables["completed_tasks"] = ["师门任务"]

    items = [
        DummyOCRItem("运镖", (450.0, 236.0)),
        DummyOCRItem("参加", (669.0, 263.0)),
        DummyOCRItem("次数0/3", (461.0, 292.0)),
        DummyOCRItem("宝图任务", (450.0, 352.0)),
        DummyOCRItem("参加", (669.0, 377.0)),
        DummyOCRItem("次数0/10", (461.0, 406.0)),
        DummyOCRItem("30", (534.5, 632.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    # 宝图 dispatched instead; escort deferred, NOT marked completed
    assert (669.0, 377.0) in device.clicks
    assert "运镖" not in ctx.variables["completed_tasks"]
    assert ctx.variables.get("escort_deferred") is True
    assert ctx.variables.get("current_task_name") == "宝图任务"
    assert ctx.variables.get("all_dailies_done") is not True


def test_handle_activity_panel_retries_escort_when_huoyue_reaches_50():
    """其余日常推高活跃度后，延迟的运镖在后续面板访问被补跑派发。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "宝图任务", "秘境降妖", "运镖"]
    ctx.variables["completed_tasks"] = ["师门任务", "宝图任务", "秘境降妖"]
    ctx.variables["escort_deferred"] = True

    items = [
        DummyOCRItem("运镖", (450.0, 236.0)),
        DummyOCRItem("参加", (669.0, 263.0)),
        DummyOCRItem("次数0/3", (461.0, 292.0)),
        DummyOCRItem("60", (534.5, 632.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    assert (669.0, 263.0) in device.clicks
    assert ctx.variables.get("current_task_name") == "运镖"
    assert ctx.variables.get("escort_deferred") is False
    assert "运镖" not in ctx.variables["completed_tasks"]
    assert ctx.variables.get("all_dailies_done") is not True


def test_handle_activity_panel_escort_fallback_row_when_card_missing():
    """活跃度达标但运镖卡片漏解析（面板滚动/OCR 漏检）：按未滚动固定行坐标兜底点参加。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "宝图任务", "秘境降妖", "运镖"]
    ctx.variables["completed_tasks"] = ["师门任务", "宝图任务", "秘境降妖"]
    # Panel already fully scanned (both scrolls used): fixed-row fallback is legitimate.
    ctx.variables["panel_scroll_count"] = 6

    items = [
        DummyOCRItem("60", (534.5, 632.0)),
        DummyOCRItem("20活跃", (457.0, 570.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    # Tick 1: scrolled panel → scroll back to top; Tick 2: fixed-row fallback fires.
    handle_activity_panel(ctx, act)
    handle_activity_panel(ctx, act)

    assert (float(ESCORT_JOIN[0]), float(ESCORT_JOIN[1])) in device.clicks
    # chests must NOT be claimed and panel must not be closed in this tick
    assert (457.0, 570.0) not in device.clicks
    assert ctx.variables.get("all_dailies_done") is not True


def test_handle_activity_panel_dispatches_escort_when_huoyue_above_50():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "宝图任务", "运镖"]
    ctx.variables["completed_tasks"] = ["师门任务", "宝图任务"]

    items = [
        DummyOCRItem("运镖", (450.0, 236.0)),
        DummyOCRItem("参加", (669.0, 263.0)),
        DummyOCRItem("次数0/3", (461.0, 292.0)),
        DummyOCRItem("55", (534.5, 632.0)),
        DummyOCRItem("20活跃", (457.0, 570.0)),
        DummyOCRItem("40活跃", (609.0, 570.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    # 55 huoyue >= 50: 运镖 should be started via 参加 button @ (669, 263)
    assert len(device.clicks) == 1
    assert device.clicks[0] == (669.0, 263.0)
    assert ctx.variables.get("current_task_name") == "运镖"
    assert ctx.variables.get("all_dailies_done") is not True


def test_classify_screen_intercepts_huoyue_toast():
    ctx = PipelineContext()
    frame = None

    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("运镖需要活跃度达到50点你的活跃度不够", (640.0, 360.0)),
            DummyOCRItem("快去提升活跃度吧。", (640.0, 390.0)),
        ]
        classify_screen(ctx, frame)
        assert "运镖" in ctx.variables["completed_tasks"]
        assert ctx.variables["current_task_done"] is True


def test_mijing_undone_card_re_dispatches_until_full():
    """秘境 次数5/10 未打满且参加按钮可见：必须继续派发，不得提前标记完成。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "宝图任务", "秘境降妖", "运镖"]
    ctx.variables["completed_tasks"] = ["师门任务", "宝图任务"]
    # Panel already fully scanned: re-dispatch may proceed without scrolling.
    ctx.variables["panel_scroll_count"] = 6

    items = [
        DummyOCRItem("秘境降妖", (450.0, 122.0)),
        DummyOCRItem("参加", (669.0, 148.0)),
        DummyOCRItem("次数5/10", (461.0, 178.0)),
        DummyOCRItem("30", (534.5, 632.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    assert device.clicks[0] == (669.0, 148.0)
    assert ctx.variables.get("current_task_name") == "秘境降妖"
    assert "秘境降妖" not in ctx.variables["completed_tasks"]
    assert ctx.variables.get("all_dailies_done") is not True


def test_classify_screen_intercepts_mijing_quota_toast():
    """挑战次数用完 Toast：标记秘境当日结束，防止打开面板-点参加-报错死循环。"""
    ctx = PipelineContext()
    frame = None

    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("秘境挑战次数已用完，明日再来", (640.0, 360.0)),
        ]
        classify_screen(ctx, frame)
        assert ctx.variables.get("mijing_quota_exhausted") is True
        assert "秘境降妖" in ctx.variables["completed_tasks"]
        assert ctx.variables["current_task_done"] is True


def test_panel_marks_mijing_finished_when_quota_exhausted():
    """次数用完标记生效后：秘境不再派发，按真实计数如实收尾。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "宝图任务", "秘境降妖", "运镖"]
    ctx.variables["completed_tasks"] = ["师门任务", "宝图任务"]
    ctx.variables["mijing_quota_exhausted"] = True
    # Panel already fully scanned (both scrolls used): terminal close-out must run.
    ctx.variables["panel_scroll_count"] = 6

    items = [
        DummyOCRItem("秘境降妖", (450.0, 122.0)),
        DummyOCRItem("参加", (669.0, 148.0)),
        DummyOCRItem("次数5/10", (461.0, 178.0)),
        DummyOCRItem("30", (534.5, 632.0)),
        DummyOCRItem("20活跃", (457.0, 570.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    # 秘境 join button must NOT be clicked again
    assert (669.0, 148.0) not in device.clicks
    assert "秘境降妖" in ctx.variables["completed_tasks"]
    assert ctx.variables.get("all_dailies_done") is True


def test_xianyu_dialog_never_confirmed_and_blocks_mijing():
    """秘境死亡弹窗（确定=花费仙玉复活）：绝不能点确定，走安全退出并阻断秘境派发。"""
    ctx = PipelineContext(device=DummyDevice())
    frame = None
    dialog_items = [
        DummyOCRItem("复活并继续挑战", (640.0, 300.0)),
        DummyOCRItem("花费20仙玉", (640.0, 330.0)),
        DummyOCRItem("确定", (760.0, 420.0)),
        DummyOCRItem("取消", (520.0, 420.0)),
    ]

    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = dialog_items
        classify_screen(ctx, frame)

    v = ctx.variables
    assert v.get("xianyu_cost_popup") is True
    # The centered 确定 must NOT be classified as deposit/use-item confirm
    assert v.get("deposit_open") is not True
    assert v.get("use_item_open") is not True
    assert v.get("popup_open") is True

    # dismiss_popups must take the safe exit, never the confirm button
    act = NodeAction(type="custom", custom_func="dismiss_popups")
    dismiss_popups(ctx, act)
    assert ctx.device.clicks == [(520.0, 420.0)]
    assert v.get("mijing_blocked") is True


def test_terminal_force_complete_warns_mijing_not_full():
    """终局兜底强制收尾时，必须如实告警秘境未打满（5/10）与活跃度缺口，不得静默。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["秘境降妖", "运镖"]
    ctx.variables["completed_tasks"] = []
    ctx.variables["current_huoyue"] = 0
    # Panel already fully scanned (both scrolls used): terminal close-out must run.
    ctx.variables["panel_scroll_count"] = 6
    ctx.variables["daily_rows_aligned"] = True

    items = [
        DummyOCRItem("秘境降妖", (450.0, 122.0)),
        DummyOCRItem("次数5/10", (461.0, 178.0)),
        DummyOCRItem("30", (534.5, 632.0)),
        DummyOCRItem("20活跃", (457.0, 570.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    with patch.object(dh, "logger") as mock_logger:
        handle_activity_panel(ctx, act)

    warn_texts = " ".join(str(c.args[0]) for c in mock_logger.warning.call_args_list if c.args)
    assert "5/10" in warn_texts
    assert "缺口" in warn_texts
    # Read at 5/10: stays unfinished for the next pass instead of being declared
    # done while its reward is untouched (live 2026-09-26).
    assert "秘境降妖" not in ctx.variables["completed_tasks"]
    assert "运镖" in ctx.variables["completed_tasks"]
    # 秘境 is still at 5/10, so the day stays open for the next pass rather than being
    # declared done with its reward untouched (live 2026-09-27).
    assert ctx.variables.get("all_dailies_done") is not True


def test_quiz_dispatched_before_escort_as_huoyue_fallback():
    """秘境打满后活跃度仍 <50：三界奇缘作为活跃度兜底源先于运镖派发。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "宝图任务", "秘境降妖", "三界奇缘", "运镖"]
    ctx.variables["completed_tasks"] = ["师门任务", "宝图任务", "秘境降妖"]

    items = [
        DummyOCRItem("三界奇缘", (450.0, 122.0)),
        DummyOCRItem("参加", (669.0, 148.0)),
        DummyOCRItem("答题赢奖励", (450.0, 149.0)),
        DummyOCRItem("运镖", (450.0, 236.0)),
        DummyOCRItem("参加", (669.0, 263.0)),
        DummyOCRItem("次数0/3", (461.0, 292.0)),
        DummyOCRItem("30", (534.5, 632.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    assert device.clicks[0] == (669.0, 148.0)
    assert ctx.variables.get("current_task_name") == "三界奇缘"
    assert ctx.variables.get("all_dailies_done") is not True




def test_activity_done_pill_marks_completed():
    """真实面板的完成态是绿色"完成"胶囊（无参加按钮），必须识别为已完成并解析活跃计数。"""
    items = [
        DummyOCRItem("秘境降妖", (890.0, 412.0)),
        DummyOCRItem("经验", (890.0, 440.0)),
        DummyOCRItem("次数不限", (846.0, 466.0)),
        DummyOCRItem("活跃11/25", (946.0, 466.0)),
        DummyOCRItem("完成", (1063.0, 435.0)),
    ]
    cards = {c["name"]: c for c in _parse_activity_panel(items)}
    mijing = cards["秘境降妖"]
    assert mijing["is_done"] is True
    assert mijing["h_current"] == 11
    assert mijing["h_max"] == 25
    assert mijing["join_btn"] is None


def test_mijing_honest_warning_when_pill_done_but_huoyue_partial():
    """秘境被游戏标"完成"但活跃 11/25：如实告警今日额度已用完，不得静默。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["秘境降妖"]
    ctx.variables["completed_tasks"] = []
    ctx.variables["panel_scroll_count"] = 6

    items = [
        DummyOCRItem("秘境降妖", (890.0, 412.0)),
        DummyOCRItem("次数不限", (846.0, 466.0)),
        DummyOCRItem("活跃11/25", (946.0, 466.0)),
        DummyOCRItem("完成", (1063.0, 435.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    with patch.object(dh, "logger") as mock_logger:
        handle_activity_panel(ctx, act)

    warn_texts = " ".join(str(c.args[0]) for c in mock_logger.warning.call_args_list if c.args)
    assert "11/25" in warn_texts
    assert "明日" in warn_texts
    assert "秘境降妖" in ctx.variables["completed_tasks"]
    assert ctx.variables.get("all_dailies_done") is True


def test_unparsed_card_not_force_completed():
    """回归 2026-09-26：滚动预算用尽仍没读到的卡片不得被标完成，面板先滚回顶部重判。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "三界奇缘"]
    ctx.variables["completed_tasks"] = []
    ctx.variables["panel_scroll_count"] = 6
    ctx.variables["panel_scrolled"] = True

    items = [
        DummyOCRItem("三界奇缘", (450.0, 122.0)),
        DummyOCRItem("活跃0/10", (461.0, 178.0)),
        DummyOCRItem("18", (534.5, 632.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    handle_activity_panel(ctx, NodeAction(type="custom", custom_func="handle_activity_panel"))

    assert device.swipes  # scrolled back toward the top
    assert ctx.variables.get("panel_scroll_count") == 0
    assert ctx.variables.get("panel_rescanned") is True
    assert "师门任务" not in ctx.variables["completed_tasks"]
    assert ctx.variables.get("all_dailies_done") is not True


def test_panel_scrolls_when_queued_card_missing():
    """队列任务不在可见卡片中（首屏之下）：先滚动面板下一 tick 再决策，不得直接终局。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["秘境降妖"]
    ctx.variables["completed_tasks"] = []

    items = [
        DummyOCRItem("运镖", (450.0, 122.0)),
        DummyOCRItem("参加", (669.0, 148.0)),
        DummyOCRItem("次数0/3", (461.0, 178.0)),
        DummyOCRItem("30", (534.5, 632.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    # 150px (420→270) rubber-bands back to the start (live 2026-09-27: mid-gesture
    # diff 11.56, after release 0.28). A ~120px nudge is what actually paginates.
    assert device.swipes == [(735.0, 420.0, 735.0, 300.0)]
    assert ctx.variables.get("panel_scroll_count") == 1
    assert "秘境降妖" not in ctx.variables["completed_tasks"]
    assert ctx.variables.get("all_dailies_done") is not True


def test_escort_fallback_guarded_when_panel_scrolled():
    """面板已滚动时固定行兜底坐标失效：先滚回顶部重扫，绝不盲点。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "运镖"]
    ctx.variables["completed_tasks"] = ["师门任务"]
    ctx.variables["panel_scroll_count"] = 6

    items = [
        DummyOCRItem("60", (534.5, 632.0)),
        DummyOCRItem("20活跃", (457.0, 570.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    # Tick 1: panel is scrolled — must NOT blind-click; scroll back to top instead
    assert (float(ESCORT_JOIN[0]), float(ESCORT_JOIN[1])) not in device.clicks
    assert device.swipes == [(735.0, 160.0, 735.0, 480.0)]
    assert ctx.variables.get("panel_scroll_count") == 6  # budget stays spent
    assert ctx.variables.get("escort_scrollback_done") is True
    assert ctx.variables.get("all_dailies_done") is not True

    # Tick 2 (panel back at top): now the fixed-row fallback may click 参加
    handle_activity_panel(ctx, act)
    assert (float(ESCORT_JOIN[0]), float(ESCORT_JOIN[1])) in device.clicks


def test_extract_huoyue_from_frame_green_bar():
    """OCR 读不到活跃度气泡时，按绿色填充宽度换算（326..1067 → 0..100）。"""
    import numpy as np

    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    # green fill up to x=631 (41%) in BGR: G dominant over both B and R
    frame[618:648, 326:632] = (60, 180, 40)
    assert _extract_huoyue_from_frame(frame) == 41

    # empty bar and full bar
    empty = np.zeros((720, 1280, 3), dtype=np.uint8)
    assert _extract_huoyue_from_frame(empty) == 0
    frame[618:648, 326:1068] = (60, 180, 40)
    assert _extract_huoyue_from_frame(frame) == 100

    # no frame at all
    assert _extract_huoyue_from_frame(None) == 0


def test_classify_screen_intercepts_quota_toast_live_wording():
    """实机 Toast 原文「少侠今日已无挑战次数，明日再来吧」必须被拦截。"""
    ctx = PipelineContext()
    frame = None

    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("少侠今日已无挑战次数，明日再来吧", (640.0, 360.0)),
        ]
        classify_screen(ctx, frame)
        assert ctx.variables.get("mijing_quota_exhausted") is True
        assert "秘境降妖" in ctx.variables["completed_tasks"]


def test_quit_game_confirm_dialog_never_confirmed():
    """双击返回触发的退出游戏确认弹窗：确定=退出客户端，绝不能点，必须取消。"""
    ctx = PipelineContext(device=DummyDevice())
    frame = None
    dialog_items = [
        DummyOCRItem("再提升59点活跃度即可获得1000金币", (700.0, 460.0)),
        DummyOCRItem("少侠确定离开游戏吗?", (700.0, 490.0)),
        DummyOCRItem("取 消", (596.0, 535.0)),
        DummyOCRItem("确 定", (834.0, 533.0)),
    ]

    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = dialog_items
        classify_screen(ctx, frame)

    v = ctx.variables
    assert v.get("quit_game_confirm") is True
    assert v.get("deposit_open") is not True
    assert v.get("popup_open") is True

    act = NodeAction(type="custom", custom_func="dismiss_popups")
    dismiss_popups(ctx, act)
    # The spaced "取 消" must be normalized and clicked — NEVER the 确 定 button
    assert ctx.device.clicks == [(596.0, 535.0)]
    assert v.get("mijing_blocked") is not True


def test_mijing_dialog_option_high_band_clicked():
    """云乐游 NPC 对话选项位置偏高（秘境降妖 y≈264）：必须点中它而不是规则说明。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["current_task_name"] = "秘境降妖"
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("请选择要做的事：", (1085.0, 185.0)),
        DummyOCRItem("秘境降妖", (1088.0, 264.0)),
        DummyOCRItem("东海湾蜃境", (1088.0, 332.0)),
        DummyOCRItem("规则说明", (1088.0, 398.0)),
        DummyOCRItem("蜃境图鉴", (1088.0, 465.0)),
    ]

    act = NodeAction(type="custom", custom_func="click_dialog_choice")
    click_dialog_choice(ctx, act)

    assert device.clicks == [(1088.0, 264.0)]


def test_panel_recognized_without_tab_labels():
    """回归 2026-09-26：页签文字被 OCR 粘连时，靠多张日常卡片 + 活跃度条仍要认出活动面板。"""
    ctx = PipelineContext()
    items = [
        DummyOCRItem("捉鬼任务", (541.0, 217.0)),
        DummyOCRItem("次数不限活跃0/20", (580.0, 248.0)),
        DummyOCRItem("宝图任务", (541.0, 303.0)),
        DummyOCRItem("次数0/10活跃0/10", (580.0, 334.0)),
        DummyOCRItem("运镖", (817.0, 303.0)),
        DummyOCRItem("今日活跃20", (472.0, 173.0)),
    ]
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=items):
        classify_screen(ctx, None)
    assert ctx.variables["panel_open"] is True
    assert ctx.variables["need_open_panel"] is not True


def test_reward_summary_confirmed_not_backed_out():
    """回归 2026-09-26：师门任务完成结算页要点「确定」领奖，返回键会弹出退出游戏确认。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    items = [
        DummyOCRItem("师门任务完成", (630.0, 222.0)),
        DummyOCRItem("人物经验501042", (523.0, 297.0)),
        DummyOCRItem("确定", (639.0, 555.0)),
    ]
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=items):
        classify_screen(ctx, None)
    assert ctx.variables["popup_open"] is True
    assert ctx.variables["fullscreen_popup"] is True

    ctx.variables["_last_frame_items"] = items
    dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert device.clicks == [(639.0, 555.0)]
    assert device.keys == []


def test_season_event_page_closed_with_back_key():
    """回归 2026-09-26：九转天阶赛季全屏页没有可点的 ×，用返回键关闭。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    items = [
        DummyOCRItem("九转天阶·第61赛季", (800.0, 105.0)),
        DummyOCRItem("全新赛季正式开启！", (822.0, 149.0)),
        DummyOCRItem("立即前往", (640.0, 614.0)),
    ]
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=items):
        classify_screen(ctx, None)
    assert ctx.variables["popup_open"] is True

    ctx.variables["_last_frame_items"] = items
    dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert device.clicks == []  # the 立即前往 CTA is never taken
    assert 4 in device.keys


def test_merged_topbar_blob_taps_activity_not_ranking():
    """回归 2026-09-26：顶栏「活动排行挂机」被合成一条时，点左端的活动，不点中心的排行。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    blob = DummyOCRItem("活动排行挂机", (427.0, 65.0))
    blob.bbox = (300, 50, 250, 30)  # center would be x≈425, the 排行 button
    ctx.variables["_last_frame_items"] = [blob]

    open_activity_panel(ctx, NodeAction(type="custom", custom_func="open_activity_panel"))

    assert device.clicks == [(330.0, 65.0)]


def test_ranking_page_not_tapped_as_activity_button():
    """回归 2026-09-26：排行榜侧栏文字不得被当成顶栏活动按钮，排行榜按弹窗关闭。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ranking = [
        DummyOCRItem("排行榜", (157.0, 28.0)),
        DummyOCRItem("×", (1217.0, 38.0)),
        DummyOCRItem("帮派榜", (177.0, 593.0)),
    ]
    ctx.variables["_last_frame_items"] = ranking

    open_activity_panel(ctx, NodeAction(type="custom", custom_func="open_activity_panel"))
    # Fell back to the fixed top-bar coordinate — the sidebar text was not tapped.
    assert (177.0, 593.0) not in device.clicks
    assert device.clicks[-1] == (float(TOPBAR_ACTIVITY[0]), float(TOPBAR_ACTIVITY[1]))

    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = ranking
        classify_screen(ctx, None)
    assert ctx.variables["popup_open"] is True

    # Its corner × does not register; the page closes via the back key.
    device.clicks.clear()
    ctx.variables["_last_frame_items"] = ranking
    dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert device.clicks == []
    assert 4 in device.keys


def test_baotu_dialog_picks_high_band_not_recruit_hall():
    """回归 2026-09-26：宝图对话的打听选项在 y≈265，不得落到「招募大厅」。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["current_task_name"] = "宝图任务"
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("请选择要做的事：", (1025.0, 200.0)),
        DummyOCRItem("打听藏宝图", (1086.0, 265.0)),
        DummyOCRItem("浏览三界论坛", (1086.0, 399.0)),
        DummyOCRItem("招募大厅", (1084.0, 465.0)),
    ]
    click_dialog_choice(ctx, NodeAction(type="custom", custom_func="click_dialog_choice"))
    assert device.clicks == [(1086.0, 265.0)]


def test_forum_option_never_clicked_and_forum_page_closes():
    """回归 2026-09-26：NPC 对话的「浏览三界论坛」会打开论坛网页，不得点；论坛页用返回键关。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["current_task_name"] = "宝图任务"
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("请选择要做的事：", (1025.0, 320.0)),
        DummyOCRItem("浏览三界论坛", (1086.0, 399.0)),
    ]
    click_dialog_choice(ctx, NodeAction(type="custom", custom_func="click_dialog_choice"))
    assert all("论坛" not in str(c) for c in device.clicks)
    assert (1086.0, 399.0) not in device.clicks

    forum = [
        DummyOCRItem("论坛", (788.0, 96.0)),
    ]
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=forum):
        classify_screen(ctx, None)
    assert ctx.variables["popup_open"] is True
    ctx.variables["_last_frame_items"] = forum
    device.keys.clear()
    dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert 4 in device.keys


def test_roaming_xingxiu_dialog_closed_during_daily():
    """回归 2026-09-26：日常进行中路过的二十八星宿弹窗不得被点「进入战斗」，直接关掉。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["current_task_name"] = "师门任务"
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("星宿", (717.0, 362.0)),
        DummyOCRItem("请选择要做的事：", (1025.0, 387.0)),
        DummyOCRItem("进入战斗", (1085.0, 468.0)),
    ]

    click_dialog_choice(ctx, NodeAction(type="custom", custom_func="click_dialog_choice"))

    assert device.clicks == []
    assert 4 in device.keys  # back key closes the roaming-boss dialog


def test_guide_popup_dismissed_not_dialog_routed():
    """答题结束后的指引弹窗（通关推荐配置+前往提升）：必须按弹窗关闭，不得被对话路由点 CTA。"""
    ctx = PipelineContext(device=DummyDevice())
    frame = None
    guide_items = [
        DummyOCRItem("指 引", (640.0, 45.0)),
        DummyOCRItem("通关推荐配置：", (530.0, 125.0)),
        DummyOCRItem("前往提升", (1006.0, 359.0)),
        DummyOCRItem("前往提升", (1006.0, 355.0)),
        DummyOCRItem("挑战", (1152.0, 370.0)),
        DummyOCRItem("×", (1143.0, 113.0)),
    ]

    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = guide_items
        classify_screen(ctx, frame)

    v = ctx.variables
    assert v.get("guide_popup") is True
    assert v.get("dialog_open") is not True
    assert v.get("popup_open") is True

    act = NodeAction(type="custom", custom_func="dismiss_popups")
    dismiss_popups(ctx, act)
    assert ctx.device.clicks == [(1143.0, 113.0)]  # closed via ×, CTA never clicked


def test_no_false_completion_for_below_fold_tasks():
    """回归 P1：未滚动面板上运镖可见且达标时，折叠区未做的师门绝不能被误标完成。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["daily_queue"] = ["师门任务", "运镖"]
    ctx.variables["completed_tasks"] = []
    ctx.variables["panel_scroll_count"] = 0  # budget available -> must scroll first

    items = [
        DummyOCRItem("运镖", (450.0, 122.0)),
        DummyOCRItem("参加", (669.0, 148.0)),
        DummyOCRItem("次数0/3", (461.0, 178.0)),
        DummyOCRItem("60", (534.5, 632.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="handle_activity_panel")
    handle_activity_panel(ctx, act)

    # 运镖 is on screen with a 参加 button, so it is dispatched now instead of burning
    # the scroll budget on the still-unseen 师门 (live 2026-09-27: 三界奇缘 was visible
    # and startable but never clicked while the scan hunted for 科举乡试).
    assert device.clicks == [(669.0, 148.0)]
    assert device.swipes == []
    assert "师门任务" not in ctx.variables["completed_tasks"]
    assert "运镖" not in ctx.variables["completed_tasks"]
    assert ctx.variables.get("all_dailies_done") is not True


def test_guild_recruit_page_is_not_quiz():
    """回归 2026-09-26：战斗结算后的帮派推荐页（加入帮派/推荐帮派/申请入帮）
    标题落在答题 ROI、申请按钮落在选项 ROI，被当成题目+选项盲点 171 次。

    实机 OCR：标题「加入帮派」在 (659,79)，「推荐帮派」在 (946,120)，
    「申请入帮」在 (1037,231)，关闭按钮是「本周不再提醒」(268,661)。
    """
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["current_task_name"] = "宝图任务"
    guild = [
        DummyOCRItem("加入帮派", (659.0, 79.0)),
        DummyOCRItem("结识更多朋友，获得帮派技能，体验特色玩法", (475.0, 122.0)),
        DummyOCRItem("推荐帮派", (946.0, 120.0)),
        DummyOCRItem("帮派技能", (475.0, 172.0)),
        DummyOCRItem("申请入帮", (1037.0, 231.0)),
        DummyOCRItem("申请入帮", (1037.0, 359.0)),
        DummyOCRItem("申请入帮", (1037.0, 488.0)),
        DummyOCRItem("本周不再提醒", (268.0, 661.0)),
    ]
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=guild):
        classify_screen(ctx, None)
    assert ctx.variables["quiz_open"] is False
    assert ctx.variables["popup_open"] is True

    ctx.variables["_last_frame_items"] = guild
    dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    # 本周不再提醒 is a checkbox and tapping outside the card does nothing;
    # the back key is what actually closes it (live 2026-09-26).
    assert 4 in device.keys
    assert device.clicks == []


def test_gacha_page_is_popup_not_dialog():
    """回归 2026-09-27：百宠仙池祈愿页的按钮（祈愿1次/祈愿10次）落在对话选项列，
    通用对话回退连点 18 次把它打开，差点花掉仙玉。必须识别为弹窗并用返回键关闭，
    绝不点页内任何按钮。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["current_task_name"] = "秘境降妖"
    gacha = [
        DummyOCRItem("百宠仙池", (207.0, 232.0)),
        DummyOCRItem("五星·云霜", (691.0, 460.0)),
        DummyOCRItem("祈愿1次", (637.0, 670.0)),
        DummyOCRItem("祈愿10次", (1004.0, 669.0)),
        DummyOCRItem("召唤灵卡册", (1381.0, 626.0)),
        DummyOCRItem("请适度娱乐理性消费", (793.0, 845.0)),
    ]
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=gacha):
        classify_screen(ctx, None)
    assert ctx.variables["dialog_open"] is False
    assert ctx.variables["popup_open"] is True

    ctx.variables["_last_frame_items"] = gacha
    dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert 4 in device.keys
    assert device.clicks == []


def test_item_tooltip_is_turnin_not_quiz():
    """回归 2026-09-27：师门上交提示框（任务物品选择 风火圈 类型：环圈）标题落在
    答题 ROI、属性行落在选项 ROI，且带「上交」按钮，被当成题目+选项盲点第一个选项。

    实机 OCR：头部「风火圈」(602,107)/「任务物品选择」(1056,106)、
    属性行 y∈[209,378]、上交按钮 (1059,593)。
    输出必须是上交而不是答题，否则上交会永远盲点第一个「选项」。
    """
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["current_task_name"] = "师门任务"
    tooltip = [
        DummyOCRItem("风火圈", (602.0, 107.0)),
        DummyOCRItem("任务物品选择", (1056.0, 106.0)),
        DummyOCRItem("类型：环圈", (615.0, 135.0)),
        DummyOCRItem("等级：40", (604.0, 163.0)),
        DummyOCRItem("基础属性", (516.0, 209.0)),
        DummyOCRItem("物理伤害+234", (566.0, 243.0)),
        DummyOCRItem("法术伤害+53", (561.0, 277.0)),
        DummyOCRItem("治疗强度+61", (560.0, 310.0)),
        DummyOCRItem("耐久度：200", (532.0, 345.0)),
        DummyOCRItem("评分：236", (522.0, 378.0)),
        DummyOCRItem("上交", (1059.0, 593.0)),
    ]
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=tooltip):
        classify_screen(ctx, None)
    assert ctx.variables["turnin_open"] is True
    assert ctx.variables["quiz_open"] is False

    ctx.variables["_last_frame_items"] = tooltip
    click_turnin(ctx, NodeAction(type="custom", custom_func="click_turnin"))
    # 上交 button was the live target; clicking it (scaled) is the delivery.
    assert device.clicks == [(1059.0, 593.0)]


def test_stall_window_is_shop_not_quiz():
    """回归 2026-09-26：摆摊界面的页签和商品行落在答题 ROI 里，不得再路由成答题。

    实机 OCR：标题「摆摊」在 (663,42)，页签「我要出售/公示物品」在 y≈105，
    商品名「珍露酒」在选项区，「购买」在 (1010,656)。
    """
    ctx = PipelineContext()
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("摆摊·", (663.0, 42.0)),
            DummyOCRItem("我要购买", (271.0, 105.0)),
            DummyOCRItem("我要出售", (454.0, 105.0)),
            DummyOCRItem("公示物品", (641.0, 105.0)),
            DummyOCRItem("珍露酒·5160→", (897.0, 104.0)),
            DummyOCRItem("珍露酒", (525.0, 307.0)),
            DummyOCRItem("珍露酒", (525.0, 422.0)),
            DummyOCRItem("购买", (1010.0, 656.0)),
        ]
        classify_screen(ctx, None)
    assert ctx.variables["quiz_open"] is False
    assert ctx.variables["shop_open"] is True


def test_quiz_done_route_requires_quiz_context():
    """其他界面的「明日再来」不得误路由成答题完成页（需同时出现答题上下文标记）。"""
    ctx = PipelineContext()
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("今日已完成", (640.0, 300.0)),
            DummyOCRItem("明日再来", (640.0, 360.0)),
        ]
        classify_screen(ctx, None)
    assert ctx.variables["quiz_open"] is False


def test_escort_dialog_clicks_option_not_narration():
    """回归 2026-09-27：郑镖头旁白整句包含「押送普通镖银」，中心 (793,617)、x>700，
    关键词子串匹配会点到句子上。必须点右列普通镖选项 (1086,400)，绝不是高级镖。

    旁白写在选项前面，_find 返回第一命中，所以顺序本身就是失败条件。
    """
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["current_task_name"] = "运镖"
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("请选择要做的事：", (1085.0, 185.0)),
        DummyOCRItem("最近好多镖车要押送，少侠要帮忙运镖吗？成功押送普通镖银除了返还", (793.0, 617.0)),
        DummyOCRItem("押送普通镖银", (1086.0, 400.0)),
        DummyOCRItem("押送高级镖银（有难度）", (1081.0, 467.0)),
    ]

    click_dialog_choice(ctx, NodeAction(type="custom", custom_func="click_dialog_choice"))

    assert device.clicks == [(1086.0, 400.0)]


def test_deposit_requires_escort_wording():
    """押金确认的「确定」本身不含押金；正文「交付押金30000，押送1趟普通镖银？」是另一条 OCR。
    只有两者同时在场才是押金框。落在同一带里、但没有押金/押送文字的「确定」不得确认。
    且在押金弹窗存在时，即便有浮动系统公告，也绝不能被误判为答题 (quiz_open=False)。
    """
    ctx = PipelineContext()
    deposit = [
        DummyOCRItem("交付押金30000，押送1趟普通镖银？", (640.0, 360.0)),
        DummyOCRItem("取消", (596.0, 419.0)),
        DummyOCRItem("确定", (747.0, 419.0)),
        # 模拟飘屏公告穿过 QUIZ_QUESTION_ROI
        DummyOCRItem("026盛夏百宝阁坐骑小获得自选隐藏款坐骑礼盒双生之运综任务", (600.0, 80.0)),
        DummyOCRItem("选项A", (700.0, 220.0)),
        DummyOCRItem("选项B", (700.0, 300.0)),
    ]
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=deposit):
        classify_screen(ctx, None)
    assert ctx.variables["deposit_open"] is True
    assert ctx.variables["quiz_open"] is False

    bare = PipelineContext()
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=[
        DummyOCRItem("确定", (747.0, 419.0)),
    ]):
        classify_screen(bare, None)
    assert bare.variables.get("deposit_open") is not True


def test_jianhui_popup_closed_at_fixed_point_not_signup():
    """回归 2026-09-27：剑会群雄报名弹窗。短标题在 (666,270)，「5v5团队竞赛」在 (665,327)，
    「报名」在 (670,680)。关闭点是 (1100,60)；点报名会真的报名，点面板关闭 (1142,48) 关不掉。

    quiz_open 优先级高于 popup_open，所以弹窗还必须从答题里否决掉。
    """
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    popup = [
        DummyOCRItem("剑会群雄", (666.0, 270.0)),
        DummyOCRItem("5v5团队竞赛", (665.0, 327.0)),
        DummyOCRItem("优先新服互相匹配", (750.0, 627.0)),
        DummyOCRItem("报名", (670.0, 680.0)),
    ]
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=popup):
        classify_screen(ctx, None)
    assert ctx.variables["popup_open"] is True
    assert ctx.variables["quiz_open"] is False

    ctx.variables["_last_frame_items"] = popup
    dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert device.clicks == [(1100.0, 60.0)]


def test_jianhui_chat_sentence_is_not_popup():
    """世界频道整句「…在剑会群雄中达到先锋一级段位…」不是弹窗。误判会在主界面按返回，
    连按两次就是退出游戏确认。"""
    ctx = PipelineContext()
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=[
        DummyOCRItem("指引排行挂机社群直播录像", (640.0, 40.0)),
        DummyOCRItem("恭喜少侠在剑会群雄中达到先锋一级段位", (640.0, 660.0)),
    ]):
        classify_screen(ctx, None)
    assert ctx.variables.get("popup_open") is not True


def test_keju_skipped_on_weekend_still_scanned_on_weekday():
    """科举乡试周六日四个页签都没有。把它留在 missing_queued 里会烧完 6 次滚动，
    每次扫的还是同一屏。周末直接记完成；工作日仍要滚动去找。"""
    import datetime as _dt

    class _Sunday(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 27)  # Sunday

    class _Monday(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 28)  # Monday

    def _panel(today):
        device = DummyDevice()
        ctx = PipelineContext(device=device)
        ctx.variables["daily_queue"] = ["科举乡试"]
        ctx.variables["completed_tasks"] = []
        ctx.variables["_last_frame_items"] = [
            DummyOCRItem("运镖", (450.0, 122.0)),
            DummyOCRItem("参加", (669.0, 148.0)),
            DummyOCRItem("次数0/3", (461.0, 178.0)),
            DummyOCRItem("30", (534.5, 632.0)),
        ]
        with patch("plugins.mhxy_mobile.custom.daily_handlers.date", today):
            handle_activity_panel(ctx, NodeAction(type="custom", custom_func="handle_activity_panel"))
        return device, ctx

    sunday_device, sunday_ctx = _panel(_Sunday)
    assert sunday_device.swipes == []
    assert "科举乡试" in sunday_ctx.variables["completed_tasks"]

    monday_device, monday_ctx = _panel(_Monday)
    assert monday_device.swipes == [(735.0, 420.0, 735.0, 300.0)]
    assert "科举乡试" not in monday_ctx.variables["completed_tasks"]


def test_adb_swipe_duration_stays_under_adb_timeout():
    """steps=800 时 duration=steps*15=12000ms，超过 _run_adb 的 5 秒超时，手势发不出去。
    封顶 1500ms；默认 steps=25 仍是 375ms。"""
    from core.device.adb import AdbDevice

    captured = []

    class _Driver:
        def swipe(self, sx, sy, ex, ey, duration_ms=300):
            captured.append(duration_ms)

    device = AdbDevice(serial="127.0.0.1:1", auto_scale=False)
    device._driver = _Driver()

    device.swipe(735, 420, 735, 300, 800)
    device.swipe(735, 420, 735, 300, 25)
    assert captured[0] <= 1500
    assert captured[1] == 375


def test_time_gated_activity_does_not_steal_adjacent_join_btn():
    """回归 2026-09-28：活动面板中处于 11:00开启/17:00开启 的卡片（如三界奇缘/科举乡试）
    绝不能误吸取相邻或上方卡片的「参加」按钮，导致提前点击报错或错位触发。"""
    items = [
        DummyOCRItem("三界奇缘", (475.0, 182.0)),
        DummyOCRItem("11:00开启", (654.0, 179.0)),
        DummyOCRItem("经验", (447.0, 97.0)),
        DummyOCRItem("参加", (670.0, 97.0)),
        DummyOCRItem("科举乡试", (883.0, 182.0)),
        DummyOCRItem("17:00开启", (1065.0, 179.0)),
    ]
    cards = _parse_activity_panel(items)
    cards_map = {c["name"]: c for c in cards}
    assert cards_map["三界奇缘"]["join_btn"] is None
    assert cards_map["三界奇缘"]["is_time_gated"] is True
    assert cards_map["科举乡试"]["join_btn"] is None
    assert cards_map["科举乡试"]["is_time_gated"] is True



def test_covering_popup_dismissal_skips_quiz_own_exit():
    """答题题目页头部可见时，× 是答题自己的退出按钮——不得当作遮挡弹窗关闭。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("三界奇缘", (640.0, 45.0)),
        DummyOCRItem("×", (1105.0, 48.0)),
        DummyOCRItem("系统公告", (640.0, 300.0)),
    ]
    dh.handle_quiz(ctx, None)
    assert ctx.device.clicks == []  # no blind dismissal of the quiz exit button


def test_shimen_dialog_picks_choice_not_tracker_item():
    """回归 2026-09-28：师门 NPC 对话时（如虬髯客），右上角任务追踪栏
    「师门-悲欢离合（4/10）」(1150, 195) 与下方真实对话选项「师门任务」(1085, 333)
    同时包含「师门」关键词。dialog_choice 必须排除追踪栏并点中真实的对话选项 (1085, 333)，
    否则点击追踪栏只会关闭对话框导致无限死循环。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["current_task_name"] = "师门任务"
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("师门-悲欢离合（4/10）", (1150.0, 195.0)),
        DummyOCRItem("请选择要做的事", (1021.0, 253.0)),
        DummyOCRItem("师门任务", (1085.0, 333.0)),
        DummyOCRItem("了解结拜", (1087.0, 399.0)),
        DummyOCRItem("义结金兰", (1085.0, 465.0)),
    ]
    click_dialog_choice(ctx, NodeAction(type="custom", custom_func="click_dialog_choice"))
    assert device.clicks == [(1085.0, 333.0)]



def test_shop_buy_guards_repeat_purchase_in_same_dialog():
    """回归 2026-09-29：商铺购买最多一次，防重复购买塞满背包。

    shop_buy 节点在每个 sense 周期都会在「购买」按钮可见时重新触发 click_shop_buy。
    同一商铺窗口内必须至多购买一次，否则会无限重复购买直到背包塞满。
    （用普通商品验证窗口级防重；藏宝图另有专门的按需门禁用例。）
    """
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("药店", (663.0, 42.0)),
        DummyOCRItem("金疮药", (525.0, 307.0)),
        DummyOCRItem("购买", (1010.0, 656.0)),
    ]
    click_shop_buy(ctx, NodeAction(type="custom", custom_func="click_shop_buy"))
    assert (1010.0, 656.0) in device.clicks  # first purchase happens

    # Same dialog on the next tick: no repeat purchase, the window is closed instead.
    device.clicks.clear()
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("药店", (663.0, 42.0)),
        DummyOCRItem("金疮药", (525.0, 307.0)),
        DummyOCRItem("购买", (1010.0, 656.0)),
    ]
    click_shop_buy(ctx, NodeAction(type="custom", custom_func="click_shop_buy"))
    assert (1010.0, 656.0) not in device.clicks  # never re-buys in the same window


def test_shop_buy_new_dialog_resets_purchase_budget():
    """不同商铺窗口（商品行变化）应获得新的购买预算，允许再次购买。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("药店", (663.0, 42.0)),
        DummyOCRItem("金疮药", (525.0, 307.0)),
        DummyOCRItem("购买", (1010.0, 656.0)),
    ]
    click_shop_buy(ctx, NodeAction(type="custom", custom_func="click_shop_buy"))
    assert (1010.0, 656.0) in device.clicks

    # A genuinely different shop (different product rows) is a new window: buy allowed again.
    device.clicks.clear()
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("药店", (663.0, 42.0)),
        DummyOCRItem("小还丹", (525.0, 307.0)),
        DummyOCRItem("购买", (1010.0, 656.0)),
    ]
    click_shop_buy(ctx, NodeAction(type="custom", custom_func="click_shop_buy"))
    assert (1010.0, 656.0) in device.clicks


def test_shop_buy_refuses_treasure_map_outside_dig_request():
    """藏宝图商铺只有在挖宝流程显式请求（treasure_map_requested）时才允许购买；
    否则直接关闭窗口，绝不囤货（回归 2026-09-29：每次藏宝图买太多，背包完全满了）。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("商会", (663.0, 42.0)),
        DummyOCRItem("藏宝图", (525.0, 307.0)),
        DummyOCRItem("藏宝图", (525.0, 422.0)),
        DummyOCRItem("购买", (1010.0, 656.0)),
    ]
    click_shop_buy(ctx, NodeAction(type="custom", custom_func="click_shop_buy"))
    assert (1010.0, 656.0) not in device.clicks  # never bought without dig request
    assert device.keys or device.clicks  # window closed (× or back key) instead


def test_shop_buy_treasure_map_budget_bounded_when_requested():
    """挖宝请求购买时：预算 1 张，一次点击后即止，不会继续买。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["treasure_map_requested"] = True
    ctx.variables["treasure_map_buy_budget"] = 1
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("商会", (663.0, 42.0)),
        DummyOCRItem("藏宝图", (525.0, 307.0)),
        DummyOCRItem("购买", (1010.0, 656.0)),
    ]
    click_shop_buy(ctx, NodeAction(type="custom", custom_func="click_shop_buy"))
    assert (1010.0, 656.0) in device.clicks

    device.clicks.clear()
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("商会", (663.0, 42.0)),
        DummyOCRItem("藏宝图", (525.0, 307.0)),
        DummyOCRItem("购买", (1010.0, 656.0)),
    ]
    click_shop_buy(ctx, NodeAction(type="custom", custom_func="click_shop_buy"))
    assert (1010.0, 656.0) not in device.clicks  # budget exhausted -> stop


def test_needs_treasure_map_gates_dig_time_purchase():
    """needs_treasure_map 只在挖宝阶段背包无图且还有剩余挖掘次数时返回 True。"""
    ctx = PipelineContext()

    ctx.variables["has_treasure_map"] = True
    ctx.variables["dig_count"] = 3
    assert dh.needs_treasure_map(ctx, None, None) is False  # bag has a map: no buy

    ctx.variables["has_treasure_map"] = False
    ctx.variables["dig_count"] = 3
    ctx.variables["treasure_map_buys_this_dig"] = 0
    assert dh.needs_treasure_map(ctx, None, None) is True  # dig needs a map: buy one

    ctx.variables["dig_count"] = 10
    assert dh.needs_treasure_map(ctx, None, None) is False  # dig done: no buy

    ctx.variables["dig_count"] = 5
    ctx.variables["treasure_map_buys_this_dig"] = 1
    assert dh.needs_treasure_map(ctx, None, None) is False  # per-dig budget used: no more


def test_buy_treasure_map_one_at_a_time_only():
    """buy_treasure_map 一次只买一张，且受 max_treasure_maps_per_dig 限制（不囤货）。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["dig_count"] = 3
    ctx.variables["baotu_dig_target"] = 10
    ctx.variables["has_treasure_map"] = False
    ctx.variables["treasure_map_buys_this_dig"] = 0
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("商会", (663.0, 42.0)),
        DummyOCRItem("藏宝图", (525.0, 307.0)),
        DummyOCRItem("购买", (1010.0, 656.0)),
    ]
    dh.buy_treasure_map(ctx, NodeAction(type="custom", custom_func="buy_treasure_map"))
    assert device.clicks == [(1010.0, 656.0)]  # exactly one 购买 click
    assert ctx.variables["treasure_map_buys_this_dig"] == 1
    assert ctx.variables["has_treasure_map"] is True

    # Budget exhausted: second call buys nothing.
    device.clicks.clear()
    dh.buy_treasure_map(ctx, NodeAction(type="custom", custom_func="buy_treasure_map"))
    assert device.clicks == []


def test_daily_baotu_dig_loop_buys_map_at_dig_time():
    """回归 2026-09-29：挖宝时背包无图 → 先按需买 1 张 → 再进背包挖。

    probe_map_in_bag 作为挖宝环路的决策节点，在背包无图且本轮未购图时路由到
    buy_map_to_dig，购买后才进入 select_treasure_map，实现「只有挖宝时候再买藏宝图」。
    """
    device = VirtualDevice()
    plugin = MHXYMobilePlugin(device=device)
    pipe = plugin.get_pipeline("daily_baotu")
    pipe.start()

    # No map in the bag, budget still available -> must route to buy_map_to_dig.
    plugin.context.variables["has_treasure_map"] = False
    plugin.context.variables["treasure_map_buys_this_dig"] = 0
    plugin.context.variables["treasure_map_buy_attempts"] = 0
    plugin.context.variables["dig_count"] = 2
    pipe.current_node_name = "probe_map_in_bag"

    status = plugin.run_pipeline_step("daily_baotu")
    assert status == PipelineStatus.RUNNING
    assert pipe.current_node_name == "buy_map_to_dig"

    # After the purchase has_treasure_map=True; next cycle routes straight to dig.
    plugin.context.variables["has_treasure_map"] = True
    plugin.context.variables["treasure_map_buys_this_dig"] = 1
    pipe.current_node_name = "probe_map_in_bag"
    plugin.run_pipeline_step("daily_baotu")
    assert pipe.current_node_name == "select_treasure_map"


def test_daily_baotu_dig_loop_skips_buy_when_bag_has_map():
    """背包已有藏宝图（强盗掉落）时，挖宝环路不得再触发购图。"""
    device = VirtualDevice()
    plugin = MHXYMobilePlugin(device=device)
    pipe = plugin.get_pipeline("daily_baotu")
    pipe.start()

    plugin.context.variables["has_treasure_map"] = True
    plugin.context.variables["treasure_map_buys_this_dig"] = 0
    plugin.context.variables["treasure_map_buy_attempts"] = 0
    plugin.context.variables["dig_count"] = 2
    pipe.current_node_name = "probe_map_in_bag"

    status = plugin.run_pipeline_step("daily_baotu")
    assert status == PipelineStatus.RUNNING
    assert pipe.current_node_name == "select_treasure_map"
    assert plugin.context.variables["treasure_map_buys_this_dig"] == 0


def test_buy_treasure_map_no_shop_window_no_stray_click():
    """商铺窗口未打开（无「购买」按钮）时绝不盲点固定坐标，只累计尝试次数。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["dig_count"] = 3
    ctx.variables["baotu_dig_target"] = 10
    ctx.variables["has_treasure_map"] = False
    ctx.variables["treasure_map_buys_this_dig"] = 0
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("商会", (663.0, 42.0)),
        DummyOCRItem("藏宝图", (525.0, 307.0)),
        # 没有「购买」按钮 —— 旧实现会盲点 (1010, 656)
    ]
    dh.buy_treasure_map(ctx, NodeAction(type="custom", custom_func="buy_treasure_map"))
    assert device.clicks == []  # 绝不盲点
    assert ctx.variables["treasure_map_buys_this_dig"] == 0
    assert ctx.variables["treasure_map_buy_attempts"] == 1


def test_buy_treasure_map_attempts_bounded_not_infinite():
    """连续无商铺购图尝试被 max_treasure_map_buy_attempts 封顶，环路必然终止。"""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["dig_count"] = 3
    ctx.variables["baotu_dig_target"] = 10
    ctx.variables["has_treasure_map"] = False
    ctx.variables["treasure_map_buys_this_dig"] = 0
    ctx.variables["treasure_map_buy_attempts"] = 2  # 已连续空跑 2 次
    ctx.variables["_last_frame_items"] = []

    # 第 3 次仍无按钮：尝试次数 +1（封顶）
    dh.buy_treasure_map(ctx, NodeAction(type="custom", custom_func="buy_treasure_map"))
    assert device.clicks == []
    assert ctx.variables["treasure_map_buy_attempts"] == 3

    # 达到上限后 needs_treasure_map 返回 False，环路不再进入购图
    assert dh.needs_treasure_map(ctx, None, None) is False


def test_fashion_showroom_vetoed_from_quiz_closed_via_corner_x():
    """回归 2026-09-29：时装外观展厅。合并的玩家 ID 行「ID442951442时装未穿戴」落在
    题干 ROI，装备位页签（坐骑/名片背景/…）落在选项 ROI，问答启发式误触发，
    quiz_answer 盲点 150+ 次，宝图任务中途卡死。

    quiz_open 优先级高于 popup_open，所以必须先从答题里否决，再经弹窗关闭器
    用右上角 × (1143,35) 关窗；返回键关不掉它（会弹出退出游戏确认）。
    """
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    showroom = [
        DummyOCRItem("乾隆", (636.0, 23.0)),
        DummyOCRItem("ID442951442", (638.0, 50.0)),
        DummyOCRItem("头饰", (264.0, 102.0)),
        DummyOCRItem("时装", (1014.0, 102.0)),
        DummyOCRItem("轻灵羽毛（翡翠）", (192.0, 140.0)),
        DummyOCRItem("未穿戴", (1025.0, 140.0)),
        DummyOCRItem("足迹", (266.0, 244.0)),
        DummyOCRItem("坐骑", (1014.0, 244.0)),
        DummyOCRItem("未装备", (254.0, 282.0)),
        DummyOCRItem("未骑乘", (1025.0, 282.0)),
        DummyOCRItem("称谓特效", (241.0, 386.0)),
        DummyOCRItem("名片背景", (1038.0, 386.0)),
        DummyOCRItem("我要试穿", (640.0, 678.0)),
        DummyOCRItem("保存穿搭", (931.0, 699.0)),
    ]
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items", return_value=showroom):
        classify_screen(ctx, None)
    assert ctx.variables["quiz_open"] is False
    assert ctx.variables["popup_open"] is True

    ctx.variables["_last_frame_items"] = showroom
    dismiss_popups(ctx, NodeAction(type="custom", custom_func="dismiss_popups"))
    assert device.clicks == [(1143.0, 35.0)]
