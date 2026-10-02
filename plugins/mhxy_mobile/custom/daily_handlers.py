"""
Daily-activities (日常) OCR-driven operators for the live MuMu client.

Design rules learned from live runs (2026-09-23/24):
- Task entry is the 活动 panel (top-bar 活动 button at (346,65)); each row's
  参加 button drives auto-path to the NPC. Never click blind NPC coordinates.
- Escort (运镖): panel row right-top -> NPC dialog 押送普通镖银 (1086,400) ->
  deposit confirm 确定 (~747,420). Completion is verified by the row counter
  次数n/3 increasing; done rows disappear from the panel.
- Battle: intelligent turn-based decision:
  * Moon Palace (月宫): monster_count > 1 -> AOE skill 月影瑶光;
    monster_count <= 1 -> single-target burst 月刃.
  * Pet: physical attack pet (攻宠) -> 攻击; magic pet (法宠) -> 法术.
  * Target selection: click primary monster or enemy formation center.
  * Settlement: click empty area to dismiss victory/defeat dialogs cleanly.
- Popup policy: reward/notice popups with a top-right × inside (1050..1200,
  20..120) or '确认关闭' / '点击空白处关闭界面' are closed.
"""

from __future__ import annotations

import datetime
from datetime import date
import re
import time
from typing import Any, List, Optional, Tuple

from loguru import logger

from scheduler.dag import NodeAction, NodeRecognition, PipelineContext
from plugins.mhxy_mobile.custom.combat_strategy import (
    CombatContext,
    PetCombatEngine,
    SkillDecision,
    global_sect_registry,
)
from plugins.mhxy_mobile.custom.quiz_solver import (
    clean_question_text,
    fix_ocr_noise,
    get_default_solver,
    normalize_text,
)

# --- constants (1280x720 baseline) -------------------------------------------
TOPBAR_ACTIVITY = (353, 64)
PANEL_CLOSE = (1142, 48)
# promo BACK burst budget (8) + suspend grace before the run is declared blocked
PROMO_BLOCK_STREAK = 20
ESCORT_JOIN = (669, 377)           # 运镖 row 参加 (unscrolled panel, row 3 left)
# 日常活动 tab, list scrolled to the very top (live 2026-09-26 & 2026-09-28):
# row 1: 秘境降妖 (669, 148), 师门任务 (1077, 148)
# row 2: 捉鬼任务队 (669, 263), 宝图任务 (1077, 263)
# row 3: 运镖 (669, 377)
DAILY_ROW_JOIN = {
    "师门任务": (1077, 148),    # row 1, right
    "宝图任务": (1077, 263),    # row 2, right
    "运镖": (669, 377),        # row 3, left
    "秘境降妖": (669, 148),     # row 1, left
}
PET_ATTACK = (983, 518)
PET_SPELL = (900, 518)
BOTTOM_ATTACK = (1138, 690)
BOTTOM_AUTO_CANCEL = (1234, 690)
DEFAULT_ENEMY_TARGET = (420, 260)
ESCORT_CHOICE = (1086, 400)        # 押送普通镖银
DEPOSIT_CONFIRM_Y = (747, 420)     # 确定
MAX_ESCORTS = 3

# --- 藏宝图 (treasure map) acquisition policy (bugfix 2026-09-29) --------------
# The generic 购买 loop in daily_dailies re-clicked 购买 every tick while a shop
# window stayed open, banking 藏宝图 until the backpack was completely full
# (user report: 每次藏宝图买太多，背包完全满了). Maps are now obtained at dig time
# and one at a time:
#   * TREASURE_MAP_KWS identifies a map-selling window from its item rows;
#   * a shop window may only be bought from MAX_SHOP_BUYS_PER_DIALOG times (default 1),
#     so a persistent dialog can never stockpile anything — this bounds *every* item,
#     not just maps;
#   * a 藏宝图-selling window is refused outright unless the dig flow explicitly
#     requests a map (``treasure_map_requested``, with a ``treasure_map_buy_budget``
#     cap). Nothing in production sets those, so the generic 商铺 loop never buys a
#     map: maps come only from the dig-time gate in daily_baotu (buy_map_to_dig),
#     which is itself capped by MAX_TREASURE_MAPS_PER_DIG per dig.
TREASURE_MAP_KWS = ("藏宝图", "宝图")
MAX_SHOP_BUYS_PER_DIALOG = 1
MAX_TREASURE_MAPS_PER_DIG = 1
# Cap on consecutive no-shop buy attempts inside the dig loop. The dig gate
# (probe_map_in_bag -> buy_map_to_dig) can otherwise bounce forever when the bag
# is empty and no shop window with a 购买 button ever opens: node timeouts reset on
# every transition and the escape manager sees each step as progress. After this
# many failed attempts the gate declines to buy and the dig loop times out honestly
# at select_treasure_map instead of spinning.
MAX_TREASURE_MAP_BUY_ATTEMPTS = 3

# Quiz (科举/三界奇缘) screen zones, borrowed from upstream Maa_MHXY_MG reco_sjqy
# (1280x720: question ROI [447,40,673,94], answer ROI [439,218,678,212])
QUIZ_QUESTION_ROI = (440, 25, 1135, 150)   # x1, y1, x2, y2 (三界奇缘 layout)
# Lower edge past 445: a "寻找N个" row sits at y≈465 (live 2026-09-27, 观音/唐僧/二大王),
# which the old band dropped so the question never got an option to click.
QUIZ_OPTION_ROI = (430, 205, 1280, 520)
# 科举乡试 layout (live 2026-09-25): title "科举乡试·" ~y99, "第n题" ~y170,
# question ~y212, options A/B ~y353 and C/D ~y453.
KEJU_QUESTION_ROI = (430, 185, 1135, 290)
KEJU_OPTION_ROI = (430, 300, 1135, 520)
QUIZ_OPTION_PREFIX_RE = re.compile(r"^[A-Da-dＡ-Ｄ][\.、,，:：\)）]\s*")
QUIZ_OPTION_NOISE_KWS = (
    "退出", "提示", "跳过", "关闭", "设置", "频道", "世界", "队伍", "帮派",
    "系统", "好友", "商城", "福利", "答题", "作答", "正确答案", "搜索",
)
QUIZ_DONE_KWS = (
    "答题完成", "已答完", "今日已完成", "明日再来", "活动已结束", "完成所有题目",
    # 科举乡试 completion (live 2026-09-25): "恭喜少侠成功获得科举会试的机会"
    "会试的机会", "乡试已结束", "答题结束",
)
QUIZ_FEEDBACK_KWS = ("回答正确", "答对了", "回答错误", "答错了", "正确答案")

# Words that mark ally characters and UI keywords in combat
ALLY_NAMES = {
    "大鹏王", "惠岸行者", "红孩儿", "星宿神君", "mango1号", "李元霸", "孙悟空",
    "菩提老祖", "唐僧", "观音菩萨", "猪八戒", "沙和尚", "小白龙", "杨戬",
    "哪吒", "牛魔王", "铁扇公主", "青霞仙子", "紫霞仙子", "北海龙王", "西海龙王",
    "东海龙王", "南海龙王", "助战"
}
COMBAT_UI_KEYWORDS = {
    "23:", "50", "43", "经验", "系统", "世界", "帮派", "队伍", "攻击", "取消",
    "自动", "法术", "道具", "防御", "逃跑", "新技能", "龙宫", "好友", "商城",
    "福利", "节日", "首充", "选择召唤灵", "特技", "当前", "回合", "第"
}

_escort_counter_cache: dict = {}


def _ocr_items(frame: Any) -> list:
    if frame is None:
        return []
    from core.ocr.engine import OCREngine

    engine = OCREngine.get_instance()
    if engine.is_mock:
        return []
    try:
        return engine.recognize(frame)
    except Exception as e:
        logger.warning(f"daily OCR error: {e}")
        return []


def _find(items: list, pred) -> Optional[Any]:
    for it in items:
        try:
            if pred(it):
                return it
        except Exception:
            continue
    return None


def _find_text(items: list, kw: str) -> Optional[Any]:
    return _find(items, lambda it: kw in getattr(it, "text", ""))


# Quest-tracker lines ("主线-佛道斗法") and world-chat broadcasts
# ("阵容推荐…时空纺织机…") cross QUIZ_QUESTION_ROI during battle gaps and satisfy the
# question+options heuristic, so quiz_answer blind-clicks per the bank-miss policy
# (live 2026-09-29). Real quiz questions never carry these markers.
_QUEST_LINE_RE = re.compile(
    r"^(主线|支线|师门|帮派|日常|抓鬼|宝图|运镖|秘境|剧情|修行|封妖|二十八宿)[\-—–·]"
)


def _looks_like_chat_or_quest_line(text: str) -> bool:
    t = text.strip()
    if _QUEST_LINE_RE.search(t):
        return True  # quest tracker line: "主线-佛道斗法"
    if "…" in t or "..." in t:
        return True  # merged chat fragments: "阵容推荐…时空纺织机…"
    if "推荐" in t and "？" not in t and "?" not in t:
        return True  # world-chat spam: 阵容推荐/阵容搭配 broadcasts
    return False


def _center(item: Any) -> Tuple[float, float]:
    return float(item.center[0]), float(item.center[1])


def _click(ctx: PipelineContext, x: float, y: float) -> None:
    # Edge-zone redline enforced in code, not just in docs: a malformed OCR box or a
    # stale constant must never land a tap on the screen bezel (live 2026-09-30 review).
    frame = ctx.variables.get("_last_frame")
    if frame is not None and hasattr(frame, "shape") and getattr(frame, "ndim", 0) == 3:
        fh, fw = frame.shape[:2]
        if not (10 <= x <= fw - 10 and 10 <= y <= fh - 10):
            logger.warning(
                f"[click] Blocked click at ({x:.0f}, {y:.0f}) — outside safe bounds "
                f"{fw}x{fh} (edge-zone redline)"
            )
            return
    if ctx.device:
        # Same-coordinate-repeat counter for the DAG stall watchdog's animated
        # blind spot: a page with shimmer/reward micro-animations never looks
        # static to the frame-diff check, yet the run is stuck (live 2026-09-30:
        # 28 consecutive clicks on the same 领取 at (1184,497) never tripped the
        # static-frame watchdog). dag.tick() reads this and breaks the pipeline.
        # Tolerance, not a grid: OCR centers of the same button jitter a few px
        # and a hard grid would straddle cells and spuriously reset the streak.
        # Reset conditions live in classify_screen (battle/panel = real progress).
        #
        # Repeat = how many of the recent clicks land on this same spot (sliding
        # window of the last _CLICK_REPEAT_WINDOW clicks). The original design
        # counted a streak vs the *previous* click, so any loop that closes with a
        # click elsewhere — open_panel tap x3 -> BACK -> quit-confirm 取消 — reset
        # the counter every cycle and never fused (live 2026-09-30 20:27 run:
        # 150 ticks of exactly that loop, zero progress, no TIMEOUT). A window
        # count survives the intervening different-coordinate click: the stall
        # loop keeps re-hitting its 3 anchors and the repeat count climbs to the
        # fuse even though the cycle also contains a 取消 tap.
        try:
            cell = (round(float(x) / 8.0) * 8, round(float(y) / 8.0) * 8)
            cells: list = ctx.variables.setdefault("_click_cells", [])
            cells.append(cell)
            # Keep a bounded recent history; counts decay as the loop's anchor
            # cells slide out, so it never latches across a real scene change.
            if len(cells) > 16:
                del cells[: len(cells) - 16]
            ctx.variables["_click_repeat"] = cells.count(cell)
            ctx.variables["_last_click_xy"] = (float(x), float(y))
        except (TypeError, ValueError):
            pass
        ctx.device.click(x, y)
        time.sleep(0.1)


def _frame_scale(ctx: PipelineContext) -> Tuple[float, float]:
    """Scale 1280x720-baseline fixed coordinates by the actual frame size.

    The module constants were designed on a 1280x720 baseline, but the MuMu instance
    runs at 1600x900 — on it the stale TOPBAR_ACTIVITY (353,64) landed on the wrong
    HUD button (基础设置, live 2026-09-30) while the real 活动 button sits at (439,79)
    = (353,64) * 1.25. Returns (1.0, 1.0) without a frame (tests / no classification yet).
    """
    frame = ctx.variables.get("_last_frame")
    if frame is not None and hasattr(frame, "shape") and getattr(frame, "ndim", 0) == 3:
        fh, fw = frame.shape[:2]
        if fw > 0 and fh > 0:
            return (fw / 1280.0, fh / 720.0)
    return (1.0, 1.0)


def _locate_corner_x(ctx: PipelineContext, items: list, x_min: int = 1000, y_max: int = 200) -> Optional[Tuple[float, float]]:
    """Locate the top-right × (close button) of a popup/sub-window.

    Full-frame OCR routinely misses the small × glyph of sub-windows — the 星宿之影
    smart-guide window's real × sits at frame (1138, 53) but full-frame OCR returned a
    spurious × at (1144, 113) and missed the real one, so dismiss_popups clicked dead
    space and the window never closed (live 2026-09-29, panel-open loop). The glyph is
    only reliably read after a 3x upscale of the top strip (observed real × positions:
    fashion (1143,35), sect-goal (1131,80), 星宿之影 (1138,53) — all y < 110).
    Strategy: trust a parsed × only in the tight band (x>x_min, y<110); a parse outside
    it (or no parse) triggers a re-screencap + 3x-upscaled top-strip OCR, mapping the ×
    back into frame coordinates. Returns frame-space (x, y) or None (caller falls back
    to its own fixed coordinate / parsed low ×).
    """
    cand = _find(items, lambda it: it.text.strip() in ("×", "X", "x", "✕")
               and it.center[0] > x_min and it.center[1] < 110)
    if cand is not None:
        return _center(cand)
    # Upscaled re-OCR fallback — needs a live device and OpenCV.
    dev = getattr(ctx, "device", None)
    if dev is None or not hasattr(dev, "screencap"):
        return None
    try:
        import cv2  # local import: only needed on the slow path
        import numpy as np
        png = dev.screencap()
        frame = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return None
        h, w = frame.shape[:2]
        x0, y0 = max(x_min - 40, 0), 0
        x1, y1 = min(w, x_min + 280), min(y_max, h)
        crop = cv2.resize(frame[y0:y1, x0:x1], None, fx=3, fy=3,
                          interpolation=cv2.INTER_CUBIC)
        upscaled = _ocr_items(crop)
        xb = _find(upscaled, lambda it: it.text.strip() in ("×", "X", "x", "✕"))
        if xb is not None:
            cx, cy = _center(xb)
            # map back from 3x upscaled crop space to original frame space
            return (x0 + cx / 3.0, y0 + cy / 3.0)
    except Exception as e:
        logger.warning(f"daily: upscaled corner-× OCR failed: {e}")
    return None


# --- combat perception & decision ---------------------------------------------

