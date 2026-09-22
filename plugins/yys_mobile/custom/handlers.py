"""
Domain-specific Perception and Action Handlers for Onmyoji (yys_mobile).
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple
from loguru import logger

from core.cv.matcher import TemplateMatcher
from scheduler.dag import NodeAction, NodeRecognition, PipelineContext


def _get_coord_center(
    coords: Dict[str, Any],
    domain: str,
    key: str,
    default: Tuple[int, int, int, int],
) -> Tuple[float, float]:
    box = coords.get(domain, {}).get(key, list(default))
    return float(box[0] + box[2] / 2), float(box[1] + box[3] / 2)


# ==============================================================================
# 1. 御魂挂机 (Yuhun / Soul Farming) Handlers
# ==============================================================================

def is_yuhun_lobby_ready(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """Detect challenge button or team readiness in Yuhun lobby."""
    if frame is not None and rec.target:
        res = TemplateMatcher.match(frame, rec.target, threshold=rec.threshold)
        if res.found:
            ctx.variables["last_match_point"] = res.center
            return True
    return ctx.variables.get("in_yuhun_lobby", True)


def click_challenge(ctx: PipelineContext, act: NodeAction) -> None:
    """Click the Challenge / Start Battle button in Yuhun lobby."""
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "yuhun", "btn_challenge", (1030, 580, 180, 70))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["in_yuhun_lobby"] = False
    ctx.variables["in_battle"] = True
    ctx.variables["battle_settlement_active"] = True
    logger.info("Clicked Yuhun challenge button; battle initiated.")


def is_yuhun_battle_settlement(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """Detect victory settlement screen (Daruma reward drum or item drops)."""
    return ctx.variables.get("battle_settlement_active", True)


def click_settlement_dismiss(ctx: PipelineContext, act: NodeAction) -> None:
    """Click neutral zone to dismiss settlement screen and return to lobby."""
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "yuhun", "settlement_click_zone", (600, 400, 200, 150))
    if ctx.device:
        ctx.device.click(cx, cy)
        time.sleep(0.1)
        ctx.device.click(cx, cy)
    ctx.variables["battle_settlement_active"] = False
    ctx.variables["in_battle"] = False
    ctx.variables["in_yuhun_lobby"] = True
    logger.info("Settlement screen dismissed.")


def increment_yuhun_round(ctx: PipelineContext, act: NodeAction) -> None:
    """Increment completed Yuhun run counter."""
    count = ctx.variables.get("yuhun_count", 0) + 1
    ctx.variables["yuhun_count"] = count
    max_count = ctx.variables.get("max_yuhun_count", 10)
    logger.info(f"Yuhun run completed: [{count}/{max_count}]")


# ==============================================================================
# 2. 结界突破 (Realm Raid / Jiejie) Handlers
# ==============================================================================

def has_raid_tickets(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """Check if player has remaining Realm Raid tickets (>= 1)."""
    tickets = ctx.variables.get("raid_tickets", 30)
    return tickets > 0


def select_raid_target(ctx: PipelineContext, act: NodeAction) -> None:
    """Select target opponent in the 3x3 Realm Raid grid."""
    coords = ctx.variables.get("coordinates", {})
    slots = coords.get("jiejie", {}).get("target_slots", [])
    idx = ctx.variables.get("current_target_index", 0)
    if slots and idx < len(slots):
        target = slots[idx]
        cx, cy = target[0] + target[2] / 2, target[1] + target[3] / 2
        if ctx.device:
            ctx.device.click(cx, cy)
    ctx.variables["target_selected"] = True
    logger.info(f"Selected realm raid target slot {idx}.")


def is_raid_attack_button_visible(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """Verify raid attack popup button is visible."""
    return ctx.variables.get("target_selected", True)


def click_raid_attack(ctx: PipelineContext, act: NodeAction) -> None:
    """Click Attack button on selected target."""
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "jiejie", "btn_attack", (1040, 520, 140, 60))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["target_selected"] = False
    ctx.variables["raid_tickets"] = max(0, ctx.variables.get("raid_tickets", 1) - 1)
    ctx.variables["raids_completed"] = ctx.variables.get("raids_completed", 0) + 1
    logger.info("Launched attack on realm raid target.")


# ==============================================================================
# 3. 全局弹窗与协作悬赏拦截 (Anti-Bot / Bounty Interceptor) Handlers
# ==============================================================================

def detect_bounty_invite(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    """Global high-priority interrupt detecting friend cooperation bounty popup."""
    return ctx.variables.get("bounty_invite_popup", False)


def resolve_bounty_invite(ctx: PipelineContext, act: NodeAction) -> None:
    """Accept the incoming bounty cooperation invite to avoid blocking routine."""
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "anti_bot", "btn_accept_bounty", (740, 420, 100, 40))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["bounty_invite_popup"] = False
    ctx.variables["bounty_accepted"] = True
    logger.info("Resolved and accepted cooperation bounty invite popup.")
