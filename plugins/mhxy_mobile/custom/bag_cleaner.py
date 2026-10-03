"""
Dedicated bag-cleanup (清理背包) OCR-driven operators.

The game toasts 背包空间不足 when a quest purchase needs a bag slot that does
not exist (live 2026-10-03: the 师门-阴晴圆缺 定神香 purchase could never
succeed), which gated whole daily chains. The user asked for a dedicated
cleanup feature (2026-10-03) — which overrides the earlier "never touch the
bag" red line. That red line existed because discarding is irreversible, so
this module is safety-first by construction:

* **Whitelist-driven**: only item names listed in the user-editable whitelist
  (plugins/mhxy_mobile/custom/data/bag_clean_whitelist.json) are ever acted
  on. An empty whitelist means the pass is a scan+log no-op — nothing is
  clicked, the bag contents are just logged so the user can fill the list.
* **Never-touch beats the whitelist**: names containing 藏宝图, 宝图, 仙玉,
  元宝, 金刚石, 装备, 任务, 活动, 镖银 are never clicked even if the user
  whitelists them. OCR mis-reads alias item names, so the guard is
  keyword-based, not exact-match.
* **Sell over discard**: the flow clicks 出售 then a confirm button, and the
  confirm is only clicked when sell wording (出售/卖出/获得) is on screen — a
  bare 确定 must never be clicked (mirrors the deposit-confirm rule), and a
  dialog mentioning 仙玉 or 离开游戏 aborts the confirm outright.
* **Session cap**: max_items_per_session (default 10) bounds the pass so a
  runaway OCR match cannot empty the bag.
* **No blind coordinates**: every item/sell/confirm click lands on an
  OCR-verified text. Only the bag-button open may fall back to the
  configured coordinates.json entry (a framework-trusted constant), since
  the bag button is an icon without a text label.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, List

from loguru import logger

from scheduler.dag import NodeAction, NodeRecognition, PipelineContext
from plugins.mhxy_mobile.custom import daily_handlers as _dh
from plugins.mhxy_mobile.custom.handlers import _get_coord_center

WHITELIST_PATH = Path(__file__).resolve().parent / "data" / "bag_clean_whitelist.json"

# Hardcoded never-touch protection — beats the whitelist (see module docstring).
NEVER_TOUCH_KWS = ("藏宝图", "宝图", "仙玉", "元宝", "金刚石", "装备", "任务", "活动", "镖银")

# UI chrome that must never be mistaken for an item name in the bag grid scan.
BAG_CHROME_KWS = (
    "背包", "包裹", "关闭", "整理", "出售", "丢弃", "使用", "确定", "取消",
    "金币", "银币", "银两", "铜币", "体力", "活力", "更多", "全部", "锁", "页",
    "物品", "任务", "配方", "仓库", "外观", "衣橱", "好友", "帮派", "门派",
    "人物评分", "获得", "评分", "灵韵", "背包已满",
)

# Chat/system lines occlude the open bag panel; item names never carry these.
BAG_CHAT_MARKERS = ("【", "】", "[", "]")


def _is_item_name(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if any(kw in t for kw in BAG_CHROME_KWS):
        return False
    if any(m in t for m in BAG_CHAT_MARKERS):
        return False
    # chat/system lines start with a channel label
    if t.startswith(("世界", "系统", "队伍", "帮派", "门派", "当前", "喇叭")):
        return False
    # pure numbers/currency are not items
    if all(c.isdigit() or c in ",，.。+|丨" for c in t):
        return False
    return True

# The main-UI bag button label.
BAG_BUTTON_KWS = ("背包", "包裹")

DEFAULT_MAX_ITEMS = 10


class _GridItem:
    """An OCR hit remapped from the upscaled bag-grid crop back to baseline
    coordinates; only .text/.center matter to _find/_center."""

    def __init__(self, text: str, center: tuple, confidence: float = 0.95):
        self.text = text
        self.center = center
        self.confidence = confidence
        self.bbox = (int(center[0]) - 20, int(center[1]) - 10, 40, 20)


def _get_coord_center_roi(ctx: PipelineContext) -> tuple:
    """The bag-scan ROI from coordinates.json (baotu.bag_roi), 1280x720 baseline."""
    coords = ctx.variables.get("coordinates", {})
    box = coords.get("baotu", {}).get("bag_roi", [760, 180, 470, 470])
    return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))


def _scan_bag_grid(ctx: PipelineContext) -> List[Any]:
    """OCR the bag grid: crop the configured bag_roi, upscale 2x so the small
    item-name font resolves, and map OCR boxes back to baseline coordinates so
    clicks land on the real items. Falls back to the full frame when the crop
    yields nothing, then to the test seam (_bag_clean_ocr_queue)."""
    if ctx.device is not None and hasattr(ctx.device, "screencap"):
        try:
            raw = ctx.device.screencap()
            if raw:
                import cv2
                import numpy as np
                frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    ctx.variables["_last_frame"] = frame
                    rx, ry, rw, rh = _get_coord_center_roi(ctx)
                    fh, fw = frame.shape[:2]
                    crop = frame[max(0, int(ry)):min(fh, int(ry + rh)), max(0, int(rx)):min(fw, int(rx + rw))]
                    if crop.size:
                        big = cv2.resize(crop, (crop.shape[1] * 2, crop.shape[0] * 2), interpolation=cv2.INTER_CUBIC)
                        found = _dh._ocr_items(big)
                        items = [
                            _GridItem(it.text, (rx + it.center[0] / 2.0, ry + it.center[1] / 2.0), it.confidence)
                            for it in found
                        ]
                        if any(_is_item_name(getattr(it, "text", "")) for it in items):
                            return items
        except Exception as exc:
            logger.warning(f"[bag_clean] 背包网格取帧失败：{exc}")
    # Test seam / full-frame fallback: the crop missed the grid (panel layout
    # differs) — a whole-frame scan at least logs the visible names.
    queue = ctx.variables.get("_bag_clean_ocr_queue")
    if queue:
        return queue.pop(0)
    return _scan_live(ctx)


def _load_whitelist() -> dict:
    try:
        with open(WHITELIST_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning(f"[bag_clean] 白名单读取失败（按空处理）：{exc}")
        return {}


def _scan_live(ctx: PipelineContext, roi: tuple = None) -> List[Any]:
    """One live OCR of the current screen, optionally cropped to a 1280x720
    baseline ROI (the device's screencap is already resized to that baseline).
    Test seam: a device that cannot screencap serves _bag_clean_ocr_queue (a
    list of item lists, popped per call) so each scan in the pass can be
    scripted; the injected cache _last_frame_items is the final fallback."""
    items: List[Any] = []
    fresh = False
    if ctx.device is not None and hasattr(ctx.device, "screencap"):
        try:
            raw = ctx.device.screencap()
            if raw:
                import cv2
                import numpy as np
                frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    fresh = True
                    ctx.variables["_last_frame"] = frame
                    if roi is not None:
                        rx, ry, rw, rh = roi
                        fh, fw = frame.shape[:2]
                        crop = frame[max(0, int(ry)):min(fh, int(ry + rh)), max(0, int(rx)):min(fw, int(rx + rw))]
                        items = _dh._ocr_items(crop) if crop.size else []
                    else:
                        items = _dh._ocr_items(frame)
        except Exception as exc:
            logger.warning(f"[bag_clean] 实机取帧失败：{exc}")
    if not fresh:
        queue = ctx.variables.get("_bag_clean_ocr_queue")
        if queue:
            items = queue.pop(0)
        else:
            items = ctx.variables.get("_last_frame_items") or []
    return items


def needs_bag_clean(ctx: PipelineContext, frame: Any, rec: NodeRecognition = None) -> bool:
    """Recognition for the daily-DAG branch: the game latched 背包空间不足 and
    this session has not attempted a cleanup."""
    return bool(ctx.variables.get("shop_blocked_bag_full")) and not ctx.variables.get("bag_clean_attempted")


def clean_pass_ready(ctx: PipelineContext, frame: Any, rec: NodeRecognition = None) -> bool:
    """Recognition for the standalone pipeline entry: run exactly one pass —
    False once it has completed, so the node does not loop to timeout."""
    return not ctx.variables.get("bag_clean_attempted")


def run_bag_clean_pass(ctx: PipelineContext, act: NodeAction = None) -> None:
    """One bounded cleanup pass: open bag -> scan -> sell whitelisted items ->
    close. With an empty whitelist the pass is a scan+log no-op."""
    v = ctx.variables
    if v.get("in_battle"):
        logger.info("[bag_clean] 战斗中无法打开背包 — 本次跳过，稍后重试")
        return

    # 1. Find and click the bag button. OCR first; the main-UI bag button is an
    # icon without a text label (live 2026-10-03: no 背包 text anywhere on the
    # world screen), so the configured coordinates.json entry is the fallback —
    # the same trust every other fixed button in the framework gets. The
    # coordinate space is the 1280x720 OCR baseline; device.click scales it.
    screen = _scan_live(ctx)
    bag_btn = _dh._find(screen, lambda it: any(kw in it.text for kw in BAG_BUTTON_KWS))
    if bag_btn is not None:
        bx, by = _dh._center(bag_btn)
        logger.info(f"[bag_clean] Opening bag via OCR label at ({bx:.0f}, {by:.0f})")
    else:
        coords = ctx.variables.get("coordinates", {})
        bx, by = _get_coord_center(coords, "common", "btn_bag", (1180, 640, 45, 45))
        logger.info(f"[bag_clean] Opening bag via configured btn_bag at ({bx:.0f}, {by:.0f})")
    _dh._click(ctx, bx, by)
    time.sleep(1.5)

    # 2. Scan the bag grid (upscaled crop for the small item-name font, with a
    # whole-frame fallback) and log what is in it.
    bag_items = _scan_bag_grid(ctx)
    item_names = [
        it.text for it in bag_items
        if _is_item_name(getattr(it, "text", ""))
    ]
    logger.info(f"[bag_clean] 背包扫描：{len(item_names)} 个物品名：{item_names}")

    # 3. Cleanup is whitelist-driven; an empty whitelist means scan-only.
    whitelist = _load_whitelist()
    sellable = [s for s in whitelist.get("sellable", []) if isinstance(s, str) and s.strip()]
    cap = max(1, int(whitelist.get("max_items_per_session", DEFAULT_MAX_ITEMS)))
    if not sellable:
        logger.info(
            "[bag_clean] 白名单为空 — 仅扫描不清理。请在 "
            f"{WHITELIST_PATH.name} 的 sellable 列表填入允许出售的物品名。"
        )

    # 4. Sell whitelisted items one by one, every click OCR-verified.
    sold = 0
    for name in sellable:
        if sold >= cap:
            logger.info(f"[bag_clean] 已达本次上限 {cap} — 停止")
            break
        if any(kw in name for kw in NEVER_TOUCH_KWS):
            logger.warning(f"[bag_clean] 白名单项 [{name}] 命中永不碰清单 — 跳过")
            continue
        target = _dh._find(bag_items, lambda it: name in it.text)
        if target is None:
            logger.info(f"[bag_clean] [{name}] 不在背包当前页 — 跳过")
            continue
        tx, ty = _dh._center(target)
        logger.info(f"[bag_clean] 选中 [{name}] at ({tx:.0f}, {ty:.0f})")
        _dh._click(ctx, tx, ty)
        time.sleep(1.0)

        sell_items = _scan_live(ctx)
        sell_btn = _dh._find(sell_items, lambda it: it.text in ("出售", "卖出"))
        if sell_btn is None:
            logger.info(f"[bag_clean] [{name}] 无出售按钮（可能不可出售）— 跳过")
            continue
        sx, sy = _dh._center(sell_btn)
        _dh._click(ctx, sx, sy)
        time.sleep(1.0)

        confirm_items = _scan_live(ctx)
        confirm_texts = [getattr(it, "text", "") for it in confirm_items]
        # Safety: never confirm a money/exit dialog — the wording guard must hold.
        if any("仙玉" in t for t in confirm_texts) or any("离开游戏" in t for t in confirm_texts):
            logger.warning(f"[bag_clean] [{name}] 确认框命中仙玉/离开游戏 — 中止确认（安全红线）")
            continue
        if not any(kw in t for t in confirm_texts for kw in ("出售", "卖出", "获得")):
            logger.info(f"[bag_clean] [{name}] 确认框无出售文案 — 不点确定（防误触）")
            continue
        confirm_btn = _dh._find(confirm_items, lambda it: it.text in ("确定", "确认"))
        if confirm_btn is None:
            logger.info(f"[bag_clean] [{name}] 未找到确认按钮 — 跳过")
            continue
        cx, cy = _dh._center(confirm_btn)
        _dh._click(ctx, cx, cy)
        time.sleep(1.2)
        sold += 1
        logger.info(f"[bag_clean] 出售 [{name}] ({sold}/{cap})")

    # 5. Close the bag.
    bag_close = _dh._find(_scan_live(ctx), lambda it: it.text.strip() in ("关闭", "×", "X", "x", "✕"))
    if bag_close is not None:
        qx, qy = _dh._center(bag_close)
        _dh._click(ctx, qx, qy)
        time.sleep(1.0)
    elif ctx.device is not None and hasattr(ctx.device, "press_key"):
        ctx.device.press_key(4)
        time.sleep(1.0)

    # 6. One pass per session; free the daily gate if space was actually freed.
    v["bag_clean_attempted"] = True
    if sold > 0:
        v.pop("shop_blocked_bag_full", None)
        logger.info(
            f"[bag_clean] 清理完成：出售 {sold} 件，腾出空间 — 解除背包满门控，"
            "本次运行可继续拾取被门控的日常"
        )
    else:
        logger.info("[bag_clean] 未出售任何物品 — 背包满门控保持，需填写白名单后重试")