def _battle_monster_count(frame: Any, items: list) -> Tuple[int, List[Tuple[str, Tuple[float, float]]], list]:
    """Estimate enemy monster count on screen using OCR enemy labels and OpenCV HP bar contours."""
    enemy_names = []
    for it in items:
        cx, cy = it.center[0], it.center[1]
        txt = getattr(it, "text", "").strip()
        # Enemy formation ROI in 1280x720 baseline: x in [100, 780], y in [80, 480]
        if 100 <= cx <= 780 and 80 <= cy <= 480:
            if any(kw in txt for kw in COMBAT_UI_KEYWORDS):
                continue
            if any(ally in txt for ally in ALLY_NAMES):
                continue
            if txt.isdigit():
                continue
            if len(txt) > 6 or "，" in txt or "！" in txt or "。" in txt:
                continue
            enemy_names.append((txt, (cx, cy)))

    hp_bars = []
    if frame is not None:
        try:
            import cv2
            import numpy as np

            if isinstance(frame, bytes):
                nparr = np.frombuffer(frame, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            else:
                img = frame

            if img is not None:
                h, w = img.shape[:2]
                crop_y1, crop_y2 = int(h * 0.11), int(h * 0.67)
                crop_x1, crop_x2 = int(w * 0.08), int(w * 0.61)
                crop = img[crop_y1:crop_y2, crop_x1:crop_x2]
                if crop.size > 0:
                    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                    m1 = cv2.inRange(hsv, np.array([0, 100, 80]), np.array([10, 255, 255]))
                    m2 = cv2.inRange(hsv, np.array([170, 100, 80]), np.array([180, 255, 255]))
                    mask_red = cv2.bitwise_or(m1, m2)
                    contours, _ = cv2.findContours(mask_red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for cnt in contours:
                        x, y, bw, bh = cv2.boundingRect(cnt)
                        if 15 <= bw <= 120 and 2 <= bh <= 15 and bw / max(bh, 1) >= 2.5:
                            orig_x = (x + crop_x1) * 1280.0 / w
                            orig_y = (y + crop_y1) * 720.0 / h
                            hp_bars.append((orig_x, orig_y, bw, bh))
        except Exception as e:
            logger.warning(f"HP bar detection error: {e}")

    count = max(len(enemy_names), len(hp_bars))
    return count, enemy_names, hp_bars


def is_in_battle_ocr(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """Real battle state from live OCR: action commands or pet selector on screen."""
    items = _ocr_items(frame)
    return bool(_find(items, lambda it: (
        it.text in ("攻击", "取消", "自动", "法术", "特技", "防御", "逃跑", "月影瑶光", "月刃")
        or "选择召唤灵" in it.text
    ) and it.center[0] > 800 and it.center[1] > 380))


def do_battle_step(ctx: PipelineContext, act: NodeAction) -> None:
    """Intelligent combat decision step:
    - Character: Multi-sect strategy engine (月宫, 魔王寨, 方寸山, 普陀山, 大唐, 龙宫, etc.).
      Dynamic multi-monster (>1) vs single-monster (<=1) skill branching.
    - Pet: 攻宠 -> 攻击; 法宠 -> 法术; 血宠/配速 -> 防御.
    - Target: tap primary enemy in enemy zone.
    - Settlement: dismiss defeat/victory popups cleanly.
    """
    items = ctx.variables.get("_last_frame_items") or []
    frame = ctx.variables.get("_last_frame")

    # 1. Check for settlement popups (defeat / victory / return to world)
    settlement = _find(items, lambda it: any(kw in it.text for kw in ("点击空白处", "战斗胜利", "战斗结束", "再接再厉")))
    if settlement is not None:
        logger.info(f"[battle_step] combat settlement [{settlement.text}] detected, dismissing to return")
        _click(ctx, 640, 500)
        time.sleep(1.0)
        return

    # 2. Estimate monster count
    monster_count, enemy_names, hp_bars = _battle_monster_count(frame, items)
    logger.info(f"[battle_step] monster_count={monster_count} (names={[n[0] for n in enemy_names]}, hp_bars={len(hp_bars)})")

    # Primary target position
    target_x, target_y = DEFAULT_ENEMY_TARGET
    if enemy_names:
        target_x, target_y = enemy_names[0][1]
    elif hp_bars:
        target_x, target_y = hp_bars[0][0], hp_bars[0][1] + 15

    # 3. Check Pet Turn: indicated by '选择召唤灵' or character is already '准备中'
    is_pet_turn = bool(_find_text(items, "选择召唤灵") or _find_text(items, "准备中"))
    if is_pet_turn:
        pet_type = ctx.variables.get("pet_type", "attack")
        pet_decision = PetCombatEngine.decide(pet_type=pet_type, monster_count=monster_count)
        logger.info(f"[battle_step] Pet turn: {pet_decision.description}")
        btn = _find(items, lambda it: any(kw in it.text for kw in pet_decision.keywords) and it.center[0] > 800)
        if btn is not None:
            _click(ctx, btn.center[0], btn.center[1])
        else:
            _click(ctx, pet_decision.fallback_coord[0], pet_decision.fallback_coord[1])
        time.sleep(0.3)
        _click(ctx, target_x, target_y)
        logger.info(f"[battle_step] Pet executed [{pet_decision.action_name}] on target ({target_x:.0f}, {target_y:.0f})")
        time.sleep(0.5)
        return

    # 4. Character Turn: Extensible Sect Combat Strategy Engine
    sect_hint = ctx.variables.get("sect") or ctx.variables.get("character_sect")
    strategy = global_sect_registry.resolve_strategy(sect_hint=sect_hint, items=items)
    combat_ctx = CombatContext(
        monster_count=monster_count,
        enemy_names=enemy_names,
        hp_bars=hp_bars,
        items=items,
        frame=frame,
        target_pos=(target_x, target_y),
        variables=ctx.variables,
    )
    decision = strategy.decide(combat_ctx)
    skill_kws = decision.keywords
    target_skill_name = decision.skill_name
    fallback_coord = decision.fallback_coord
    logger.info(f"[battle_step] Character turn: [{strategy.sect_name}] decision -> [{target_skill_name}] ({decision.description})")

    # Check if target skill is already directly visible (e.g. wheel is already expanded)
    skill_item = _find(items, lambda it: any(kw in it.text for kw in skill_kws))
    if skill_item is not None:
        logger.info(f"[battle_step] Found visible skill [{skill_item.text}] at ({skill_item.center[0]:.0f}, {skill_item.center[1]:.0f})")
        _click(ctx, skill_item.center[0], skill_item.center[1])
        time.sleep(0.3)
        _click(ctx, target_x, target_y)
        logger.info(f"[battle_step] Cast [{skill_item.text}] on target ({target_x:.0f}, {target_y:.0f})")
        time.sleep(0.5)
        return

    # Tap '法术' / skill button at (1045, 685) to expand skill menu
    logger.info("[battle_step] Opening skill menu at (1045, 685)")
    _click(ctx, 1045, 685)
    time.sleep(0.5)
    if ctx.device:
        raw = ctx.device.screencap()
        new_items = _ocr_items(raw)
        wanted = _find(new_items, lambda it: any(kw in it.text for kw in skill_kws))
        if wanted is not None:
            _click(ctx, wanted.center[0], wanted.center[1])
            logger.info(f"[battle_step] Selected [{wanted.text}] from menu at ({wanted.center[0]:.0f}, {wanted.center[1]:.0f})")
        else:
            _click(ctx, fallback_coord[0], fallback_coord[1])
            logger.info(f"[battle_step] Selected fallback [{target_skill_name}] at {fallback_coord}")
        time.sleep(0.3)
        _click(ctx, target_x, target_y)
        logger.info(f"[battle_step] Cast [{target_skill_name}] on target ({target_x:.0f}, {target_y:.0f})")
        time.sleep(0.5)
        return

    time.sleep(0.5)


def capture_frame_items(ctx: PipelineContext, act: NodeAction = None) -> None:
    """Kept as a no-op action so the DAG's sense node can precede recognitions."""
    return None


def classify_screen(ctx: PipelineContext, frame: Any, rec: NodeRecognition = None) -> bool:
    """One OCR per tick; classify the screen into routing flags in ctx.variables."""
    items = _ocr_items(frame)
    v = ctx.variables
    v["_last_frame_items"] = items
    v["_last_frame"] = frame

    v.setdefault("all_dailies_done", False)
    v.setdefault("completed_tasks", [])
    v.setdefault("current_task_done", False)
    v.setdefault("current_task_name", "")

    texts = [getattr(it, "text", "") for it in items]
    centers = [(float(it.center[0]), float(it.center[1])) for it in items]

    # 0. Intercept floating toasts for activity gates
    if any(any(kw in t for kw in ("活跃度不够", "需要活跃度达到50点", "活跃度不足", "活跃度达到50点")) for t in texts):
        logger.warning("[classify] Intercepted toast: 活跃度不足! Marking 运镖 as completed/ineligible.")
        if "运镖" not in v["completed_tasks"]:
            v["completed_tasks"].append("运镖")
        v["current_task_done"] = True
    elif any(any(kw in t for kw in ("挑战次数已用完", "挑战次数不足", "今日挑战次数", "已无挑战次数", "今日已无挑战次数")) for t in texts):
        # 秘境 daily challenge attempts exhausted (live toast: 少侠今日已无挑战次数，明日再来吧).
        logger.warning("[classify] Intercepted toast: 秘境挑战次数用完! Marking 秘境降妖 finished for today.")
        v["mijing_quota_exhausted"] = True
        if "秘境降妖" not in v["completed_tasks"]:
            v["completed_tasks"].append("秘境降妖")
        v["current_task_done"] = True

    # 0.2 Safety: the double-back quit-game confirm (少侠确定离开游戏吗) must NEVER be
    # auto-confirmed — 确定 quits the whole game client.
    v["quit_game_confirm"] = any("离开游戏" in t for t in texts)

    # 0.5 Safety: any dialog offering to spend 仙玉 (秘境 death revive / continue) must
    # never be auto-confirmed — it is money. Exclude it from confirm-button classifications
    # and let dismiss_popups take the safe exit instead.
    v["xianyu_cost_popup"] = any("仙玉" in t for t in texts)

    # 1. In-battle: attack, cancel auto, skills, or pet selector in combat action area
    v["in_battle"] = bool(_find(items, lambda it: (
        it.text in ("攻击", "取消", "自动", "法术", "特技", "防御", "逃跑", "月影瑶光", "月刃")
        or "选择召唤灵" in it.text
    ) and it.center[0] > 800 and it.center[1] > 380))

    # 2. Activity panel: tabs on the left (日常活动, 挑战活动, 竞技休闲, 活动地图) + bottom chests / top header
    has_activity_tabs = bool(_find(items, lambda it: any(kw in it.text for kw in ("日常活动", "挑战活动", "竞技休闲", "即将开启", "活动地图")) and it.center[0] < 320))
    has_activity_chests = any(any(kw in t for kw in ("活跃", "0点刷新", "活动地图")) for t in texts)
    has_activity_header = bool(_find(items, lambda it: ("活" in it.text and "动" in it.text) and 500 < it.center[0] < 750 and it.center[1] < 80))
    has_panel_x = any(c[0] > 1050 and c[1] < 120 and t.strip() in ("×", "X", "x", "✕") for t, c in zip(texts, centers))

    # The left tab labels sometimes merge into one OCR blob ("唤灵奇旅新服特") and the
    # panel × is missed, so also accept the panel by its content: several known daily
    # cards plus the 活跃度 bar text (live 2026-09-26, 活跃度=20 panel went unseen and
    # the pipeline pressed back into the quit-game confirm).
    known_cards_visible = sum(1 for name in ("师门任务", "宝图任务", "运镖", "秘境降妖", "三界奇缘", "科举乡试", "捉鬼任务") if any(name in t for t in texts))
    v["panel_open"] = (not v["in_battle"]) and (
        (has_activity_tabs and (has_activity_chests or has_activity_header or has_panel_x))
        or (has_panel_x and (bool(_find_text(items, "日常活动")) or bool(_find_text(items, "活动地图"))))
        or (known_cards_visible >= 2 and has_activity_chests)
    )
    if v["panel_open"]:
        v["panel_closed_streak"] = 0
        # A successful open resets the fallback miss counter (open_activity_panel
        # increments it while guessing the 活动 button position behind overlays).
        v["panel_fallback_count"] = 0
    else:
        # One missed read must not wipe the visit: while the list is scrolling the
        # tab labels and card names all leave the frame for a tick, and resetting
        # here forgot every card found so far (live 2026-09-26, 宝图/运镖/秘境 read
        # then lost, so nothing was dispatched). Only a panel that stays closed
        # across ticks is a new visit.
        v["panel_closed_streak"] = v.get("panel_closed_streak", 0) + 1
        if v["panel_closed_streak"] >= 2:
            v["panel_scroll_count"] = 0
            v["panel_scrolled"] = False
            v["panel_rescanned"] = False
            v["escort_scrollback_done"] = False
            v["panel_seen_cards"] = {}
            v["daily_rows_aligned"] = False

    # 3. 师门 task board (去完成 or 继续任务 or 自动完成任务)
    v["shimen_board_open"] = bool(_find(items, lambda it: "自动完成任务" in it.text or it.text in ("去完成", "继续任务") or "自动选择每日任务" in it.text))

    # 4. Shop buying dialog (购买 button in shop)
    v["shop_open"] = not v["in_battle"] and bool(_find(items, lambda it: it.text == "购买" and it.center[0] > 800 and it.center[1] > 450))

    # 5. Turn-in dialog (上交 or 给予)
    v["turnin_open"] = not v["in_battle"] and bool(_find(items, lambda it: any(kw in it.text for kw in ("上交", "给予", "上交任务")) and it.center[0] > 600 and it.center[1] > 350))

    # 6. Use item popup (使用) - floating, center, or quick-use right slot
    v["use_item_open"] = (not v["in_battle"] and not v["xianyu_cost_popup"] and not v["quit_game_confirm"]
                          and bool(_find(items, lambda it: it.text == "使用" and 500 < it.center[0] < 1250 and 380 < it.center[1] < 650)))

    # 7. Deposit confirm dialog (确定 / 确认) — never while a 仙玉 cost dialog or the
    # quit-game confirm is up (their 确定 buttons must never be clicked).
    # Requires escort/deposit wording to be present on screen.
    has_deposit_wording = any(any(kw in t for kw in ("押金", "押送", "镖银")) for t in texts)
    v["deposit_open"] = (not v["in_battle"] and not v["xianyu_cost_popup"] and not v["quit_game_confirm"]
                         and has_deposit_wording
                         and bool(_find(items, lambda it: it.text in ("确定", "确认") and 340 < it.center[1] < 500 and 600 < it.center[0] < 900)))

    # 8. NPC dialogue choices
    has_dialog_prompt = bool(_find(items, lambda it: any(kw in it.text for kw in ("请选择要做的事", "请选择", "要做的事", "跳过", "点击继续", "交谈"))))
    has_dialog_choice = bool(_find(items, lambda it: any(kw in it.text for kw in ("师门", "押送普通镖银", "打听藏宝图", "打听强盗", "请安", "领取", "挑战", "进入挑战", "进入秘境", "进入战斗", "秘境")) and it.center[0] > 700 and 340 < it.center[1] < 680))
    # Post-quiz upgrade-guide popup (通关推荐配置 + 前往提升 CTAs): a dismissible popup
    # with an × — never a task dialog, otherwise its 前往/挑战 texts hijack the dialog router.
    guide_popup = bool(_find_text(items, "通关推荐配置")) or bool(
        _find(items, lambda it: "指引" in it.text.replace(" ", "") and not any(kw in it.text for kw in ("排行", "挂机", "社群", "直播")) and 450 < it.center[0] < 800 and it.center[1] < 90)
    )
    v["guide_popup"] = guide_popup
    # Gacha/spend pages (百宠仙池 祈愿, 召唤灵卡册). Their buttons (祈愿1次) sit in the
    # dialog-choice column, so the generic choice fallback clicks them and spends 仙玉
    # (live 2026-09-27: 18 ticks of dialog_choice opened 百宠仙池 mid-秘境). They are
    # popups, closed with the back key — never click anything inside.
    # The world HUD's left promo strip also reads "百宠仙池" (live 2026-09-27, x231),
    # which is not the page — require the page's own buttons, right of that strip. A
    # false positive presses back on the world HUD and raises the quit-game confirm.
    gacha_page = bool(_find(items, lambda it: any(kw in it.text for kw in ("祈愿", "百宠仙池", "召唤灵卡册")) and it.center[0] > 500))
    v["gacha_page"] = gacha_page
    v["dialog_open"] = (not v["in_battle"]) and (not v["panel_open"]) and (not guide_popup) and (not gacha_page) and (has_dialog_prompt or has_dialog_choice)

    # 8.5 Quiz screen (科举/三界奇缘): question ROI + option ROI (upstream Maa_MHXY_MG zones)
    quiz_header = _find(items, lambda it: any(kw in it.text for kw in ("三界奇缘", "科举", "答题", "请作答")) and it.center[1] < 200)
    quiz_question_item = _find(items, lambda it: (
        QUIZ_QUESTION_ROI[0] <= it.center[0] <= QUIZ_QUESTION_ROI[2]
        and QUIZ_QUESTION_ROI[1] <= it.center[1] <= QUIZ_QUESTION_ROI[3]
        and len(it.text.strip()) >= 6
        and not _looks_like_chat_or_quest_line(it.text)
    ))
    quiz_option_count = sum(
        1 for it in items
        if QUIZ_OPTION_ROI[0] <= it.center[0] <= QUIZ_OPTION_ROI[2]
        and QUIZ_OPTION_ROI[1] <= it.center[1] <= QUIZ_OPTION_ROI[3]
        and 1 <= len(it.text.strip()) <= 16
        and it.text.strip() not in ("×", "X", "x", "✕")
    )
    # Main-city top-bar buttons (指引/排行/挂机/社群/直播录像) only exist on the world HUD;
    # a real quiz screen never shows them. Veto quiz_open so crowded city text (player
    # name tags + event banners) cannot masquerade as a question + options.
    # Substring, not exact: OCR glues the top bar into one blob ("53排行挂机社群直播录像…"),
    # which an exact match misses, so the world HUD masquerades as a quiz (live 2026-09-27).
    main_ui_marker = _find(items, lambda it: any(kw in it.text for kw in ("指引", "排行", "挂机", "社群", "直播录像")) and it.center[1] < 120)
    # A done/summary screen (恭喜少侠完成所有题目！) is a quiz screen too — its vertical
    # title sits outside the header band, so route it via the DONE keywords directly.
    # Require a quiz-context marker alongside the done keywords: unrelated screens may
    # contain 明日再来/今日已完成 without being the quiz.
    quiz_done_hit = _find(items, lambda it: any(kw in it.text for kw in QUIZ_DONE_KWS))
    if quiz_done_hit is not None:
        quiz_context = _find(items, lambda it: any(kw in it.text for kw in ("三界奇缘", "科举", "准确率", "恭喜", "请作答")))
        if quiz_context is None:
            quiz_done_hit = None
    # Escort auto-travel shows the world map with a 距离运镖完成 countdown — its
    # colorful location labels parse as fake questions, so it must never route to
    # quiz_answer; the cart moves on its own and the pipeline just waits.
    v["escort_traveling"] = any("距离运镖" in t or "运镖完成" in t for t in texts)
    # 首席弟子竞选 is a vote popup (rows of 投票 + a top ×), not a quiz: its title and
    # candidate lines otherwise satisfy the question+options heuristic and the quiz node
    # blind-clicks it forever (live 2026-09-26).
    chief_vote_popup = bool(_find(items, lambda it: "首席弟子" in it.text and it.center[1] < 150))
    # 剑会群雄报名弹窗 (5v5团队竞赛 / 报名)
    jianhui_popup = bool(_find(items, lambda it: "剑会群雄" in it.text and any("报名" in t for t in texts)))
    # The player stall (摆摊) puts its tab labels ("我要出售 公示物品 …") inside the
    # question ROI and its item rows inside the option ROI, so the question+options
    # heuristic fires and quiz_answer (higher priority than shop_buy) blind-clicks the
    # stall forever (live 2026-09-26, 师门 stuck at 5/10). A stall is a shop.
    stall_open = any("摆摊" in t or "我要出售" in t or "公示物品" in t for t in texts)
    # 时装外观展厅: a merged player-ID line ("ID442951442时装未穿戴") lands in the
    # question ROI and the gear-slot tab labels (坐骑/名片背景/…) land in the option
    # ROI, so the question+options heuristic fires and quiz_answer blind-clicks the
    # window forever — 150+ clicks with the 宝图 run stuck mid-way (live 2026-09-29).
    # It is a sub-window, closed via its top-right ×.
    fashion_showroom = sum(
        1 for kw in ("头饰", "坐骑", "称谓特效", "名片背景", "入场特效", "武器幻彩", "试穿", "保存穿搭")
        if any(kw in t for t in texts)
    ) >= 2
    # 门派目标 sub-window ("本周门派目标×示威亲善" title + tab rows): opens when the
    # 师门 tracker leads into the mentor dialog chain. Its merged title line lands in
    # the question ROI and tab rows in the option ROI, so quiz_answer blind-clicks it
    # in a loop (live 2026-09-29, recurring every few minutes during 师门 resume).
    # It is a sub-window, closed via its top-right ×.
    sect_goal_window = any("本周门派目标" in t or "示威亲善" in t for t in texts)
    # Post-battle guild recruit page ("加入帮派…推荐帮派" + 申请入帮 rows). Its
    # title sits in the question ROI and the apply buttons sit in the option ROI,
    # so the question+options heuristic fires and quiz_answer (higher priority than
    # popup dismiss) blind-clicks 申请入帮 forever (live 2026-09-26, 171 clicks,
    # 宝图 abandoned at 12:11). It is a popup, closed via 本周不再提醒.
    guild_recruit = any("推荐帮派" in t or "申请入帮" in t or "本周不再提醒" in t for t in texts)
    # Scrolling world activity banners (青丘奇珍 / 巅峰联赛 / 时空之隙) and the
    # "点击任意地方继续" story-advance prompt land in the question ROI and pair with
    # stray mid-screen candidate/banner text as "options", so quiz_answer blind-clicks
    # first option on the world HUD — never a real quiz (live 2026-09-29, 师门 10/10).
    # Also covers the in-game "每日新发现" cross-game ad carousel, whose scrolling
    # ad copy ("上线领全武将", "9月23日首发", "邀你战三界，共渡灵妖劫") reaches the
    # question ROI and was mis-routed to quiz_answer for 16 ticks (live 2026-09-30
    # 11:xx, 三界奇缘 run stuck on a promo carousel, never reached the panel).
    banner_noise = any(
        kw in t for t in texts
        for kw in (
            "青丘奇珍", "灵狐栖梦", "时空之隙", "巅峰联赛", "点击任意地方继续", "正在火热进行中",
            "每日新发现", "上线领全武将", "首发，可以逛", "可以逛的武侠", "邀你战三界", "共渡灵妖劫", "共遮灵妖劫",
            "中秋华诞", "双节同庆",
            "当前最高层数",
        )
    )
    v["fashion_showroom"] = fashion_showroom
    v["sect_goal_window"] = sect_goal_window
    v["quiz_open"] = (not v["in_battle"]) and (not v["dialog_open"]) and (not v["panel_open"]) and (not v["deposit_open"]) and (main_ui_marker is None) and (not guide_popup) and (not v["escort_traveling"]) and (not chief_vote_popup) and (not jianhui_popup) and (not stall_open) and (not guild_recruit) and (not fashion_showroom) and (not sect_goal_window) and (not v["turnin_open"]) and (not banner_noise) and bool(
        quiz_header or quiz_done_hit or (quiz_question_item is not None and quiz_option_count >= 2)
    )

    # 9. Auto walking
    v["auto_walking"] = any("自动寻路中" in t or "自动巡逻中" in t for t in texts)

    # 10. Tracker active (evaluate before popups to avoid false positive subwindow alerts)
    curr_task = v.get("current_task_name", "")
    daily_queue = v.get("daily_queue") or ["师门任务", "宝图任务", "秘境降妖", "科举乡试", "三界奇缘", "运镖"]
    completed_tasks = v.setdefault("completed_tasks", [])

    # Only track daily activities that are in queue and NOT completed
    daily_kws = []
    if "师门任务" in daily_queue and "师门任务" not in completed_tasks:
        daily_kws.append("师门")
    if "宝图任务" in daily_queue and "宝图任务" not in completed_tasks:
        daily_kws.extend(["宝图", "贼王", "强盗"])
    if "运镖" in daily_queue and "运镖" not in completed_tasks:
        daily_kws.extend(["运镖", "押镖", "镖银"])
    if "秘境降妖" in daily_queue and "秘境降妖" not in completed_tasks:
        daily_kws.extend(["秘境", "降妖", "挑战", "关"])
    if "科举乡试" in daily_queue and "科举乡试" not in completed_tasks:
        daily_kws.extend(["科举", "乡试"])

    tracker_item = _find(items, lambda it: any(kw in it.text for kw in daily_kws) and 1000 < it.center[0] < 1280 and 140 < it.center[1] < 340)
    v["tracker_active"] = tracker_item is not None

    if tracker_item:
        if not curr_task:
            if "师门" in tracker_item.text:
                v["current_task_name"] = "师门任务"
                curr_task = "师门任务"
            elif any(kw in tracker_item.text for kw in ("宝图", "贼王", "强盗")):
                v["current_task_name"] = "宝图任务"
                curr_task = "宝图任务"
            elif any(kw in tracker_item.text for kw in ("运镖", "押镖")):
                v["current_task_name"] = "运镖"
                curr_task = "运镖"
            elif any(kw in tracker_item.text for kw in ("秘境", "降妖", "挑战", "关")):
                v["current_task_name"] = "秘境降妖"
                curr_task = "秘境降妖"

        # Bracket-agnostic full-progress detection: OCR often mixes half/full-width
        # parens ("（10/10)" or "(10/10）"), which the exact-match literals missed and
        # left a 10/10 task un-marked-complete (live 2026-09-29, 师门 reached 10/10).
        _tracker_full = re.search(r"[（(]\s*(\d+)\s*/\s*(\d+)\s*[）)]", tracker_item.text)
        if any(cnt in tracker_item.text for cnt in ("(10/10)", "（10/10）", "(20/20)", "（20/20）", "(3/3)", "（3/3）")) or (
            _tracker_full and _tracker_full.group(1) == _tracker_full.group(2) and int(_tracker_full.group(2)) in (3, 10, 20)
        ):
            v["current_task_done"] = True
            logger.info(f"[classify] Current task [{curr_task}] completed according to tracker: {tracker_item.text}")
            if curr_task and curr_task not in completed_tasks:
                completed_tasks.append(curr_task)

    # 11. Check if a blocking promo overlay is present (e.g. 银钥匙半价, 首充特惠)
    promo_text = _find(items, lambda it: any(kw in it.text for kw in ("银钥匙", "半价啦", "每周5折", "限时特卖", "首充礼包", "更新公告", "满月如璧")) and it.center[1] < 400)
    promo_x = _find(items, lambda it: it.text in ("×", "X", "x", "✕") and 500 < it.center[0] < 1250 and it.center[1] < 300)
    has_blocking_promo = (promo_text is not None and promo_x is not None)

    # Stray full-screen sub-windows like 伙伴助战 / 百宝谱 / 排行榜 (only valid when main tracker is not visible)
    has_subwindow = (not v["tracker_active"]) and any(any(kw in t for kw in ("伙伴助战", "百宝谱", "排行榜", "论坛", "招募大厅")) and c[1] < 200 for t, c in zip(texts, centers))
    # Full-screen event pages with no corner × (九转天阶赛季) and reward summaries
    # (师门任务完成) cover the HUD, so the activity-button tap lands behind them.
    # "九转天阶" alone also appears in the world chat ticker ("九转天阶·新秀二级"),
    # which is not a popup — require the season-page wording (live 2026-09-26: the
    # loose keyword pressed back on the world HUD and raised the quit-game confirm).
    v["fullscreen_popup"] = (not v["in_battle"]) and (not v["panel_open"]) and any(
        kw in t for t in texts for kw in ("全新赛季", "任务完成")
    )
    # Cash-shop pages (超值月卡/尊享月卡, 首充好礼, 累充奖励) carry no corner × that OCR
    # reads, so nothing else closes them and the pipeline stalls tapping behind the
    # page (live 2026-09-27, 宝图 stuck on the 月卡 page). They are popups; the back
    # key closes them. Never tap their 购买 buttons.
    # The world HUD's left promo strip repeats these titles ("首充礼包" at x146,
    # "新服特惠" at x217), so only count them right of the strip (live 2026-09-27: a
    # false positive pressed back on the world HUD and raised the quit-game confirm).
    paywall = (not v["in_battle"]) and (not v["panel_open"]) and any(
        kw in t and c[0] > 400
        for t, c in zip(texts, centers)
        for kw in ("月卡", "首充好礼", "累充奖励", "元购买", "新服特惠", "新服战令", "星途祈愿", "折扣礼包")
    )
    # Guild recruit page vetoed out of quiz above; route it to the popup dismisser,
    # which closes it with the back key (its 本周不再提醒 checkbox does not close it,
    # and tapping outside the card does nothing — live 2026-09-26).
    guild_recruit = any("推荐帮派" in t or "申请入帮" in t or "本周不再提醒" in t for t in texts)

    # 剑会群雄报名弹窗: 独立弹窗标题在 (666,270)，含「5v5团队竞赛」或「报名」按钮
    jianhui_popup = bool(_find(items, lambda it: "剑会群雄" in it.text and (it.center[1] < 300 or any("报名" in t for t in texts)) and not any(kw in t for t in texts for kw in ("指引", "排行", "挂机"))))

    is_functional_window = (
        v["in_battle"] or v["panel_open"] or v["shimen_board_open"]
        or v["shop_open"] or v["turnin_open"] or v["deposit_open"]
        or v["dialog_open"] or v["use_item_open"] or v["quiz_open"]
    )

    # In-game cross-game promo carousel ("每日新发现" full-screen page pushing other
    # games) has no ×, no 关闭, no HUD 活动 button — classify otherwise sees "nothing
    # functional" and the pipeline keeps trying open_panel against a screen with no
    # panel, and reads the 领取 button as a task-specific dialog option (live 2026-09-30
    # 11:xx: stuck 90 ticks, never reached the activity panel). It closes with a single
    # BACK; route it to dismiss_popup. dialog_open is deliberately NOT excluded — the
    # 领取 button on this page can register as a dialog option, and popup_open is
    # evaluated before dialog_open in daily_dailies.json. The banner_noise set above
    # already vetoes quiz. A genuine NPC dialog never carries these promo banner texts,
    # so this cannot misfire on real task dialogs.
    promo_carousel = (not v["in_battle"]) and not (
        v["panel_open"] or v["shimen_board_open"] or v["shop_open"]
        or v["turnin_open"] or v["deposit_open"] or v["use_item_open"]
        or v["quiz_open"]
    ) and not any(
        kw in t for t in texts
        for kw in ("请选择要做的事", "请选择", "要做的事")
    ) and any(
        kw in t for t in texts
        for kw in (
            "每日新发现", "上线领全武将", "首发，可以逛", "可以逛的武侠",
            "邀你战三界", "共渡灵妖劫", "共遮灵妖劫",
        )
    )
    v["promo_carousel"] = promo_carousel

    # Chat compose bar focused (world chat input): occludes the whole HUD and its
    # 确定 would SEND a chat message (live 2026-10-02: a walk-out/relaunch left the
    # composer up, popup_open stayed False and the runner blind-tapped 活动 through
    # the input bar until the same-coord watchdog fired). The input placeholder, or
    # the 发送+取消+确定 system row together, is the signature — chat panels with
    # history only never show it.
    chat_input_open = any("点击这里输入" in t for t in texts) or (
        any("发送" in t for t in texts)
        and any(t.replace(" ", "") == "取消" for t in texts)
        and any(t.replace(" ", "") == "确定" for t in texts)
    )
    v["chat_input_open"] = chat_input_open

    v["popup_open"] = bool(v["xianyu_cost_popup"]) or bool(v["quit_game_confirm"]) or bool(v["guide_popup"]) or bool(v.get("gacha_page")) or bool(v["fullscreen_popup"]) or bool(paywall) or bool(guild_recruit) or bool(jianhui_popup) or bool(has_blocking_promo) or bool(has_subwindow) or bool(v.get("fashion_showroom")) or bool(v.get("sect_goal_window")) or bool(promo_carousel) or bool(chat_input_open) or ((not is_functional_window) and (
        any(c[0] > 1050 and c[1] < 120 and t.strip() in ("×", "X", "x", "✕") for t, c in zip(texts, centers))
        or any(any(kw in t.strip() for kw in ("确认关闭", "点击空白处", "点击屏幕", "轻触屏幕", "满月如璧", "我知道了")) for t in texts)
        or any(t.strip() in ("×", "X", "x", "✕") and 600 < c[0] < 1250 and c[1] < 250 for t, c in zip(texts, centers) if not v["shop_open"])
    ))

    # Determine if we need to open the activity panel:
    has_active_work = (
        v["in_battle"] or v["popup_open"] or v["shimen_board_open"]
        or v["shop_open"] or v["turnin_open"] or v["deposit_open"]
        or v["dialog_open"] or v["use_item_open"] or v["auto_walking"]
        or v["quiz_open"] or v["escort_traveling"]
        or (v["tracker_active"] and not v.get("current_task_done"))
    )
    v["need_open_panel"] = not has_active_work and not v["panel_open"] and not v.get("all_dailies_done")

    # No dialog on screen means any 领取-match streak from earlier is stale — clear it
    # so a later genuine claim chain (its first click legitimately earns a click) is
    # not penalized by the residue of a dead one.
    if not v["dialog_open"] and "dialog_claim_streak" in ctx.variables:
        ctx.variables.pop("dialog_claim_streak", None)

    # Same idea for the quiz bank-miss refusal streak: it only means something while
    # the same misparsed "quiz" screen persists; a fresh quiz_open (real quiz window,
    # banner gone) must start from zero. The promo BACK streak clears when no popup
    # is classified at all, so each promo episode gets its own bounded burst.
    if not v["quiz_open"] and "quiz_refusal_streak" in ctx.variables:
        ctx.variables.pop("quiz_refusal_streak", None)
    if not v["popup_open"] and "promo_back_streak" in ctx.variables:
        ctx.variables.pop("promo_back_streak", None)
    # promo_block_latch means "currently stuck behind a promo that ignores BACK";
    # it clears with the promo itself so a later legitimate completion is not
    # masked, while a promo persisting to the end keeps the Summary honest.
    if not v["popup_open"] and ctx.variables.get("promo_block_latch"):
        ctx.variables.pop("promo_block_latch", None)
        logger.warning("[classify] promo_block_latch cleared — promo overlay gone")

    # Same-coordinate-repeat watchdog (see _click): battle or an open activity panel is
    # unambiguous progress, so a repeat streak carried over from a prior dead screen is
    # stale. Also reset whenever the click target itself has moved on (handled in _click),
    # but classify running without any click in between (e.g. between ticks) must not
    # accumulate residue across a genuine scene change.
    if (v["in_battle"] or v["panel_open"]) and "_click_repeat" in ctx.variables:
        ctx.variables.pop("_click_repeat", None)
        ctx.variables.pop("_last_click_xy", None)
        ctx.variables.pop("_click_cells", None)

    # Backward compatibility flags
    v["escort_dialog"] = bool(_find_text(items, "押送"))
    v["escort_running"] = v["in_battle"] or bool(_find(
        items, lambda it: ("运镖" in it.text or "镖银" in it.text)
        and 450 < it.center[0] < 900 and 60 < it.center[1] < 400))
    if v["panel_open"]:
        v["escort_done"] = (_find_text(items, "运镖") is None)

    logger.info(
        f"[classify] battle={v['in_battle']} popup={v['popup_open']} panel={v['panel_open']} "
        f"shimen_board={v['shimen_board_open']} shop={v['shop_open']} turnin={v['turnin_open']} "
        f"dialog={v['dialog_open']} quiz={v['quiz_open']} walking={v['auto_walking']} tracker={v['tracker_active']} "
        f"need_panel={v['need_open_panel']} done={v.get('all_dailies_done')}"
    )
    return True


# --- activity panel parser & multi-task dispatching --------------------------

def _parse_activity_panel(items: list) -> List[dict]:
    """Parse activity cards in the open 活动 panel.

    Each card has a title (e.g. 师门任务, 宝图任务, 运镖, 秘境降妖),
    progress count (e.g. 次数0/10, 次数10/10, 次数0/3, 次数3/3; or 次数不限),
    a 活跃 reward counter (e.g. 活跃11/25 on the 秘境 row),
    completion status (done = True when a green 完成 pill sits at the button spot,
    text has 已完成, or a counter is maxed out),
    and a 参加 button if available.
    """
    cards = []
    known_activities = ["师门任务", "宝图任务", "运镖", "秘境降妖", "捉鬼任务队", "三界奇缘", "科举乡试"]

    for act_name in known_activities:
        title_item = _find(items, lambda it: act_name in it.text and 300 < it.center[0] < 1000 and 80 < it.center[1] < 550)
        if title_item is None:
            continue

        tx, ty = title_item.center[0], title_item.center[1]

        # Collect nearby card items
        card_items = [
            it for it in items
            if abs(it.center[0] - tx) < 220 and -20 <= (it.center[1] - ty) <= 90
        ]

        card_text = " ".join(getattr(it, "text", "") for it in card_items)
        is_done = "已完成" in card_text
        is_time_gated = "开启" in card_text

        m = re.search(r"次数\s*(\d+)/(\d+)", card_text)
        current_cnt, max_cnt = 0, 0
        if m:
            current_cnt, max_cnt = int(m.group(1)), int(m.group(2))
            if current_cnt >= max_cnt and max_cnt > 0:
                is_done = True

        # 活跃 reward counter (e.g. 秘境 活跃11/25): the honest reward progress even
        # when the card already carries the game's 完成 pill.
        hm = re.search(r"活跃\s*(\d+)/(\d+)", card_text)
        h_current, h_max = (int(hm.group(1)), int(hm.group(2))) if hm else (0, 0)
        if h_max > 0 and h_current >= h_max:
            is_done = True

        # Find 参加 button for this card; the green 完成 pill occupies the same spot
        # on finished rows and is the game's authoritative done signal.
        # The 参加 button is on the same card but OCR puts the title and the button on
        # different rows, and which is higher depends on the scroll position (live
        # 2026-09-28: 三界奇缘 title at y480 while its 参加 sat at y371, 109px ABOVE it).
        # Search a wide vertical band both ways and take the nearest button to the right.
        # A card that is not yet open (e.g. 11:00开启 / 17:00开启) has no 参加 button;
        # don't falsely match an adjacent card's button (live 2026-09-28).
        join_cands = [
            it for it in items
            if it.text == "参加" and 0 < (it.center[0] - tx) < 340 and abs(it.center[1] - ty) <= 140
        ] if not is_time_gated else []
        join_btn = min(join_cands, key=lambda it: abs(it.center[1] - ty)) if join_cands else None
        done_pill = _find(items, lambda it: it.text == "完成" and 0 < (it.center[0] - tx) < 260 and abs(it.center[1] - ty) < 45)
        if done_pill is not None:
            is_done = True

        cards.append({
            "name": act_name,
            "title_pos": (tx, ty),
            "is_done": is_done,
            "is_time_gated": is_time_gated,
            "current_cnt": current_cnt,
            "max_cnt": max_cnt,
            "h_current": h_current,
            "h_max": h_max,
            "join_btn": (join_btn.center[0], join_btn.center[1]) if join_btn else None,
            "card_text": card_text,
        })
    return cards


def _extract_huoyue(items: list) -> int:
    """Extract current 活跃度 score from bottom progress area of 活动 panel."""
    # Method 1: Look for isolated digits in the progress bar area (y: 605..655, x: 350..1150)
    for it in items:
        cy = it.center[1]
        cx = it.center[0]
        if 605 < cy < 655 and 350 < cx < 1150:
            txt = getattr(it, "text", "").strip()
            if txt.isdigit():
                try:
                    return int(txt)
                except ValueError:
                    pass
            m = re.search(r"\b(\d{1,3})\b", txt)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass

    # Method 2: Look for '活跃' followed by digits in lower half
    for it in items:
        txt = getattr(it, "text", "").strip()
        m = re.search(r"活跃[^\d]*(\d{1,3})", txt)
        if m and it.center[1] > 550:
            try:
                return int(m.group(1))
            except ValueError:
                pass

    return 0


# 活跃度 progress-bar geometry (1280x720 base): the green fill spans x 326..1067
# at y 618..648, calibrated against the 20/40/60/80/100活跃 tick labels on a live
# panel. The score bubble is stylized and OCR-blind, so the fill width is the
# reliable signal.
HUOYUE_BAR_X = (326, 1067)
HUOYUE_BAR_Y = (618, 648)


def _extract_huoyue_from_frame(frame: Any) -> int:
    """Measure the green fill of the 活跃度 progress bar directly from pixels.

    RapidOCR cannot read the stylized score bubble on the bar (live-verified
    2026-09-25: bubble "41" never appears in OCR output), so when OCR-based
    extraction fails this pixel fallback measures the fill's right edge.
    Known bias: the mint-green bubble overlaps the fill's right edge, so readings
    can overshoot by ~1 point (live: bubble 61 read 62, bubble 70 read 71) —
    irrelevant for the 50-point escort gate.
    """
    if frame is None:
        return 0
    try:
        x0, x1 = HUOYUE_BAR_X
        y0, y1 = HUOYUE_BAR_Y
        band = frame[y0:y1, x0:x1]
        if band is None or band.size == 0:
            return 0
        fill_right = -1
        for xx in range(band.shape[1] - 1, -1, -1):
            for px in band[:, xx]:
                gg, bb, rr = int(px[1]), int(px[0]), int(px[2])
                if gg > 120 and gg - rr > 40 and gg - bb > 40:
                    fill_right = xx
                    break
            if fill_right >= 0:
                break
        if fill_right < 0:
            return 0
        score = round(fill_right / (x1 - x0) * 100)
        return max(0, min(100, int(score)))
    except Exception:
        return 0


def handle_activity_panel(ctx: PipelineContext, act: NodeAction) -> None:
    """Intelligently dispatch daily activities from the open 活动 panel:
    1. Read daily_queue (defaults to ["师门任务", "宝图任务", "秘境降妖", "科举乡试", "三界奇缘", "运镖"]).
    2. Check completion status of tasks.
    3. Read current 活跃度; check prerequisites (e.g. 运镖 requires 50 活跃度).
    4. Pick the first uncompleted, eligible task and click its 参加 button.
    5. If all daily tasks are completed, claim activity chests and close panel.
    """
    items = ctx.variables.get("_last_frame_items") or []
    v = ctx.variables
    daily_queue = v.get("daily_queue") or ["师门任务", "宝图任务", "秘境降妖", "科举乡试", "三界奇缘", "运镖"]
    completed_tasks = ctx.variables.setdefault("completed_tasks", [])
    # Time-gated activities (live 2026-09-29 panel: 三界奇缘 "今日 11:00开启",
    # 科举乡试 "今日 17:00开启", no 参加 button) are neither done nor unfinished.
    # Treating them as "read but not finished" left them in still_open, and the
    # still_open guard closed the panel before the chest branch ever ran — the
    # 20-活跃 chest was never claimed at 活跃度 37. Tracked separately from
    # completed_tasks so a run still alive when the gate passes (11:00/17:00)
    # can dispatch them afterwards.
    not_runnable_today = ctx.variables.setdefault("not_runnable_today", [])

    # The score bubble is OCR-blind and PARTIAL READS happen (live: bubble "61" read
    # as "6", wrongly locking escort) — the pixel measurement is the primary source;
    # OCR-based extraction is only the fallback when no frame/bar is available.
    current_huoyue = _extract_huoyue_from_frame(ctx.variables.get("_last_frame"))
    if current_huoyue <= 0:
        current_huoyue = _extract_huoyue(items)
    else:
        logger.info(f"[daily_panel] 活跃度 via bar-pixel measurement: {current_huoyue}")
    ctx.variables["current_huoyue"] = current_huoyue
    logger.info(f"[daily_panel] Current 活跃度: {current_huoyue}")

    cards = _parse_activity_panel(items)
    # 科举乡试周六日没有，如果在队列中直接标为完成，避免滚动6次烧空预算
    if "科举乡试" in daily_queue and "科举乡试" not in completed_tasks:
        today_date = date.today()
        # Monday=0, Sunday=6
        if today_date.weekday() >= 5:
            logger.info("[daily_panel] 科举乡试 is not available on weekends; marking completed")
            completed_tasks.append("科举乡试")
    # Remember every card seen this visit so a task that scrolled out of view is
    # still known (done-ness, counters). But a 参加 button only exists where it was
    # just read: a remembered coordinate points at whatever row scrolled there since
    # (live 2026-09-26: remembered 宝图 button kept clicking 帮派任务's 参加).
    seen = v.setdefault("panel_seen_cards", {})
    visible_names = {c["name"] for c in cards}
    for c in cards:
        prev = seen.get(c["name"])
        # Counters survive a partial re-read (a row half cut by scrolling), but the
        # 参加 coordinate does not: the list moved, so a remembered point now hits
        # another row's button (live 2026-09-26: 宝图's (669,263) clicked 三界奇缘).
        if prev is not None:
            c = dict(c)
            for key in ("current_cnt", "max_cnt", "h_current", "h_max"):
                c[key] = max(c[key], prev.get(key, 0))
            if prev.get("is_done"):
                c["is_done"] = True
        seen[c["name"]] = c
    cards_by_name = {}
    for name, c in seen.items():
        merged = dict(c)
        if name not in visible_names:
            merged["join_btn"] = None
        cards_by_name[name] = merged

    logger.info(f"[daily_panel] Found {len(cards)} activity cards: {[(c['name'], 'done' if c['is_done'] else 'pending', c['join_btn'] is not None) for c in cards]}")

    for c in cards:
        if c["is_done"] and c["name"] not in completed_tasks:
            logger.info(
                f"[daily_panel] Activity [{c['name']}] marked as completed "
                f"(次数 {c['current_cnt']}/{c['max_cnt']}, 活跃 {c['h_current']}/{c['h_max']})"
            )
            completed_tasks.append(c["name"])

    # 秘境 honesty: the game pills the row 完成 once today's challenge quota is used,
    # but its 活跃 reward may be far from maxed (live 2026-09-25: 11/25 at 第6关).
    mijing_card = cards_by_name.get("秘境降妖")
    if mijing_card and mijing_card["is_done"] and mijing_card["h_max"] > 0 and mijing_card["h_current"] < mijing_card["h_max"]:
        logger.warning(
            f"[daily_panel] 秘境降妖 pill-marked 完成 but 活跃 {mijing_card['h_current']}/{mijing_card['h_max']} — "
            "今日挑战额度已用完，剩余活跃度需明日继续闯关（进度已保存）。"
        )
            
    # Some queued cards sit below the panel's first screenful (live: 师门/宝图/秘境
    # are below the fold). Scroll and re-scan on the next tick BEFORE any dispatch
    # decision, so queue priority is honored on the full list and below-fold tasks
    # are never skipped or falsely completed just because they were invisible.
    # A card already seen this visit counts even when it has scrolled off: the scan
    # only needs to find each queued task once, then dispatch whatever button is on
    # screen. Otherwise the list scrolls for the whole budget and never clicks.
    # A time-gated card whose gate has passed this run (its 参加 button is now
    # parsed and the card no longer reads *开启*) is runnable again — drop it
    # from the not-runnable list so dispatch can pick it up.
    for t in list(not_runnable_today):
        c = cards_by_name.get(t)
        if c and c["join_btn"] and not c["is_done"] and not c["is_time_gated"]:
            not_runnable_today.remove(t)
            logger.info(f"[daily_panel] [{t}] time gate passed; dispatchable again")

    missing_queued = [t for t in daily_queue if t not in completed_tasks and t not in not_runnable_today and t not in cards_by_name]
    scroll_count = ctx.variables.setdefault("panel_scroll_count", 0)
    # Scrolling lands the panel somewhere mid-list (it remembers its position and a
    # swipe can switch tabs), so a card seen on tick 1 is gone on tick 3. After the
    # scan budget is spent, scroll back to the top and judge from there — otherwise
    # the close-out below marks every card that scrolled out of view as done (live
    # 2026-09-26: 师门 stopped at 9/10 while the panel reported all six complete).
    visible_unfinished = [t for t in daily_queue if t not in completed_tasks and t in cards_by_name]
    # A queued card that is on screen AND startable must be dispatched before any more
    # scrolling. Otherwise one card the scan can never find (科举乡试, live 2026-09-27)
    # burns the whole scroll budget while a visible, startable card (三界奇缘, 参加
    # parsed on tick 1) is never clicked and the pass ends with nothing done.
    startable_now = [
        t for t in visible_unfinished
        if cards_by_name[t]["join_btn"] and not cards_by_name[t]["is_done"]
    ]
    if startable_now:
        missing_queued = []
    if missing_queued and visible_unfinished and v.get("panel_scrolled") and scroll_count >= 2 and not v.get("panel_rescanned"):
        logger.info(f"[daily_panel] Scan budget spent, still missing {missing_queued}; scrolling back to top to re-judge")
        v["panel_rescanned"] = True
        v["panel_scroll_count"] = 0
        if ctx.device is not None and hasattr(ctx.device, "swipe"):
            ctx.device.swipe(735, 200, 735, 620)
            time.sleep(0.4)
            ctx.device.swipe(735, 200, 735, 620)
        time.sleep(1.5)
        return
    if missing_queued and scroll_count < 6:
        logger.info(
            f"[daily_panel] Queued cards not visible yet ({missing_queued}); scrolling panel ({scroll_count + 1}/6)"
        )
        ctx.variables["panel_scroll_count"] = scroll_count + 1
        ctx.variables["panel_scrolled"] = True
        # A full-screen swipe (480 -> 160) jumps past the next row of cards, so the
        # two screenfuls never overlap and queued cards stay "never parsed" (live
        # 2026-09-26: 宝图/秘境/运镖 seen on tick 1, gone after one swipe). A short
        # nudge keeps the lists overlapping.
        if ctx.device is not None and hasattr(ctx.device, "swipe"):
            ctx.device.swipe(735, 420, 735, 300)
        time.sleep(1.5)
        return

    target_task = None
    target_card = None
    now = time.time()
    # A card whose 参加 button is on screen beats queue order. Otherwise the first
    # queued task (宝图) keeps the panel scrolling forever while 三界奇缘, which is
    # visible and startable, is never clicked (live 2026-09-26).
    for task_name in daily_queue:
        if task_name in completed_tasks:
            continue
        # Dispatch debounce: clicking 参加 again while the previous dialog cycle is
        # still animating races a duplicate accept (live: double 押送 dialogs).
        if (
            task_name == v.get("last_dispatch_task")
            and now - v.get("last_dispatch_time", 0.0) < 30
        ):
            logger.info(f"[daily_panel] [{task_name}] dispatched {now - v.get('last_dispatch_time', 0.0):.0f}s ago; waiting for its dialog flow")
            continue
        card = cards_by_name.get(task_name)

        # Game-gated 秘境 (挑战次数用完 toast / 仙玉死亡弹窗安全退出) cannot run any
        # further today: mark finished but surface the honest counter, since the
        # 活跃度 reward only maxes out at 次数10/10.
        if task_name == "秘境降妖" and (ctx.variables.get("mijing_quota_exhausted") or ctx.variables.get("mijing_blocked")):
            reason = "挑战次数用完" if ctx.variables.get("mijing_quota_exhausted") else "仙玉复活弹窗(未花费，安全退出)"
            if card and card["h_max"] > 0:
                prog = f"活跃 {card['h_current']}/{card['h_max']}"
            elif card and card["max_cnt"] > 0:
                prog = f"次数 {card['current_cnt']}/{card['max_cnt']}"
            else:
                prog = "未知"
            logger.warning(
                f"[daily_panel] 秘境降妖 gated by game ({reason}); progress {prog} — "
                "秘境活跃度按闯关进度累积，未拿满部分需次日继续."
            )
            completed_tasks.append(task_name)
            continue

        if card and not card["is_done"] and not card["join_btn"] and "开启" not in card["card_text"]:
            logger.warning(
                f"[daily_panel] Activity [{task_name}] not done ({card['current_cnt']}/{card['max_cnt']}) "
                "but no 参加 button parsed (panel scroll/OCR miss); cannot dispatch."
            )
        if card and not card["is_done"] and card["join_btn"]:
            # Prerequisite gate: 运镖 requires 50 活跃度 in 《梦幻西游手游》.
            # Defer instead of abandoning: 活跃度 keeps rising while other dailies run,
            # so retry on every later panel visit instead of permanently skipping.
            if task_name == "运镖" and current_huoyue < 50:
                logger.warning(
                    f"[daily_panel] Activity [{task_name}] requires 50 活跃度, but current is {current_huoyue}. "
                    "Deferred: will retry after other dailies raise 活跃度."
                )
                ctx.variables["escort_deferred"] = True
                continue

            # First startable task in queue order wins; keep looking so an earlier
            # queued task whose button is also on screen is preferred.
            if target_task is None:
                target_task = task_name
                target_card = card
            
    if target_task is None:
        # Nothing startable is on screen, but a queued task has a known row when the
        # list is scrolled to the top. Scroll up and use that fixed row next tick
        # instead of clicking a coordinate remembered from another scroll position.
        for task_name in daily_queue:
            if task_name in completed_tasks or task_name not in DAILY_ROW_JOIN:
                continue
            card = cards_by_name.get(task_name)
            if card is None or card["is_done"]:
                continue
            if task_name in not_runnable_today:
                continue  # still time-gated (e.g. 17:00开启): no fixed row to click
            if task_name == "运镖" and current_huoyue < 50:
                continue
            if v.get("daily_rows_aligned"):
                if card["join_btn"] is None and "参加" not in card["card_text"]:
                    continue  # its row was read and really has no 参加 button
                jx, jy = DAILY_ROW_JOIN[task_name]
                logger.info(f"[daily_panel] Starting [{task_name}] via fixed top-of-list row at ({jx}, {jy})")
                v["current_task_name"] = task_name
                v["current_task_done"] = False
                v["last_dispatch_task"] = task_name
                v["last_dispatch_time"] = now
                _click(ctx, jx, jy)
                time.sleep(2.0)
                return
            logger.info(f"[daily_panel] [{task_name}] not on screen; scrolling the list to the top for its fixed row")
            v["daily_rows_aligned"] = True
            if ctx.device is not None and hasattr(ctx.device, "swipe"):
                ctx.device.swipe(735, 250, 735, 560)
                time.sleep(0.4)
                ctx.device.swipe(735, 250, 735, 560)
            time.sleep(1.2)
            return

    if target_task and target_card and target_card["join_btn"]:
        jx, jy = target_card["join_btn"]
        logger.info(f"[daily_panel] Starting daily task [{target_task}] via 参加 button at ({jx:.0f}, {jy:.0f})")

        ctx.variables["current_task_name"] = target_task
        ctx.variables["current_task_done"] = False
        v["last_dispatch_task"] = target_task
        v["last_dispatch_time"] = now
        if target_task == "运镖":
            ctx.variables["escort_deferred"] = False
            logger.info(f"[daily_panel] Escort finally dispatched (活跃度={current_huoyue} >= 50)")
        _click(ctx, jx, jy)
        time.sleep(2.0)
        return

    # Terminal escort decision before closing the panel (no eligible target left):
    if "运镖" in daily_queue and "运镖" not in completed_tasks:
        if current_huoyue >= 50:
            if ctx.variables.get("panel_scroll_count") and not ctx.variables.pop("escort_scrollback_done", None):
                # Panel is scrolled: the fixed fallback row no longer points at 运镖.
                # Scroll back to the top first (keeping the scroll budget spent), then
                # take the fixed-row fallback on the next tick.
                logger.info("[daily_panel] Escort eligible but panel is scrolled; scrolling back to top first")
                if ctx.device is not None and hasattr(ctx.device, "swipe"):
                    ctx.device.swipe(735, 160, 735, 480)
                ctx.variables["escort_scrollback_done"] = True
                time.sleep(1.5)
                return
            logger.info(
                f"[daily_panel] Escort eligible (活跃度={current_huoyue}) but card not parsed; "
                f"clicking unscrolled 运镖 row fallback {ESCORT_JOIN}"
            )
            _click(ctx, *ESCORT_JOIN)
            time.sleep(2.0)
            return
        logger.warning(
            f"[daily_panel] All other dailies done but 活跃度={current_huoyue} < 50 (缺口 {50 - current_huoyue} 点); "
            "escort cannot be unlocked today, abandoning 运镖 for this run."
        )
        completed_tasks.append("运镖")

    logger.info(f"[daily_panel] All queued activities completed or ineligible! Claiming activity chests (活跃度={current_huoyue})...")
    for task_name in daily_queue:
        if task_name not in completed_tasks:
            # Honest close-out: report any task that never reached its daily counter
            # (e.g. 秘境 5/10) instead of silently claiming everything is done.
            card = cards_by_name.get(task_name)
            if card is None:
                # Unverified: leave it out of completed_tasks so the next panel visit
                # retries it instead of declaring the day finished on an OCR miss.
                logger.warning(
                    f"[daily_panel] [{task_name}] card was NEVER parsed (panel scroll/tab/OCR miss) "
                    "— leaving it unfinished for the next pass."
                )
                continue
            elif card["is_time_gated"] and not card["is_done"]:
                # Time-gated (三界奇缘 11:00开启 / 科举乡试 17:00开启): genuinely not
                # runnable now, NOT unfinished. Ineligible for today's run unless the
                # gate passes while the run is still alive; chests are unaffected.
                if task_name not in not_runnable_today:
                    logger.warning(
                        f"[daily_panel] [{task_name}] time-gated ({card['card_text'][:24]}); "
                        "not runnable now — tracked as ineligible, chests unaffected."
                    )
                    not_runnable_today.append(task_name)
                continue
            elif not card["is_done"]:
                # Read but not finished (its 参加 button is just off-screen this tick).
                # Keep it queued so the next panel visit scrolls to it and dispatches.
                logger.warning(
                    f"[daily_panel] [{task_name}] read but not finished "
                    f"(次数 {card['current_cnt']}/{card['max_cnt']}, 活跃 {card['h_current']}/{card['h_max']}) "
                    "— leaving it for the next pass."
                )
                continue
            completed_tasks.append(task_name)

    # A task left unfinished above (never parsed, or read but its 参加 is off-screen)
    # must keep the day open. Otherwise the pipeline takes daily_finish and never comes
    # back for it (live 2026-09-27: 科举乡试 never parsed and 三界奇缘 at 0/10, yet
    # all_dailies_done was set and the run exited). Time-gated tasks are excluded:
    # they cannot run now, and blocking on them cost the whole chest claim
    # (live 2026-09-29: chests never claimed because 三界奇缘 was 11:00开启).
    still_open = [t for t in daily_queue if t not in completed_tasks and t not in not_runnable_today]
    if still_open:
        logger.warning(
            f"[daily_panel] Not finished — {still_open} still queued. Closing the panel "
            "without claiming the day done so the next pass retries them."
        )
        _click(ctx, *PANEL_CLOSE)
        time.sleep(1.0)
        return

    chest_milestones = [
        (20, (457, 570)),
        (40, (609, 570)),
        (60, (760, 570)),
        (80, (911, 570)),
        (100, (1063, 570)),
    ]
    claimed_chests = ctx.variables.setdefault("claimed_chests", [])
    for threshold, (cx, cy) in chest_milestones:
        # If current_huoyue is 0 (unparsed), click all as fallback; otherwise click eligible unlocked chests
        if current_huoyue == 0 or current_huoyue >= threshold:
            if threshold not in claimed_chests:
                logger.info(f"[daily_panel] Claiming {threshold}活跃 chest at ({cx}, {cy})")
                _click(ctx, cx, cy)
                claimed_chests.append(threshold)
                time.sleep(0.5)

    ctx.variables["all_dailies_done"] = True
    _click(ctx, *PANEL_CLOSE)
    logger.info("[daily_panel] Claimed chests, closed panel, daily sequence completed!")
    time.sleep(1.0)


# --- interaction handlers ----------------------------------------------------

def click_shimen_board(ctx: PipelineContext, act: NodeAction) -> None:
    """Handle 师门 board when open: click 继续任务, 去完成, 前往."""
    items = ctx.variables.get("_last_frame_items") or []
    # Check if there are active choices: "选择", "继续任务", "去完成", "前往", "继续"
    go_btn = _find(items, lambda it: (
        any(kw in it.text for kw in ("选择", "继续任务", "去完成", "前往", "继续"))
        or (it.text.strip() == "完成")
    ) and "已完成" not in it.text and 350 < it.center[1] < 500)
    if go_btn is not None:
        gx, gy = _center(go_btn)
        logger.info(f"[shimen_board] Clicking [{go_btn.text}] at ({gx:.0f}, {gy:.0f})")
        _click(ctx, gx, gy)
        time.sleep(2.0)
        return

    # Check if all tasks on board are completed or no actionable button
    completed_btns = [it for it in items if "已完成" in it.text and 350 < it.center[1] < 500]
    has_choices = any(it.text.strip() == "选择" for it in items)
    if not has_choices and (len(completed_btns) >= 2 or any("全部完成" in it.text for it in items) or "师门任务" in ctx.variables.get("completed_tasks", [])):
        logger.info("[shimen_board] All tasks completed on shimen board, pressing back key to close board")
        ctx.device.press_key(4)
        if "师门任务" not in ctx.variables.setdefault("completed_tasks", []):
            ctx.variables["completed_tasks"].append("师门任务")
        ctx.variables["current_task_done"] = True
        time.sleep(1.5)
        return

    logger.info("[shimen_board] Fallback clicking 继续任务 at (629, 442)")
    _click(ctx, 629, 442)
    time.sleep(2.0)


def _shop_dialog_signature(items: list, buy_btn: Optional[Any]) -> str:
    """Identity of the currently open shop window.

    Combines the 购买 button position with the visible item rows so that a dialog
    which stays open across ticks keeps the same signature (and therefore the same
    purchase budget), while a genuinely different shop — new item rows — gets a new
    one. Without this, the DAG's ``shop_buy`` node re-fires every frame and bought
    the same item forever (bugfix 2026-09-29: 藏宝图 stocked until the bag was full).
    """
    rows = sorted({
        getattr(it, "text", "").strip()
        for it in items
        if 400 < it.center[0] < 1260 and 120 < it.center[1] < 660
        and len(getattr(it, "text", "").strip()) >= 2
    })
    # Round the button position to 10px buckets: OCR bounding boxes jitter by a
    # couple of pixels between frames, which must not reset the per-window budget.
    # The item-row text below is the stronger identity signal anyway.
    btn = "-" if buy_btn is None else f"{round(buy_btn.center[0] / 10) * 10:.0f},{round(buy_btn.center[1] / 10) * 10:.0f}"
    return btn + "|" + "|".join(rows)[:240]


def _exit_shop(ctx: PipelineContext, items: list) -> None:
    """Close the current shop window: prefer its corner ×, else the back key."""
    close_btn = _find(items, lambda it: it.text.strip() in ("×", "X", "x", "✕") and it.center[0] > 900 and it.center[1] < 200)
    if close_btn is not None:
        cx, cy = _center(close_btn)
        logger.info(f"[shop_buy] Closing shop window via × at ({cx:.0f}, {cy:.0f})")
        _click(ctx, cx, cy)
    elif ctx.device is not None and hasattr(ctx.device, "press_key"):
        logger.info("[shop_buy] Closing shop window via back key")
        ctx.device.press_key(4)
    time.sleep(1.2)


def click_shop_buy(ctx: PipelineContext, act: NodeAction) -> None:
    """Click 购买 in a shop dialog — bounded, and never a bulk purchase of 藏宝图.

    The daily DAG re-enters this node every frame while a 购买 button is visible, so
    an unguarded handler clicked 购买 endlessly and filled the backpack with the
    selected item (user report 2026-09-29: 藏宝图 over-purchased until the bag was
    full). Two guards now bound it:

    * each distinct shop window gets at most ``max_shop_buys_per_dialog`` purchases
      (default 1); a new window resets the budget;
    * a 藏宝图-selling window is only bought from when the dig phase explicitly asks
      for a map (``treasure_map_requested``) and the remaining budget allows it —
      otherwise the window is closed without buying.
    """
    items = ctx.variables.get("_last_frame_items") or []
    buy_btn = _find(items, lambda it: it.text == "购买" and it.center[0] > 800 and it.center[1] > 450)

    # Reset the per-window purchase budget whenever the shop window changes.
    signature = _shop_dialog_signature(items, buy_btn)
    if ctx.variables.get("shop_dialog_signature") != signature:
        ctx.variables["shop_dialog_signature"] = signature
        ctx.variables["shop_buys_this_dialog"] = 0
    buys_done = int(ctx.variables.get("shop_buys_this_dialog", 0))
    max_buys = int(ctx.variables.get("max_shop_buys_per_dialog", MAX_SHOP_BUYS_PER_DIALOG))

    # A map-selling window is the dig flow's business alone. Outside an explicit
    # dig request this must never buy — that is exactly what stocked the bag.
    sells_maps = any(
        any(kw in getattr(it, "text", "") for kw in TREASURE_MAP_KWS)
        for it in items
    )
    if sells_maps:
        budget = int(ctx.variables.get("treasure_map_buy_budget", 0))
        if not ctx.variables.get("treasure_map_requested", False) or buys_done >= budget:
            logger.info(
                f"[shop_buy] 藏宝图 window: requested={ctx.variables.get('treasure_map_requested', False)} "
                f"budget={budget} done={buys_done}; not buying, closing window"
            )
            _exit_shop(ctx, items)
            return

    if buy_btn is not None:
        if buys_done >= max_buys:
            logger.info(f"[shop_buy] 本次窗口已购买 {buys_done} 次，停止重复购买（背包保护），关闭窗口")
            _exit_shop(ctx, items)
            return
        bx, by = _center(buy_btn)
        logger.info(f"[shop_buy] Clicking 购买 at ({bx:.0f}, {by:.0f})")
        _click(ctx, bx, by)
        ctx.variables["shop_buys_this_dialog"] = buys_done + 1
        if sells_maps:
            ctx.variables["treasure_map_buys_this_dig"] = ctx.variables.get("treasure_map_buys_this_dig", 0) + 1
    else:
        # No 购买 button visible on the current frame: the shop dialog is not open
        # (or OCR missed it). Never blind-click a fixed coordinate — a stray tap in
        # the game world could buy an unintended item (review P2).
        if buys_done >= max_buys:
            logger.info("[shop_buy] 本次窗口已购买，停止重复购买（背包保护）")
            return
        logger.info("[shop_buy] 未检测到「购买」按钮，跳过本次点击（不盲点坐标）")
        return
    time.sleep(1.5)

    # Check if in player stall (摆摊): buying does not auto-close stall, so close it to resume quest
    is_stall = any("摆摊" in getattr(it, "text", "") for it in items) or any("我要购买" in getattr(it, "text", "") for it in items)
    if is_stall:
        close_btn = _find(items, lambda it: it.text in ("×", "X", "x", "✕") and it.center[0] > 900 and it.center[1] < 150)
        cx, cy = _center(close_btn) if close_btn is not None else (1111, 44)
        logger.info(f"[shop_buy] Stall window detected; closing stall at ({cx:.0f}, {cy:.0f}) to continue quest")
        _click(ctx, cx, cy)
        time.sleep(1.5)


def needs_treasure_map(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """True when the dig phase still needs a map but the bag has none.

    Maps are obtained at dig time only — this recognizer gates the buy node in the
    baotu dig loop and never fires outside it. It is also bounded by
    ``treasure_map_buy_attempts`` so the gate can never bounce forever between
    probe_map_in_bag and buy_map_to_dig with no shop window open.
    """
    if ctx.variables.get("has_treasure_map", False):
        return False
    target = int(ctx.variables.get("baotu_dig_target", 10))
    done = int(ctx.variables.get("dig_count", 0))
    if done >= target:
        return False
    if int(ctx.variables.get("treasure_map_buy_attempts", 0)) >= int(
        ctx.variables.get("max_treasure_map_buy_attempts", MAX_TREASURE_MAP_BUY_ATTEMPTS)
    ):
        return False
    return ctx.variables.get("treasure_map_buys_this_dig", 0) < ctx.variables.get("max_treasure_maps_per_dig", MAX_TREASURE_MAPS_PER_DIG)


def buy_treasure_map(ctx: PipelineContext, act: NodeAction) -> None:
    """Buy exactly one 藏宝图 at the moment of digging — never a bulk stock.

    Only acts when an actual 购买 button is visible in the current frame; a
    dig-loop frame with no shop window open must not produce a stray tap. Each
    no-shop visit increments ``treasure_map_buy_attempts`` so the dig gate stops
    routing here and the loop times out honestly instead of spinning.
    """
    buys = int(ctx.variables.get("treasure_map_buys_this_dig", 0))
    limit = int(ctx.variables.get("max_treasure_maps_per_dig", MAX_TREASURE_MAPS_PER_DIG))
    remaining = max(0, int(ctx.variables.get("baotu_dig_target", 10)) - int(ctx.variables.get("dig_count", 0)))
    if buys >= limit or remaining <= 0:
        logger.info(f"[baotu] 挖宝购图已达上限（本轮 {buys}/{limit}, 剩余挖掘 {remaining}），不再购买")
        return

    # The dig-time purchase must act on the *current* screen, not on the shared
    # _last_frame_items cache: in a chained routine (shimen -> baotu) that cache
    # still holds the previous pipeline's classify_screen output, and a 购买 button
    # found there would be a stale click on the wrong screen (review P1). Always
    # live-OCR the fresh frame; the injected cache is only a stand-in for devices
    # that cannot produce a frame at all (unit-test DummyDevice returns b'').
    items = []
    fresh_frame = False
    if ctx.device is not None and hasattr(ctx.device, "screencap"):
        try:
            raw = ctx.device.screencap()
            if raw:
                import cv2
                import numpy as np
                frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    fresh_frame = True
                    items = _ocr_items(frame)
        except Exception as exc:
            logger.warning(f"[baotu] 购图前实机取帧失败：{exc}")
    if not fresh_frame:
        # Test/virtual devices produce no readable frame; serve the injected cache.
        items = ctx.variables.get("_last_frame_items") or []

    buy_btn = _find(items, lambda it: it.text == "购买" and it.center[0] > 800 and it.center[1] > 450)
    if buy_btn is None:
        # No shop window with a 购买 button is open in this frame. Do not guess a
        # coordinate: a stray tap in the game world is worse than a no-op here.
        attempts = int(ctx.variables.get("treasure_map_buy_attempts", 0)) + 1
        ctx.variables["treasure_map_buy_attempts"] = attempts
        logger.info(
            f"[baotu] 未检测到商铺「购买」按钮，跳过本次购图（不盲点坐标）"
            f"[尝试 {attempts}/{ctx.variables.get('max_treasure_map_buy_attempts', MAX_TREASURE_MAP_BUY_ATTEMPTS)}]"
        )
        return
    bx, by = _center(buy_btn)
    logger.info(f"[baotu] 挖宝时按需购买 1 张藏宝图 at ({bx:.0f}, {by:.0f}) [{buys + 1}/{limit}]")
    _click(ctx, bx, by)
    ctx.variables["treasure_map_buys_this_dig"] = buys + 1
    ctx.variables["treasure_map_buy_attempts"] = 0  # the bag now has a map
    ctx.variables["has_treasure_map"] = True
    time.sleep(1.5)


def click_turnin(ctx: PipelineContext, act: NodeAction) -> None:
    """Click 上交 or 给予 when handing in items or completing quest turn-in."""
    items = ctx.variables.get("_last_frame_items") or []
    turnin_btn = _find(items, lambda it: any(kw in it.text for kw in ("上交", "给予", "上交任务")) and it.center[0] > 600 and it.center[1] > 350)
    if turnin_btn is not None:
        tx, ty = _center(turnin_btn)
        logger.info(f"[turnin] Clicking [{turnin_btn.text}] at ({tx:.0f}, {ty:.0f})")
        _click(ctx, tx, ty)
    else:
        logger.info("[turnin] Fallback clicking turn-in at (880, 520)")
        _click(ctx, 880, 520)
    time.sleep(1.5)


def click_use_item(ctx: PipelineContext, act: NodeAction) -> None:
    """Click 使用 on item popup (e.g. 藏宝图, quest scroll)."""
    items = ctx.variables.get("_last_frame_items") or []
    use_btn = _find(items, lambda it: it.text == "使用" and 500 < it.center[0] < 1250 and 380 < it.center[1] < 650)
    if use_btn is not None:
        ux, uy = _center(use_btn)
        logger.info(f"[use_item] Clicking 使用 at ({ux:.0f}, {uy:.0f})")
        _click(ctx, ux, uy)
    else:
        logger.info("[use_item] Fallback clicking 使用 at (1094, 578)")
        _click(ctx, 1094, 578)
    time.sleep(2.0)


def click_dialog_choice(ctx: PipelineContext, act: NodeAction) -> None:
    """Click NPC dialogue options:
    - Prefer choice matching current task keywords (e.g. 师门, 宝图, 押送普通镖银).
    - Or right-hand dialogue choice list (x > 900, 350 < y < 650).
    - Or 跳过 / 继续.
    """
    items = ctx.variables.get("_last_frame_items") or []
    curr_task = ctx.variables.get("current_task_name", "")

    # A roaming world boss (二十八星宿) opens its own dialog with a lone 进入战斗
    # while a daily is in progress. Taking it abandons the daily mid-step (live
    # 2026-09-26, 师门 8/10 blocked by 角木蛟之影). Close it and resume the tracker.
    # Note: Require a battle keyword or dialog prompt on the dialog to avoid false positives
    # from standing near an NPC named 星宿 on the world map.
    has_xingxiu = bool(_find(items, lambda it: "星宿" in it.text and it.center[1] < 500))
    has_battle_opt = bool(_find(items, lambda it: any(kw in it.text for kw in ("进入战斗", "开始战斗", "切入战斗")) and it.center[0] > 700))
    if curr_task and has_xingxiu and has_battle_opt:
        logger.info(f"[dialog] Roaming 星宿 dialog while doing {curr_task}; closing it")
        if ctx.device is not None and hasattr(ctx.device, "press_key"):
            ctx.device.press_key(4)
        time.sleep(1.2)
        return

    # 0. Direct battle entry in NPC dialogue takes highest priority
    battle_kws = ("进入战斗", "开始战斗", "切入战斗")
    choice_y_min, choice_y_max = 340, 680
    if curr_task == "秘境降妖":
        battle_kws = ("进入战斗", "开始战斗", "切入战斗", "进入挑战", "开始挑战", "挑战", "秘境降妖")
        # The 云乐游 NPC (东海湾) dialog rows sit higher on screen (秘境降妖 option ~y264);
        # the default 340.. band would miss it and fall through to 规则说明.
        choice_y_min = 200
    elif curr_task == "师门任务":
        # 门派师父 dialog lists 师门任务 above the default band (live 2026-09-26, 月宫:
        # 师门任务 at y≈265); missing it falls through to 门派关系/查看竞选名单.
        choice_y_min = 200
    elif curr_task == "宝图任务":
        # 店小二 lists 打听藏宝图 above the default band; missing it falls through to
        # 浏览三界论坛 / 招募大厅 (live 2026-09-26, both opened and abandoned the quest).
        choice_y_min = 200
    # The quest tracker label (e.g. "秘境降妖" at y≈244) sits above the real dialog
    # choice ("进入战斗" at y≈400) and matches the same keywords. Pick the LOWEST
    # match so the dialog choice wins over the tracker (live 2026-09-27, 秘境 looped
    # on the tracker and never entered the fight).
    battle_matches = [it for it in items if any(kw in it.text for kw in battle_kws) and it.center[0] > 700 and choice_y_min < it.center[1] < choice_y_max]
    battle_opt = max(battle_matches, key=lambda it: it.center[1]) if battle_matches else None
    if battle_opt is not None:
        bx, by = _center(battle_opt)
        logger.info(f"[dialog] Clicking battle entry [{battle_opt.text}] at ({bx:.0f}, {by:.0f})")
        ctx.variables["dialog_fallback_count"] = 0
        _click(ctx, bx, by)
        time.sleep(2.0)
        return

    skip = _find(items, lambda it: any(kw in it.text for kw in ("跳过", "点击继续", "继续")) and it.center[1] > 400)
    if skip is not None:
        sx, sy = _center(skip)
        logger.info(f"[dialog] Clicking [{skip.text}] at ({sx:.0f}, {sy:.0f})")
        ctx.variables["dialog_fallback_count"] = 0
        _click(ctx, sx, sy)
        time.sleep(1.2)
        return
        
    # NOTE: "前往" is deliberately NOT a keyword — it is a greedy CTA (前往提升/前往查看)
    # that jumps to unrelated pages when an unknown reward dialog pops up. Task routing
    # goes through the quest tracker instead.
    keywords = ["进入战斗", "押送普通镖银", "普通镖银", "听听无妨", "打听强盗", "打听藏宝图", "我想打听", "师门", "打听", "藏宝图", "宝图", "请安", "领取", "挑战", "进入挑战", "进入秘境"]
    if curr_task:
        if curr_task == "运镖":
            keywords = ["押送普通镖银", "普通镖银", "押送", "押镖", "运镖"] + keywords
        elif curr_task == "师门任务":
            keywords = ["师门"] + keywords
        elif curr_task == "宝图任务":
            keywords = ["打听强盗", "打听藏宝图", "宝图", "强盗"] + keywords
        elif curr_task == "秘境降妖":
            keywords = ["进入战斗", "开始战斗", "进入挑战", "开始挑战", "挑战", "下一层", "进入下一层", "传送", "进入秘境", "进入", "秘境降妖", "日月之井", "海底秘境"] + keywords
        else:
            keywords = [curr_task] + keywords
        
    for kw in keywords:
        # Avoid long narration lines like "最近好多镖车要押送..." by requiring choice length <= 16 and center[0] > 900 for choices.
        # Also exclude quest tracker items (which contain progress counters like "（4/10）" or "(4/10)"),
        # and pick the lowest matching option in the choice column so real dialogue options (y >= 260)
        # always win over top-right HUD tracker text (y ~ 196).
        # "首席" options (挑战首席弟子) are the guild chief-duel weekly, never a daily
        # step: the base keyword 挑战 matched it in the mentor dialog while a 师门
        # errand was mid-progress, and each duel is a ~15-min unwinnable stalemate
        # (帮众 adds respawn, auto-flee, no 师门 progress) — 59 clicks, 师门 stuck at
        # 2/10 for the whole run (live 2026-09-29).
        matches = [
            it for it in items
            if kw in it.text
            and "首席" not in it.text
            and "（" not in it.text and "(" not in it.text and "/" not in it.text
            and 1000 < it.center[0] < 1250
            and len(it.text.strip()) <= 16
            # Live 2026-09-29 (in-progress errand 三界安宁 2/10): the mentor dialog
            # lists 师门任务 as the FIRST option at frame y≈130 — above the old 170
            # floor, so the keyword loop never matched it and the generic fallback
            # clicked 门派关系 (opening the 门派目标 window) instead of resuming.
            and (120 if curr_task == "师门任务" else choice_y_min) < it.center[1] < choice_y_max
        ]
        matched = max(matches, key=lambda it: it.center[1]) if matches else None
        if matched is not None:
            mx, my = _center(matched)
            # A generic 领取 CTA (reward-claim button on ad pages, promo carousels,
            # event popups — NOT a task-specific dialogue option) can match the base
            # keyword list forever when the page it sits on never changes or has no
            # real exit: live 2026-09-30 the cross-game promo carousel's 领取 at
            # (1184,497) was clicked 28 consecutive times with zero progress. A real
            # claim changes the dialog and the streak never builds; cap 3 consecutive
            # 领取-only matches at BACK + wait (a single BACK on a dialog is safe — it
            # only closes the dialog; the quit-game confirm safety lives in
            # dismiss_popups and is never confirmed).
            if "领取" in matched.text:
                claim_streak = int(ctx.variables.get("dialog_claim_streak", 0)) + 1
                ctx.variables["dialog_claim_streak"] = claim_streak
                if claim_streak >= 3:
                    ctx.variables["dialog_claim_streak"] = 0
                    logger.warning(
                        f"[dialog] 领取-type option [{matched.text}] matched {claim_streak}x with no "
                        f"progress at ({mx:.0f}, {my:.0f}) — pressing BACK instead of clicking it again"
                    )
                    if ctx.device is not None and hasattr(ctx.device, "press_key"):
                        ctx.device.press_key(4)
                    time.sleep(1.5)
                    return
            else:
                ctx.variables["dialog_claim_streak"] = 0
            logger.info(f"[dialog] Clicking task-specific option [{matched.text}] at ({mx:.0f}, {my:.0f})")
            ctx.variables["dialog_fallback_count"] = 0
            _click(ctx, mx, my)
            time.sleep(1.5)
            return

    def is_valid_choice(it):
        # Dialog choices live in the right column (~x1085, y>=340). The quest tracker
        # overlaps that column higher up ("出发闯荡前看看首席有" at y229, "什么交代的"
        # at y249) and world NPC name tags sit left of it ("月灵" at x967) — neither is
        # a choice (live 2026-09-26).
        if not (1000 < it.center[0] < 1200) or not (340 < it.center[1] < 650) or len(it.text) < 2:
            return False
        text = it.text.strip()
        if "（" in text or "(" in text:
            return False
        if text.endswith("：") or text.endswith(":"):
            return False
        if any(p in text for p in ("请选择", "要做的事", "交谈", "任务", "队伍", "主线")):
            return False
        # 首席弟子竞选 is a weekly vote event, not a daily: "查看竞选名单" reopens the
        # vote popup and loops (live 2026-09-26, 月宫 师门 dialog).
        # 挑战首席弟子 is the guild chief-duel weekly: an unwinnable ~15-min solo
        # stalemate that abandons the daily (live 2026-09-29).
        if "竞选" in text or "首席" in text:
            return False
        # "浏览三界论坛" opens the in-game forum web page and abandons the quest
        # (live 2026-09-26, 宝图 NPC dialog).
        # "打工赚钱" is an irrelevant life-skill sub-action on 颜如羽 that loops endlessly.
        if any(p in text for p in ("论坛", "浏览", "招募", "打工")):
            return False
        # Gacha/spend CTAs spend 仙玉 (live 2026-09-27, 百宠仙池 opened mid-秘境).
        if any(p in text for p in ("祈愿", "百宠", "召唤灵", "充值", "仙玉")):
            return False
        return True

    generic_choice = _find(items, is_valid_choice)
    if generic_choice is not None:
        gx, gy = _center(generic_choice)
        logger.info(f"[dialog] Clicking dialogue choice [{generic_choice.text}] at ({gx:.0f}, {gy:.0f})")
        ctx.variables["dialog_fallback_count"] = 0
        _click(ctx, gx, gy)
        time.sleep(1.5)
        return
        
    # Blind-clicking the default choice slot is dangerous when the only options left
    # are the guild chief-duel weekly (挑战首席弟子/查看竞选名单): (1086,468) sits close
    # enough to start the ~15-min unwinnable duel (live 2026-09-29). Close instead.
    if any("首席" in getattr(it, "text", "") or "竞选" in getattr(it, "text", "")
           for it in items if 1000 < it.center[0] < 1250 and 250 < it.center[1] < 680):
        logger.info("[dialog] Only guild chief-duel options visible; closing dialog instead of blind click")
        if ctx.device is not None and hasattr(ctx.device, "press_key"):
            ctx.device.press_key(4)
        time.sleep(1.2)
        return

    # Degradation: the default-slot click is a guess made at the moment OCR failed —
    # the least trustworthy moment. It is a blind click by design (and the safety
    # redline says none), so cap it: after 3 consecutive fallbacks with no matched
    # choice in between, the safer move is BACK + wait, letting the tracker re-derive
    # or the popup dismisser take over (live 2026-09-30 review).
    fb = int(ctx.variables.get("dialog_fallback_count", 0))
    if fb >= 3:
        logger.warning(
            f"[dialog] Default-slot fallback already tried {fb}x with no matched choice — "
            f"pressing BACK instead of blind-clicking (1086, 468) again"
        )
        # Reset (not ++): the counter must not latch at >=3 forever — the BACK likely
        # closes this dialog, and the NEXT dialog (a different one) deserves a fresh
        # 3-try cycle, not an immediate cancel. Latching made every later OCR-miss
        # dialog a reflex BACK that cancels it (2026-09-30 re-review).
        ctx.variables["dialog_fallback_count"] = 0
        if ctx.device is not None and hasattr(ctx.device, "press_key"):
            ctx.device.press_key(4)
        time.sleep(1.2)
        return

    logger.info("[dialog] Fallback clicking default dialogue choice at (1086, 468)")
    ctx.variables["dialog_fallback_count"] = fb + 1
    _click(ctx, 1086, 468)
    time.sleep(1.5)


def click_task_tracker(ctx: PipelineContext, act: NodeAction) -> None:
    """Click top-right quest tracker (x: 1050..1280, y: 150..320) to resume navigation / subtask."""
    items = ctx.variables.get("_last_frame_items") or []
    curr_task = ctx.variables.get("current_task_name", "")

    task_kws = {
        "师门任务": ["师门"],
        "宝图任务": ["宝图", "贼王", "强盗"],
        "运镖": ["运镖", "押镖"],
        # Bare 关/挑战 also match unrelated HUD text (通关第6关解锁), which then gets
        # clicked as the quest tracker (live 2026-09-27). Require the 第N关 progress
        # form instead, matched as a pair below.
        "秘境降妖": ["秘境", "降妖"],
    }
    
    def _is_mijing_progress(text: str) -> bool:
        # 第N关 progress line, but not the 通关第N关解锁 teaser (which has 解锁).
        return "第" in text and "关" in text and "解锁" not in text

    tracker_item = None
    if curr_task and curr_task in task_kws:
        tracker_item = _find(items, lambda it: (any(kw in it.text for kw in task_kws[curr_task]) or (curr_task == "秘境降妖" and _is_mijing_progress(it.text))) and 1000 < it.center[0] < 1280 and 140 < it.center[1] < 340)

    if tracker_item is None:
        tracker_item = _find(items, lambda it: (any(kw in it.text for kw in ("师门", "宝图", "贼王", "强盗", "运镖", "押镖", "秘境", "降妖")) or _is_mijing_progress(it.text)) and 1000 < it.center[0] < 1280 and 140 < it.center[1] < 340)

    if tracker_item is not None:
        tx, ty = _center(tracker_item)
        logger.info(f"[tracker] Clicking quest tracker [{tracker_item.text}] at ({tx:.0f}, {ty:.0f})")
        _click(ctx, tx, ty)
    else:
        logger.info("[tracker] Fallback clicking top tracker slot at (1145, 210)")
        _click(ctx, 1145, 210)
    time.sleep(2.5)


def wait_walking(ctx: PipelineContext, act: NodeAction = None) -> None:
    """Wait while character is pathfinding (自动寻路中)."""
    # Exempt the next tick from the DAG stall watchdog: pathfinding/escort screens are
    # legitimately near-static for minutes (world map + countdown) — a static frame
    # here is not a stuck loop (scheduler/dag.py).
    ctx.variables["wait_expected"] = True
    logger.info("[walking] Character is auto-pathfinding, waiting 2.5s...")
    time.sleep(2.5)


def find_activity_entry(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """活动 panel open and the 运镖 row visible (i.e. escort quota remains)."""
    items = _ocr_items(frame)
    ctx.variables["_last_frame_items"] = items
    yb = _find(items, lambda it: "运镖" in it.text and abs(it.center[1] - 122) < 14 and it.center[0] > 700)
    return yb is not None


def open_activity_panel(ctx: PipelineContext, act: NodeAction) -> None:
    """Open the panel via the top-bar 活动 button; close stray/event popups first."""
    items = ctx.variables.get("_last_frame_items") or []
    xbtn = _find(items, lambda it: it.text in ("×", "X", "x", "✕") and it.center[0] > 1050 and it.center[1] < 120)
    if xbtn:
        x, y = _center(xbtn)
        _click(ctx, x, y)
        logger.info(f"daily: closed popup × at ({x:.0f}, {y:.0f})")
        time.sleep(1.0)

    # The top-bar 活动 button sits around y 63. A loose y<120 band also matches
    # the 排行榜 sidebar ("帮派榜" read as "…活动", live 2026-09-26), which then gets
    # tapped and reopens the ranking page instead of the activity panel.
    act_btn = _find(items, lambda it: "活动" in it.text and 40 < it.center[1] < 95 and 250 < it.center[0] < 560)
    # The top bar buttons OCR either as separate items (指引/活动/排行/挂机) or as one
    # merged blob. "Blob left end + 30px" only lands on 活动 when the blob STARTS at
    # 活动 ("活动排行挂机"). A blob prefixed by 指引 ("指引活动排行挂机", live 2026-09-29)
    # has its left end on 指引 — tapping left+30px opens the guide window instead of
    # the panel, which is exactly what kept re-triggering the 门派目标/星宿之影 windows.
    # So: prefer a clean standalone 活动 item; for a 指引-prefixed blob fall back to the
    # HUD-fixed position (the top bar layout is identical on every map) instead of
    # unreliable blob geometry.
    standalone = _find(items, lambda it: it.text.strip() == "活动" and 40 < it.center[1] < 95 and 250 < it.center[0] < 560)
    if standalone is not None:
        ax, ay = _center(standalone)
        src = "standalone item"
    elif act_btn is not None and not act_btn.text.strip().startswith("指引"):
        bx, by, bw, bh = act_btn.bbox
        # 活动 is the leftmost button of the blob, so aim at its left end, not its center.
        ax = bx + min(30, bw / 2)
        ay = by + bh / 2
        src = f"blob '{act_btn.text.strip()[:10]}' left end"
    else:
        # Fallback to the HUD-fixed coordinate when OCR failed to find any 活动 text —
        # this usually means an overlay is covering the top bar (live 2026-09-30:
        # a promo carousel hid the HUD, OCR saw nothing, and the stale 1280x720
        # constant (353,64) landed on 基础设置 at 1600x900). Two fixes:
        # 1) scale the 1280x720-baseline constant by the real frame size so it lands
        #    on the right button on any resolution;
        # 2) if even the scaled fallback keeps failing (panel still not open), stop
        #    blind-clicking and press BACK to clear the blocking overlay instead.
        fb_count = int(ctx.variables.get("panel_fallback_count", 0))
        if fb_count >= 3:
            logger.warning(
                f"[open_panel] 活动 fallback missed {fb_count}x in a row — overlay likely "
                f"blocking OCR; pressing BACK instead of clicking again"
            )
            # Reset (not ++): the BACK should clear the blocking overlay, and the next
            # attempt must retry the (now-unobstructed) scaled tap — a latched >=3
            # counter kept pressing BACK forever even after the overlay was gone and
            # 活动 became tappable again (2026-09-30 re-review). classify_screen resets
            # this counter too whenever the panel is actually open.
            ctx.variables["panel_fallback_count"] = 0
            if ctx.device is not None and hasattr(ctx.device, "press_key"):
                ctx.device.press_key(4)
            time.sleep(1.2)
            return
        sx, sy = _frame_scale(ctx)
        ax, ay = (TOPBAR_ACTIVITY[0] * sx, TOPBAR_ACTIVITY[1] * sy)
        ctx.variables["panel_fallback_count"] = fb_count + 1
        src = "HUD-fixed" if act_btn is not None else "fallback-scaled"
    _click(ctx, ax, ay)
    logger.info(f"daily: tap top-bar 活动 button at ({ax:.0f}, {ay:.0f}) [{src}]")
    time.sleep(2.5)


def escort_join_available(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """运镖 row visible AND counter shows remaining trips (次数n/3, n<3)."""
    items = _ocr_items(frame)
    ctx.variables["_last_frame_items"] = items
    yb = _find(items, lambda it: "运镖" in it.text and abs(it.center[1] - 122) < 14 and it.center[0] > 700)
    if yb is None:
        return False
    cnt = _find(items, lambda it: it.text.startswith("次数") and abs(it.center[1] - 178) < 10 and it.center[0] > 800)
    if cnt and ("/3" in cnt.text):
        try:
            done = int(cnt.text.replace("次数", "").split("/")[0])
        except ValueError:
            done = 0
        ctx.variables["escort_done"] = done
        return done < MAX_ESCORTS
    return True


def click_escort_join(ctx: PipelineContext, act: NodeAction) -> None:
    _click(ctx, *ESCORT_JOIN)
    logger.info("escort: tap 参加")


def find_escort_dialog(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    items = _ocr_items(frame)
    ctx.variables["_last_frame_items"] = items
    dlg = _find(items, lambda it: "押送普通镖银" in it.text and it.confidence > 0.4)
    if dlg:
        return True
    gate = _find(items, lambda it: "活跃度" in it.text and "50" in it.text and it.confidence > 0.5)
    if gate:
        ctx.variables["escort_gate"] = True
        logger.warning("escort: 50-activity gate hit")
    return False


def click_escort_choice(ctx: PipelineContext, act: NodeAction) -> None:
    _click(ctx, *ESCORT_CHOICE)
    logger.info("escort: tap 押送普通镖银")


def find_deposit_confirm(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    items = _ocr_items(frame)
    ctx.variables["_last_frame_items"] = items
    ok = _find(items, lambda it: it.text in ("确定", "确认") and 340 < it.center[1] < 500 and 600 < it.center[0] < 900 and it.confidence > 0.4)
    return ok is not None


def click_deposit_confirm(ctx: PipelineContext, act: NodeAction) -> None:
    items = ctx.variables.get("_last_frame_items") or []
    btn = _find(items, lambda it: it.text in ("确定", "确认") and 340 < it.center[1] < 500 and 600 < it.center[0] < 900)
    if btn is not None:
        bx, by = _center(btn)
        logger.info(f"[deposit_confirm] Clicking [{btn.text}] at ({bx:.0f}, {by:.0f})")
        _click(ctx, bx, by)
    else:
        logger.info(f"[deposit_confirm] Fallback clicking deposit confirm at {DEPOSIT_CONFIRM_Y}")
        _click(ctx, *DEPOSIT_CONFIRM_Y)
    time.sleep(1.5)


def escort_in_progress(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """Escort accepted: tracker line visible in upper middle OR a battle on."""
    items = _ocr_items(frame)
    ctx.variables["_last_frame_items"] = items
    if _find(items, lambda it: it.text in ("攻击", "取消", "自动", "法术") and it.center[0] > 800 and it.center[1] > 380):
        return True
    tr = _find(items, lambda it: "运镖" in it.text and it.confidence > 0.4 and 450 < it.center[0] < 900 and it.center[1] < 400)
    return tr is not None


def escort_finished(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """Tracker gone and no battle — trip done (or deposit dialog never opened)."""
    return not escort_in_progress(ctx, frame, rec)


def close_panel_and_finish(ctx: PipelineContext, act: NodeAction) -> None:
    items = ctx.variables.get("_last_frame_items") or []
    close_text = _find(items, lambda it: any(kw in it.text for kw in (
        "确认关闭", "点击空白处关闭界面", "点击空白处返回主界面", "点击空白处",
        "点击屏幕", "轻触屏幕", "我知道了"
    )))
    if close_text:
        x, y = _center(close_text)
        _click(ctx, x, y)
        time.sleep(0.5)
    _click(ctx, *PANEL_CLOSE)
    logger.info("[daily_finish] Daily routine completely finished. Activity panel closed.")


def dismiss_popups(ctx: PipelineContext, act: NodeAction) -> None:
    """Close reward popups, promo banners, or cancel the chat composer if it opened."""
    items = ctx.variables.get("_last_frame_items") or []

    # Safety first: the double-back quit-game confirm must NEVER be confirmed —
    # its 确定 quits the whole game client. Always take 取消 (OCR may render it
    # spaced as "取 消", so normalize).
    if any("离开游戏" in getattr(it, "text", "") for it in items):
        cancel = _find(items, lambda it: it.text.replace(" ", "") == "取消")
        if cancel is not None:
            x, y = _center(cancel)
            logger.warning(f"[dismiss_popups] Quit-game confirm detected; clicking 取消 at ({x:.0f}, {y:.0f}) — NEVER 确定")
            _click(ctx, x, y)
        else:
            logger.warning("[dismiss_popups] Quit-game confirm detected; no 取消 parsed, pressing back instead of confirming")
            if ctx.device is not None and hasattr(ctx.device, "press_key"):
                ctx.device.press_key(4)
        time.sleep(1.5)
        return

    # Chat composer focused (world chat input): occludes the whole HUD and its 确定
    # would SEND a chat message — close via the system 取消 (top-right; at 1600x900
    # it sits at x≈1479, so the legacy x<1210 baseline bound must not apply here),
    # never 确定/发送. Fallback: one BACK drops the IME.
    if ctx.variables.get("chat_input_open") or any("点击这里输入" in getattr(it, "text", "") for it in items):
        cancel = _find(items, lambda it: it.text.replace(" ", "") == "取消" and it.center[1] < 80)
        if cancel is not None:
            x, y = _center(cancel)
            logger.warning(f"[dismiss_popups] Chat composer open; clicking 取消 at ({x:.0f}, {y:.0f}) — NEVER 确定/发送")
            _click(ctx, x, y)
        elif ctx.device is not None and hasattr(ctx.device, "press_key"):
            logger.warning("[dismiss_popups] Chat composer open; 取消 not parsed — pressing BACK to drop the IME")
            ctx.device.press_key(4)
        time.sleep(1.2)
        return

    # Safety second: a dialog offering to spend 仙玉 (秘境 death revive / continue) must
    # NEVER be confirmed. Take the safe exit (取消/离开/...) and block further 秘境 dispatch.
    if any("仙玉" in getattr(it, "text", "") for it in items):
        safe = _find(items, lambda it: it.text.replace(" ", "") in ("取消", "离开", "退出", "放弃", "关闭", "暂不"))
        if safe is not None:
            x, y = _center(safe)
            logger.warning(f"[dismiss_popups] 仙玉 cost dialog detected; safe-exit via [{safe.text}] at ({x:.0f}, {y:.0f}) — NOT confirming")
            _click(ctx, x, y)
        else:
            logger.warning("[dismiss_popups] 仙玉 cost dialog detected; no safe button parsed, clicking panel close")
            _click(ctx, *PANEL_CLOSE)
        ctx.variables["mijing_blocked"] = True
        time.sleep(1.5)
        return

    close_text = _find(items, lambda it: any(kw in it.text for kw in (
        "确认关闭", "点击空白处关闭界面", "点击空白处返回主界面", "点击空白处",
        "点击屏幕", "轻触屏幕", "满月如璧", "我知道了"
    )))
    if close_text:
        x, y = _center(close_text)
        _click(ctx, x, y)
        logger.info(f"daily: dismiss popup via [{close_text.text}] at ({x:.0f}, {y:.0f})")
        time.sleep(1.2)
        return

    # Cross-game promo carousel ("每日新发现"): no ×, no 关闭, no 确认关闭 — the only
    # exits are its 领取 button (opens ANOTHER game's ad/download flow) and the back
    # key. Never click 领取; a single BACK closes it. The next tick's quit-game safety
    # above handles the (never-confirmed) case where BACK instead raises the confirm.
    # Guard: a task-completion reward page (任务完成 + 确定 collect) is NOT this — it
    # must be collected, never backed out of, so let the reward_summary branch below
    # win if its marker is present (2026-09-30 review).
    if not any("任务完成" in getattr(it, "text", "") for it in items) and any(kw in getattr(it, "text", "") for it in items for kw in (
        "每日新发现", "上线领全武将", "首发，可以逛", "可以逛的武侠",
        "邀你战三界", "共渡灵妖劫", "共遮灵妖劫",
    )):
        promo_back_streak = int(ctx.variables.get("promo_back_streak", 0)) + 1
        ctx.variables["promo_back_streak"] = promo_back_streak
        if promo_back_streak > PROMO_BLOCK_STREAK:
            # An animated promo that ignores BACK spins here with no clicks, so
            # neither watchdog can fire and the run would idle to ticks-exhausted
            # and exit 0 (false success). Latch the block so the Summary and the
            # runner report it as a blocked run instead.
            ctx.variables["promo_block_latch"] = True
            logger.error(
                f"[dismiss_popups] Promo BACK streak {promo_back_streak} exceeds "
                f"{PROMO_BLOCK_STREAK} — latching promo_block_latch; the run cannot "
                f"progress past this promo and must not report success"
            )
            time.sleep(2.0)
            return
        if promo_back_streak > 8:
            # Live 2026-10-02: 30 consecutive promo BACKs walked the client all the
            # way to the launcher. Beyond a bounded burst, stop pressing and wait —
            # a promo that truly ignores BACK must stall visibly instead of risking
            # further navigation; the runner's foreground guard re-launches the
            # client if a BACK already left the game.
            logger.warning(
                f"[dismiss_popups] Promo BACK streak {promo_back_streak} — suspending BACK "
                f"to avoid walking out of the client; waiting"
            )
            time.sleep(2.0)
            return
        logger.info("[dismiss_popups] Cross-game promo carousel detected; closing via single back key (never clicking 领取)")
        if ctx.device is not None and hasattr(ctx.device, "press_key"):
            ctx.device.press_key(4)
        else:
            logger.warning("[dismiss_popups] No device press_key; skipping promo carousel dismiss")
        time.sleep(1.5)
        return

    # Reward summary (师门任务完成): its 确定 collects the reward and closes the page.
    # Must run before the generic back-key exits — back here raises the quit-game
    # confirm instead of closing (live 2026-09-26).
    reward_summary = _find(items, lambda it: "任务完成" in it.text)
    if reward_summary is not None:
        confirm = _find(items, lambda it: it.text == "确定" and 400 < it.center[1] < 680)
        if confirm is not None:
            x, y = _center(confirm)
            logger.info(f"[dismiss_popups] Reward summary [{reward_summary.text}]; confirming at ({x:.0f}, {y:.0f})")
            _click(ctx, x, y)
            time.sleep(1.5)
            return

    # 剑会群雄报名弹窗: 关闭点在 (1100, 60)
    if any("剑会群雄" in getattr(it, "text", "") for it in items) and any("报名" in getattr(it, "text", "") for it in items):
        logger.info("[dismiss_popups] 剑会群雄 popup detected; closing at (1100, 60)")
        _click(ctx, 1100, 60)
        time.sleep(1.2)
        return

    # 时装外观展厅: its gear-slot tabs masquerade as quiz options and the quiz answerer
    # blind-clicks the window forever (live 2026-09-29, 150+ clicks). The back key does
    # not close it (it raises the quit-game confirm); the corner × at (1143, 35) does.
    if sum(
        1 for kw in ("头饰", "坐骑", "称谓特效", "名片背景", "入场特效", "武器幻彩", "试穿", "保存穿搭")
        if any(kw in getattr(it, "text", "") for it in items)
    ) >= 2:
        xbtn = _find(items, lambda it: it.text.strip() in ("×", "X", "x", "✕") and it.center[0] > 1000 and it.center[1] < 120)
        x, y = _center(xbtn) if xbtn is not None else (1143.0, 35.0)
        logger.info(f"[dismiss_popups] Fashion showroom detected; closing via X at ({x:.0f}, {y:.0f})")
        _click(ctx, x, y)
        time.sleep(1.2)
        return

    # 门派目标 sub-window ("本周门派目标×示威亲善"): same quiz-misfire class as the
    # fashion showroom — its merged title lands in the question ROI and tabs in the
    # option ROI (live 2026-09-29, recurring during 师门 resume). Back does not close it;
    # its corner × (~1131, 80) does. The X is small so OCR may miss it; fall back fixed.
    if any(kw in getattr(it, "text", "") for it in items for kw in ("本周门派目标", "示威亲善")):
        xbtn = _find(items, lambda it: it.text.strip() in ("×", "X", "x", "✕") and it.center[0] > 1000 and it.center[1] < 140)
        x, y = _center(xbtn) if xbtn is not None else (1131.0, 80.0)
        logger.info(f"[dismiss_popups] Sect-goal window detected; closing via X at ({x:.0f}, {y:.0f})")
        _click(ctx, x, y)
        time.sleep(1.2)
        return

    # Cash-shop pages (月卡/首充/累充/星途祈愿): the back key does NOT close them, but
    # they have a corner X (OCR reads it as X/× near the top-right). Tap that, and
    # never the 购买 buttons (live 2026-09-27: back left the 星途祈愿 page open; the X
    # at (1129, 37) closed it).
    if any(kw in getattr(it, "text", "") for it in items for kw in ("月卡", "首充好礼", "累充奖励", "元购买", "星途祈愿", "折扣礼包")):
        xbtn = _find(items, lambda it: it.text.strip() in ("×", "X", "x", "✕") and it.center[0] > 1000 and it.center[1] < 120)
        if xbtn is not None:
            x, y = _center(xbtn)
            logger.info(f"[dismiss_popups] Cash-shop page; closing via X at ({x:.0f}, {y:.0f}) (never buying)")
            _click(ctx, x, y)
        else:
            logger.info("[dismiss_popups] Cash-shop page; no X parsed, pressing back")
            if ctx.device is not None and hasattr(ctx.device, "press_key"):
                ctx.device.press_key(4)
        time.sleep(1.2)
        return

    # Cash-shop pages whose back key does nothing (星途祈愿/新服战令/折扣礼包, live
    # 2026-09-27: five back presses stayed put). Their corner × does close them.
    if any(kw in getattr(it, "text", "") for it in items for kw in ("星途祈愿", "新服战令", "折扣礼包", "新服特惠")):
        # The corner X sits at a fixed spot but OCR reads it intermittently, and the
        # back key does not close these pages — two presses raise the quit-game confirm
        # (live 2026-09-27). Tap the fixed corner directly; prefer a parsed X if seen.
        xbtn = _find(items, lambda it: it.text in ("×", "X", "x", "✕") and it.center[0] > 1000 and it.center[1] < 150)
        x, y = _center(xbtn) if xbtn is not None else (1129.0, 37.0)
        logger.info(f"[dismiss_popups] Cash-shop page; closing via corner X at ({x:.0f}, {y:.0f}) (never buying)")
        _click(ctx, x, y)
        time.sleep(1.2)
        return

    # Full-screen event pages without a working × (九转天阶赛季开启): back key closes them.
    if any(kw in getattr(it, "text", "") for it in items for kw in ("全新赛季",)):
        logger.info("[dismiss_popups] Full-screen event page; closing via back key")
        if ctx.device is not None and hasattr(ctx.device, "press_key"):
            ctx.device.press_key(4)
        time.sleep(1.2)
        return

    # Full-screen pages (排行榜/伙伴助战/百宝谱) and the post-battle guild recruit page
    # before the generic × tap: their corner × does not register, and the recruit
    # page's 本周不再提醒 is a checkbox that leaves the page open.
    has_subwindow = any(any(kw in getattr(it, "text", "") for kw in ("伙伴助战", "百宝谱", "排行榜", "论坛", "招募大厅", "推荐帮派", "申请入帮", "祈愿", "百宠仙池", "召唤灵卡册")) for it in items)
    if has_subwindow:
        logger.info("[dismiss_popups] Closing full-screen sub-window via back key")
        if ctx.device is not None and hasattr(ctx.device, "press_key"):
            ctx.device.press_key(4)
        time.sleep(1.2)
        return

    # Check modal promo close button (e.g. 银钥匙半价啦 at 807, 141)
    promo_xbtn = _find(items, lambda it: it.text in ("×", "X", "x", "✕") and 500 < it.center[0] < 1250 and it.center[1] < 300)
    if promo_xbtn:
        # A parsed × below the genuine close-button band (y>=110) is suspect: full-frame
        # OCR returned a spurious × at (1144,113) while the real close × sat at (1138,53)
        # — clicking dead space looped the window open (live 2026-09-29, 星宿之影 window
        # blocked the activity panel for ~20 min). Re-locate via 3x upscaled top strip;
        # keep the parsed spot if that fails (covers mid-window × like 807,141).
        xy = _locate_corner_x(ctx, items) if promo_xbtn.center[1] >= 110 else None
        if xy is not None:
            x, y = xy
        else:
            x, y = _center(promo_xbtn)
        _click(ctx, x, y)
        logger.info(f"daily: dismiss modal promo × at ({x:.0f}, {y:.0f})")
        time.sleep(1.2)
        return

    xbtn = _find(items, lambda it: it.text in ("×", "X", "x", "✕") and it.center[0] > 1050 and it.center[1] < 120)
    if xbtn:
        x, y = _center(xbtn)
        _click(ctx, x, y)
        logger.info(f"daily: dismiss popup × at ({x:.0f}, {y:.0f})")
        time.sleep(1.2)
        return

    cancel = _find(items, lambda it: it.text == "取消" and it.center[1] < 45 and it.center[0] < 1210 and it.confidence > 0.5)
    if cancel:
        x, y = _center(cancel)
        _click(ctx, x, y)
        logger.info("daily: cancel chat composer")
        time.sleep(1.0)
        return


def popup_visible(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    items = _ocr_items(frame)
    ctx.variables["_last_frame_items"] = items
    xbtn = _find(items, lambda it: it.text in ("×", "X", "x", "✕") and it.center[0] > 1050 and it.center[1] < 120)
    close_text = _find(items, lambda it: any(kw in it.text for kw in ("确认关闭", "点击空白处关闭界面", "点击空白处返回主界面")))
    composer = _find(items, lambda it: it.text == "取消" and it.center[1] < 45 and it.center[0] < 1210 and it.confidence > 0.5)
    return xbtn is not None or close_text is not None or composer is not None


def always_true(ctx: PipelineContext, frame: Any, rec: NodeRecognition = None) -> bool:
    """Cheap recognition for nodes that exist only to run their action."""
    return True


def noop_wait(ctx, act=None):
    """Pause node: sleep for act.duration (NodeAction model has no args dict)."""
    # Exempt the next tick from the DAG stall watchdog: this node exists to wait.
    ctx.variables["wait_expected"] = True
    seconds = 0.5
    if isinstance(act, NodeAction):
        seconds = float(act.duration or 0.5)
    elif isinstance(act, dict):
        seconds = float(act.get("duration") or 0.5)
    time.sleep(seconds)
    return True


# --- quiz answering (科举/三界奇缘, zero-token local engine) ---------------------

def _is_keju_layout(items: list) -> bool:
    """科举乡试 window: title sits mid-screen and the question is below the 三界奇缘 ROI."""
    return _find(items, lambda it: "科举" in it.text and "乡试" in it.text and it.center[1] < 200) is not None


def _quiz_question_text(items: list) -> str:
    """Assemble the question from the question ROI, row-grouped like upstream reco_sjqy
    (20px row threshold, x-sorted), then strip 第n题/(n-m) markers and OCR misreads.

    科举乡试 uses a lower question band (below the 第n题/正确率 status row); the
    三界奇缘 band would only catch the "科举乡试·" title.
    """
    keju = _is_keju_layout(items)
    x1, y1, x2, y2 = KEJU_QUESTION_ROI if keju else QUIZ_QUESTION_ROI
    zone = [
        it for it in items
        if x1 <= it.center[0] <= x2 and y1 <= it.center[1] <= y2 and it.text.strip()
    ]
    # Status row of the 乡试 window (第n题 / 正确率) is not part of the question.
    # Only strip it for the 乡试 layout: the 三界奇缘 question itself begins with
    # "第9题：" (live 2026-09-27, 寻找天命取经人), and stripping every "第" there left
    # the question empty so the solver waited forever.
    if keju:
        zone = [it for it in zone if not any(kw in it.text for kw in ("第", "正确率", "当前得分", "乡试"))]
    if not zone:
        zone = [it for it in items if ("?" in it.text or "？" in it.text) and it.center[1] < 340 and it.text.strip()]
    if not zone:
        return ""
    zone.sort(key=lambda it: (round(it.center[1] / 20.0), it.center[0]))
    return clean_question_text(fix_ocr_noise("".join(it.text for it in zone)))


def _quiz_options(items: list) -> Tuple[List[str], list]:
    """Collect option texts + OCR items from the option ROI in row-major order (A B / C D).

    科举乡试 options sit lower (A/B ~y353, C/D ~y453) than the 三界奇缘 band.
    """
    x1, y1, x2, y2 = KEJU_OPTION_ROI if _is_keju_layout(items) else QUIZ_OPTION_ROI
    zone = [
        it for it in items
        if x1 <= it.center[0] <= x2 and y1 <= it.center[1] <= y2
    ]
    zone.sort(key=lambda it: (round(it.center[1] / 50.0), it.center[0]))
    texts: List[str] = []
    kept: list = []
    seen = set()
    for it in zone:
        raw = it.text.strip()
        if not raw or len(raw) > 16 or raw in seen:
            continue
        if raw in ("×", "X", "x", "✕") or any(kw in raw for kw in QUIZ_OPTION_NOISE_KWS):
            continue
        clean = QUIZ_OPTION_PREFIX_RE.sub("", fix_ocr_noise(raw))
        if not clean:
            continue
        seen.add(raw)
        texts.append(clean)
        kept.append(it)
    return texts, kept


def _quiz_vlm_fallback(ctx: PipelineContext, question: str, options: List[str]) -> Optional[int]:
    """Tier-2 VLM escalation — strictly opt-in via ctx.variables['quiz_vlm_enabled']
    so the daily run stays zero-token by default (Milestone 7 doctrine)."""
    if not question or not options or not ctx.variables.get("quiz_vlm_enabled", False):
        return None
    try:
        from plugins.mhxy_mobile.custom.vlm_solver import MHXYVLMSolver

        frame = ctx.variables.get("_last_frame")
        if frame is None:
            return None
        res = MHXYVLMSolver().solve_exam(image=frame, question=question, options=list(options))
        idx = int(res.get("option_index", -1))
        conf = float(res.get("confidence", 0.0))
        if 0 <= idx < len(options) and conf >= 0.5:
            logger.warning(f"[quiz] Tier-2 VLM resolved: [{options[idx]}] conf={conf:.2f} (local bank missed)")
            return idx
    except Exception as e:
        logger.debug(f"[quiz] VLM escalation unavailable: {e}")
    return None


def handle_quiz(ctx: PipelineContext, act: NodeAction) -> None:
    """Answer 科举/三界奇缘 screens with the local zero-token QuizSolver.

    Policies borrowed from upstream Maa_MHXY_MG reco_sjqy:
    - question ROI row-grouping + 第n题/(n-m) marker stripping + OCR replace table;
    - click only on exact/fuzzy bank hits with confidence >= 0.6;
    - bank miss -> opt-in Tier-2 VLM, else click the FIRST option (upstream policy).
    """
    items = ctx.variables.get("_last_frame_items") or []
    v = ctx.variables

    # 0) Activity finished: collect the completion gift (left panel of the quiz
    # window, above the 已获得奖励 label) BEFORE leaving — it is one-click-only and
    # lost forever once the window closes (live lesson 2026-09-25).
    if _find(items, lambda it: any(kw in it.text for kw in QUIZ_DONE_KWS)):
        if not v.get("quiz_gift_clicked"):
            gift_label = _find_text(items, "已获得奖励")
            if gift_label is not None:
                lx, ly = _center(gift_label)
                gx, gy = lx + 30, ly - 188  # gift box hangs above its label
            else:
                gx, gy = 330, 320  # fixed position on the completion page
            logger.info(f"[quiz] Quiz finished; clicking completion gift at ({gx:.0f}, {gy:.0f})")
            v["quiz_gift_clicked"] = True
            _click(ctx, gx, gy)
            time.sleep(1.5)
            return
        confirm = _find(items, lambda it: it.text in ("确定", "确认") and 300 < it.center[1] < 620 and 500 < it.center[0] < 1000)
        if confirm is not None:
            cx_, cy_ = _center(confirm)
            logger.info(f"[quiz] Confirming gift reward popup at ({cx_:.0f}, {cy_:.0f})")
            _click(ctx, cx_, cy_)
            time.sleep(1.2)
            return
        logger.info("[quiz] Quiz activity finished, pressing back to leave")
        v["quiz_gift_clicked"] = False
        if ctx.device is not None and hasattr(ctx.device, "press_key"):
            ctx.device.press_key(4)
        completed = v.setdefault("completed_tasks", [])
        # The same quiz window serves 三界奇缘 and 科举乡试. The window title tells
        # them apart; current_task_name is only a fallback (it is empty when the run
        # resumes on an already-open completion screen).
        quiz_task = None
        if _find(items, lambda it: "科举" in it.text):
            quiz_task = "科举乡试"
        elif _find(items, lambda it: "三界奇缘" in it.text):
            quiz_task = "三界奇缘"
        elif v.get("current_task_name") in ("三界奇缘", "科举乡试"):
            quiz_task = v["current_task_name"]
        else:
            # No title and no current task (the 三界奇缘 completion page carries only
            # the done wording): keep the historical default so it still gets marked.
            quiz_task = "三界奇缘"
        if quiz_task and quiz_task not in completed:
            completed.append(quiz_task)
        v["current_task_done"] = True
        time.sleep(1.5)
        return

    # 1) Result feedback interstitials (回答正确/答错了 -> 确定/继续/下一题)
    if _find(items, lambda it: any(kw in it.text for kw in QUIZ_FEEDBACK_KWS)):
        cont = _find(items, lambda it: any(kw in it.text for kw in ("确定", "继续", "下一题")) and 300 < it.center[1] < 680)
        if cont is not None:
            fx, fy = _center(cont)
            logger.info(f"[quiz] Dismissing result feedback [{cont.text}] at ({fx:.0f}, {fy:.0f})")
            _click(ctx, fx, fy)
            time.sleep(1.2)
            return

    # 2) Local deterministic solve
    question = _quiz_question_text(items)
    options, option_items = _quiz_options(items)

    # 2.5) A popup is covering the quiz UI (system notice / upgrade guide): dismiss
    # it instead of idling or blind-clicking its texts as if they were an answer.
    def _dismiss_covering_popup() -> None:
        # Same header test (and threshold) as the bank-miss guard below: a quiz
        # header anywhere above y=250 means the × at top right is the quiz's own
        # exit button, not a covering popup's close button.
        if _find(items, lambda it: any(kw in it.text for kw in ("三界奇缘", "科举", "答题", "请作答")) and it.center[1] < 250):
            return False  # quiz header visible: the × is the quiz's own exit button
        xbtn = _find(items, lambda it: it.text in ("×", "X", "x", "✕") and 500 < it.center[0] < 1250 and it.center[1] < 300)
        if xbtn is not None:
            xx, xy = _center(xbtn)
            logger.warning(f"[quiz] Covering popup over quiz UI; dismissing × at ({xx:.0f}, {xy:.0f})")
            _click(ctx, xx, xy)
            time.sleep(1.2)
            return True
        return False

    if question and any(m in question for m in ("通关推荐配置", "指引", "公告", "咨询专家", "智能指引")):
        if _dismiss_covering_popup():
            return
    if not question or not option_items:
        if _dismiss_covering_popup():
            return
        logger.info("[quiz] No question/options parsed yet, waiting for next tick")
        time.sleep(1.0)
        return

    decision = get_default_solver().answer(question, options)
    v["quiz_bank_hit"] = decision.bank_hit
    v["quiz_confidence"] = decision.confidence
    v["quiz_source"] = decision.source
    logger.info(
        f"[quiz] Q='{question[:40]}' src={decision.source} conf={decision.confidence:.2f} "
        f"elapsed={decision.elapsed_ms:.1f}ms -> [{decision.option_text or '<miss>'}]"
    )

    # 3) Confident local answer (exact/fuzzy bank hit only; low band is never auto-clicked).
    # "寻找N个X" questions keep the same options up and want every matching one clicked
    # before the question advances (live 2026-09-27: 第9题 寻找3个天命取经人 stalled at
    # 1/3 because one tick clicked one option and the next tick saw the same screen).
    multi_need = 1
    multi_match = re.search(r"寻找\s*(\d+)\s*个", question)
    if multi_match:
        multi_need = int(multi_match.group(1))
    if (
        decision.bank_hit
        and decision.option_index >= 0
        and decision.source in ("exact", "fuzzy")
        and decision.confidence >= 0.6
    ):
        targets = [option_items[decision.option_index]]
        if multi_need > 1:
            valid = {normalize_text(a) for a in decision.answers}
            targets = [it for it in option_items if normalize_text(it.text) in valid] or targets
        for it in targets[:multi_need]:
            _click(ctx, it.center[0], it.center[1])
            time.sleep(0.8)
        time.sleep(0.6)
        return

    # 4) Tier-2 VLM escalation (opt-in)
    vlm_idx = _quiz_vlm_fallback(ctx, question, options)
    if vlm_idx is not None and 0 <= vlm_idx < len(option_items):
        it = option_items[vlm_idx]
        _click(ctx, it.center[0], it.center[1])
        time.sleep(1.2)
        return

    # 5) Upstream fallback policy: bank miss -> click the FIRST option. Guard: only
    # inside a genuine quiz window (header marker present). Without one, a bank miss
    # means the "question" is a misparsed banner/HUD (live 2026-09-29: the 青丘奇珍
    # banner reached here and blind-fired the first "option"). Admitting the screen
    # cannot be read and waiting is the safe behavior.
    quiz_header_present = bool(_find(
        items,
        lambda it: any(kw in it.text for kw in ("三界奇缘", "科举", "答题", "请作答")) and it.center[1] < 250,
    ))
    if not quiz_header_present:
        refusal_streak = int(ctx.variables.get("quiz_refusal_streak", 0)) + 1
        ctx.variables["quiz_refusal_streak"] = refusal_streak
        logger.warning(
            f"[quiz] Bank miss for '{question[:40]}' and no quiz header on screen — "
            f"refusing first-option blind click, waiting"
        )
        if refusal_streak >= 5:
            # The same misparsed banner/HUD keeps re-classifying as quiz_open and the
            # wait path issues no clicks, so neither the same-coord watchdog nor the
            # stall watchdog can fire (an animated banner keeps frames changing).
            # One BACK clears the overlay layer; resetting the streak re-arms a
            # bounded "5 refusals -> one BACK" loop (八修 counter semantics). A single
            # BACK never raises the exit confirm, which the framework never confirms.
            ctx.variables["quiz_refusal_streak"] = 0
            logger.warning("[quiz] Refusal streak >= 5 — pressing BACK once to clear the overlay layer")
            if ctx.device is not None and hasattr(ctx.device, "press_key"):
                ctx.device.press_key(4)
            time.sleep(1.5)
        else:
            time.sleep(1.0)
        return
    logger.warning(f"[quiz] Bank miss for '{question[:40]}', clicking first option (upstream policy)")
    _click(ctx, option_items[0].center[0], option_items[0].center[1])
    time.sleep(1.5)
