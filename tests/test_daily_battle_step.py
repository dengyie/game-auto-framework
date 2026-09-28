"""
Unit tests for intelligent combat decision logic in daily_handlers.py:
- Moon Palace (月宫): multi-monster AOE (月影瑶光) vs single-monster (月刃)
- Pet turn: physical attack pet (攻宠 -> 攻击) vs magic pet (法宠 -> 法术)
- Monster count estimation (OCR labels + HP bars)
- Combat settlement dismissal
- Screen classification (in_battle, popup_open, panel_open)
"""

from unittest.mock import MagicMock
import pytest

from plugins.mhxy_mobile.custom.daily_handlers import (
    _battle_monster_count,
    classify_screen,
    do_battle_step,
    is_in_battle_ocr,
    DEFAULT_ENEMY_TARGET,
    PET_ATTACK,
    BOTTOM_ATTACK,
)
from scheduler.dag import NodeAction, PipelineContext


class DummyOCRItem:
    def __init__(self, text: str, center: tuple[float, float], confidence: float = 0.95):
        self.text = text
        self.center = center
        self.confidence = confidence


class DummyDevice:
    def __init__(self):
        self.clicks = []

    def click(self, x: float, y: float):
        self.clicks.append((x, y))

    def screencap(self, raw: bool = False):
        return b""


def test_monster_count_multi_monsters():
    # Simulated items with multiple enemy monsters in enemy formation ROI (100..780, 80..480)
    items = [
        DummyOCRItem("银沙怒蛟", (532.0, 228.0)),
        DummyOCRItem("沧海", (323.0, 342.0)),
        DummyOCRItem("银沙怒蛟", (243.0, 399.0)),
        DummyOCRItem("大鹏王", (417.0, 391.0)),      # Ally
        DummyOCRItem("惠岸行者", (1039.0, 431.0)),    # Ally
        DummyOCRItem("mango1号", (947.0, 491.0)),    # Player
        DummyOCRItem("攻击", (1138.0, 690.0)),        # Action
        DummyOCRItem("取消", (1234.0, 690.0)),        # Auto Cancel
    ]
    count, names, bars = _battle_monster_count(None, items)
    assert count == 3
    assert len(names) == 3
    assert ("大鹏王", (417.0, 391.0)) not in names


def test_monster_count_single_monster():
    items = [
        DummyOCRItem("强盗头领", (380.0, 260.0)),
        DummyOCRItem("惠岸行者", (1039.0, 431.0)),    # Ally
        DummyOCRItem("mango1号", (947.0, 491.0)),    # Player
        DummyOCRItem("攻击", (1138.0, 690.0)),
    ]
    count, names, bars = _battle_monster_count(None, items)
    assert count == 1
    assert names[0][0] == "强盗头领"


def test_battle_step_moon_palace_aoe_when_multi_monsters():
    device = DummyDevice()
    ctx = PipelineContext(device=device)

    # Multi-monster battle: skill 月影瑶光 visible on shortcut
    items = [
        DummyOCRItem("银沙怒蛟", (532.0, 228.0)),
        DummyOCRItem("沧海", (323.0, 342.0)),
        DummyOCRItem("月影瑶光", (1100.0, 600.0)),
        DummyOCRItem("月刃", (1000.0, 600.0)),
        DummyOCRItem("攻击", (1138.0, 690.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="do_battle_step")
    do_battle_step(ctx, act)

    # Should click visible 月影瑶光 @ (1100, 600), then click enemy target
    assert len(device.clicks) >= 2
    assert device.clicks[0] == (1100.0, 600.0)
    # Target should be primary enemy coordinate (532.0, 228.0)
    assert device.clicks[1] == (532.0, 228.0)


def test_battle_step_moon_palace_single_target_when_single_monster():
    device = DummyDevice()
    ctx = PipelineContext(device=device)

    # Single-monster battle: skill 月刃 should be chosen
    items = [
        DummyOCRItem("强盗头领", (350.0, 280.0)),
        DummyOCRItem("月影瑶光", (1100.0, 600.0)),
        DummyOCRItem("月刃", (1020.0, 580.0)),
        DummyOCRItem("攻击", (1138.0, 690.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="do_battle_step")
    do_battle_step(ctx, act)

    # Should click visible 月刃 @ (1020, 580), then target
    assert len(device.clicks) >= 2
    assert device.clicks[0] == (1020.0, 580.0)
    assert device.clicks[1] == (350.0, 280.0)


def test_battle_step_pet_turn_attack_pet():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["pet_type"] = "attack"  # 攻宠

    items = [
        DummyOCRItem("野猪", (400.0, 250.0)),
        DummyOCRItem("选择召唤灵", (640.0, 100.0)),
        DummyOCRItem("攻击", (983.0, 518.0)),
        DummyOCRItem("法术", (900.0, 518.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="do_battle_step")
    do_battle_step(ctx, act)

    # 攻宠: Should click 攻击, then enemy target
    assert len(device.clicks) >= 2
    assert device.clicks[0] == (983.0, 518.0)
    assert device.clicks[1] == (400.0, 250.0)


def test_battle_step_pet_turn_magic_pet():
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["pet_type"] = "magic"  # 法宠

    items = [
        DummyOCRItem("野猪", (400.0, 250.0)),
        DummyOCRItem("选择召唤灵", (640.0, 100.0)),
        DummyOCRItem("攻击", (983.0, 518.0)),
        DummyOCRItem("法术", (900.0, 518.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="do_battle_step")
    do_battle_step(ctx, act)

    # 法宠: Should click 法术, then enemy target
    assert len(device.clicks) >= 2
    assert device.clicks[0] == (900.0, 518.0)
    assert device.clicks[1] == (400.0, 250.0)


def test_battle_step_settlement_dismiss():
    device = DummyDevice()
    ctx = PipelineContext(device=device)

    items = [
        DummyOCRItem("点击空白处返回主界面", (640.0, 573.0)),
        DummyOCRItem("少侠不要气馁，提升实力继续挑战！", (624.0, 373.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="do_battle_step")
    do_battle_step(ctx, act)

    # Should click empty center area (640, 500) to dismiss
    assert len(device.clicks) == 1
    assert device.clicks[0] == (640, 500)


def test_classify_screen_in_battle_detection():
    ctx = PipelineContext()
    frame = None

    # Mock OCR items returned by _ocr_items
    from unittest.mock import patch
    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("银沙怒蛟", (532.0, 228.0)),
            DummyOCRItem("攻击", (1138.0, 690.0)),
            DummyOCRItem("取消", (1234.0, 690.0)),
        ]
        classify_screen(ctx, frame)
        assert ctx.variables["in_battle"] is True
        assert ctx.variables["popup_open"] is False

    with patch("plugins.mhxy_mobile.custom.daily_handlers._ocr_items") as mock_ocr:
        mock_ocr.return_value = [
            DummyOCRItem("点击空白处关闭界面", (639.0, 643.0)),
            DummyOCRItem("时空计划", (193.0, 656.0)),
        ]
        classify_screen(ctx, frame)
        assert ctx.variables["in_battle"] is False
        assert ctx.variables["popup_open"] is True


def test_battle_step_mowang_strategy():
    """魔王寨: multi-monster -> 飞砂走石; single-monster -> 三昧真火."""
    # 1. Multi-monster
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["sect"] = "魔王寨"
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("山贼甲", (350.0, 260.0)),
        DummyOCRItem("山贼乙", (450.0, 320.0)),
        DummyOCRItem("飞砂走石", (1095.0, 590.0)),
        DummyOCRItem("三昧真火", (990.0, 580.0)),
    ]
    act = NodeAction(type="custom", custom_func="do_battle_step")
    do_battle_step(ctx, act)

    assert len(device.clicks) >= 2
    assert device.clicks[0] == (1095.0, 590.0)  # Clicks 飞砂走石
    assert device.clicks[1] == (350.0, 260.0)   # Targets primary enemy

    # 2. Single-monster
    device2 = DummyDevice()
    ctx2 = PipelineContext(device=device2)
    ctx2.variables["sect"] = "魔王寨"
    ctx2.variables["_last_frame_items"] = [
        DummyOCRItem("山贼头领", (380.0, 270.0)),
        DummyOCRItem("飞砂走石", (1095.0, 590.0)),
        DummyOCRItem("三昧真火", (990.0, 580.0)),
    ]
    do_battle_step(ctx2, act)
    assert len(device2.clicks) >= 2
    assert device2.clicks[0] == (990.0, 580.0)   # Clicks 三昧真火
    assert device2.clicks[1] == (380.0, 270.0)


def test_battle_step_fangcun_strategy():
    """方寸山: multi-monster -> 五雷咒; single-monster or force_seal -> 失心符."""
    act = NodeAction(type="custom", custom_func="do_battle_step")

    # 1. Routine multi-monster -> 五雷咒
    dev1 = DummyDevice()
    ctx1 = PipelineContext(device=dev1)
    ctx1.variables["sect"] = "方寸山"
    ctx1.variables["_last_frame_items"] = [
        DummyOCRItem("野鬼A", (320.0, 240.0)),
        DummyOCRItem("野鬼B", (420.0, 310.0)),
        DummyOCRItem("五雷咒", (1080.0, 600.0)),
        DummyOCRItem("失心符", (980.0, 600.0)),
    ]
    do_battle_step(ctx1, act)
    assert len(dev1.clicks) >= 2
    assert dev1.clicks[0] == (1080.0, 600.0)  # Clicks 五雷咒

    # 2. Single boss monster -> 失心符 (seal + debuff)
    dev2 = DummyDevice()
    ctx2 = PipelineContext(device=dev2)
    ctx2.variables["sect"] = "方寸山"
    ctx2.variables["_last_frame_items"] = [
        DummyOCRItem("千年厉鬼", (360.0, 260.0)),
        DummyOCRItem("五雷咒", (1080.0, 600.0)),
        DummyOCRItem("失心符", (980.0, 600.0)),
    ]
    do_battle_step(ctx2, act)
    assert len(dev2.clicks) >= 2
    assert dev2.clicks[0] == (980.0, 600.0)   # Clicks 失心符

    # 3. Multi-monster with force_seal flag -> prioritizes 失心符
    dev3 = DummyDevice()
    ctx3 = PipelineContext(device=dev3)
    ctx3.variables["sect"] = "方寸山"
    ctx3.variables["force_seal"] = True
    ctx3.variables["_last_frame_items"] = [
        DummyOCRItem("野鬼A", (320.0, 240.0)),
        DummyOCRItem("野鬼B", (420.0, 310.0)),
        DummyOCRItem("五雷咒", (1080.0, 600.0)),
        DummyOCRItem("失心符", (980.0, 600.0)),
    ]
    do_battle_step(ctx3, act)
    assert len(dev3.clicks) >= 2
    assert dev3.clicks[0] == (980.0, 600.0)   # Forced seal triggers 失心符


def test_battle_step_putuo_strategy():
    """普陀山: multi-monster -> 五行咒; support buff -> 灵动九天; need heal -> 普渡众生."""
    act = NodeAction(type="custom", custom_func="do_battle_step")

    # 1. Routine multi-monster -> 五行咒 (fixed damage AoE)
    dev1 = DummyDevice()
    ctx1 = PipelineContext(device=dev1)
    ctx1.variables["sect"] = "普陀山"
    ctx1.variables["_last_frame_items"] = [
        DummyOCRItem("小怪1", (300.0, 250.0)),
        DummyOCRItem("小怪2", (450.0, 320.0)),
        DummyOCRItem("五行咒", (1090.0, 595.0)),
        DummyOCRItem("普渡众生", (995.0, 595.0)),
    ]
    do_battle_step(ctx1, act)
    assert len(dev1.clicks) >= 2
    assert dev1.clicks[0] == (1090.0, 595.0)  # Clicks 五行咒

    # 2. Need heal -> 普渡众生
    dev2 = DummyDevice()
    ctx2 = PipelineContext(device=dev2)
    ctx2.variables["sect"] = "普陀山"
    ctx2.variables["need_heal"] = True
    ctx2.variables["_last_frame_items"] = [
        DummyOCRItem("小怪1", (300.0, 250.0)),
        DummyOCRItem("五行咒", (1090.0, 595.0)),
        DummyOCRItem("普渡众生", (995.0, 595.0)),
    ]
    do_battle_step(ctx2, act)
    assert len(dev2.clicks) >= 2
    assert dev2.clicks[0] == (995.0, 595.0)   # Clicks 普渡众生

    # 3. Support mode buff -> 灵动九天
    dev3 = DummyDevice()
    ctx3 = PipelineContext(device=dev3)
    ctx3.variables["sect"] = "普陀山"
    ctx3.variables["support_mode"] = "buff"
    ctx3.variables["_last_frame_items"] = [
        DummyOCRItem("小怪1", (300.0, 250.0)),
        DummyOCRItem("灵动九天", (950.0, 420.0)),
    ]
    do_battle_step(ctx3, act)
    assert len(dev3.clicks) >= 2
    assert dev3.clicks[0] == (950.0, 420.0)   # Clicks 灵动九天


def test_sect_auto_detection_from_skill_items():
    """Verify that sect is automatically detected when sect is not set in ctx."""
    act = NodeAction(type="custom", custom_func="do_battle_step")

    # No sect specified, but 飞砂走石 is visible -> auto-detects 魔王寨
    dev = DummyDevice()
    ctx = PipelineContext(device=dev)
    assert "sect" not in ctx.variables
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("强盗A", (320.0, 250.0)),
        DummyOCRItem("强盗B", (420.0, 310.0)),
        DummyOCRItem("飞砂走石", (1090.0, 600.0)),
    ]
    do_battle_step(ctx, act)
    assert len(dev.clicks) >= 2
    assert dev.clicks[0] == (1090.0, 600.0)


def test_battle_step_blood_pet_defend():
    """Verify blood/speed pet (血宠/配速) executes 防御."""
    device = DummyDevice()
    ctx = PipelineContext(device=device)
    ctx.variables["pet_type"] = "blood"

    items = [
        DummyOCRItem("黑熊精", (400.0, 250.0)),
        DummyOCRItem("选择召唤灵", (640.0, 100.0)),
        DummyOCRItem("防御", (983.0, 518.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    act = NodeAction(type="custom", custom_func="do_battle_step")
    do_battle_step(ctx, act)

    assert len(device.clicks) >= 2
    assert device.clicks[0] == (983.0, 518.0)  # Clicks 防御
    assert device.clicks[1] == (400.0, 250.0)  # Clicks target


def test_all_registered_sects_strategy_coverage():
    """Ensure all 11 major sects are registered and provide valid AoE and single decisions."""
    from plugins.mhxy_mobile.custom.combat_strategy import (
        CombatContext,
        global_sect_registry,
    )
    sects = global_sect_registry.list_sects()
    expected_sects = {
        "月宫", "魔王寨", "方寸山", "普陀山", "龙宫",
        "大唐官府", "化生寺", "阴曹地府", "狮驼岭", "小雷音", "花果山"
    }
    assert expected_sects.issubset(set(sects))

    for s_name in expected_sects:
        strat = global_sect_registry.get(s_name)
        assert strat is not None
        # Test multi-monster decision
        multi_ctx = CombatContext(monster_count=5)
        dec_multi = strat.decide(multi_ctx)
        assert dec_multi.skill_name != ""
        assert len(dec_multi.keywords) > 0

        # Test single-monster decision
        single_ctx = CombatContext(monster_count=1)
        dec_single = strat.decide(single_ctx)
        assert dec_single.skill_name != ""
        assert len(dec_single.keywords) > 0

