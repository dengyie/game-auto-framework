"""
Custom recognition and action operators for Milestone 2 pipelines:
- 组队抓鬼 (team_zhuogui)
- 320/520 副本 (fuben_320_520)
- 工坊考古 (gongfang_kaogu)
- 活力商会 (huoli_shanghui)
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple
from loguru import logger

from scheduler.dag import NodeAction, NodeRecognition, PipelineContext


def _get_coord_center(coords: Dict[str, Any], domain: str, key: str, default: Tuple[int, int, int, int]) -> Tuple[float, float]:
    box = coords.get(domain, {}).get(key, list(default))
    return float(box[0] + box[2] / 2), float(box[1] + box[3] / 2)


# ==============================================================================
# 1. 组队抓鬼 (Team Ghost Hunting) Handlers
# ==============================================================================

def is_team_panel_open(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("team_panel_open", False) or ctx.variables.get("is_team_open", False)


def click_open_team(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "team", "btn_team_top", (1120, 240, 120, 35))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["team_panel_open"] = True


def click_create_team(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "team", "btn_create_team", (980, 600, 100, 40))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["is_leader"] = True
    ctx.variables["team_member_count"] = ctx.variables.get("team_member_count", 1)


def is_team_full(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    # Check if team has 4 or 5 members
    member_count = ctx.variables.get("team_member_count", 5)
    return member_count >= 4


def click_auto_match(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "team", "btn_auto_match", (850, 600, 100, 40))
    if ctx.device:
        ctx.device.click(cx, cy)
    # Simulate matching full team
    ctx.variables["team_member_count"] = 5
    ctx.variables["team_panel_open"] = False


def find_zhongkui(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("near_zhongkui", True)


def click_talk_zhongkui(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "zhuogui", "btn_talk_zhongkui", (930, 430, 80, 30))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["zhongkui_dialog_open"] = True


def is_zhongkui_dialog_open(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("zhongkui_dialog_open", True)


def click_accept_ghost(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "zhuogui", "btn_accept_ghost", (930, 430, 80, 30))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["zhongkui_dialog_open"] = False
    ctx.variables["has_ghost_quest"] = True


def check_double_points(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    # Need double points if not yet enabled
    return not ctx.variables.get("double_points_active", False)


def click_fetch_double(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "zhuogui", "btn_double_points", (1020, 280, 80, 30))
    if ctx.device:
        ctx.device.click(cx, cy)
        time.sleep(0.1)
        cx2, cy2 = _get_coord_center(coords, "zhuogui", "btn_confirm_double", (640, 450, 90, 35))
        ctx.device.click(cx2, cy2)
    ctx.variables["double_points_active"] = True


def is_ghost_tracking(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("has_ghost_quest", True) and not ctx.variables.get("in_ghost_battle", False)


def click_ghost_tracker(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "common", "btn_task_track_top", (1120, 195, 120, 35))
    if ctx.device:
        ctx.device.click(cx, cy)
    # Simulate moving and engaging ghost battle
    ctx.variables["in_ghost_battle"] = True


def is_ghost_in_battle(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("in_ghost_battle", False)


def handle_ghost_combat(ctx: PipelineContext, act: NodeAction) -> None:
    time.sleep(act.duration if act and act.duration > 0 else 0.1)
    ctx.variables["in_ghost_battle"] = False
    ctx.variables["ghost_battle_done"] = True


def is_ghost_battle_ended(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    # Battle concluded
    return not ctx.variables.get("in_ghost_battle", False) or ctx.variables.get("ghost_battle_done", False)


def increment_ghost_round(ctx: PipelineContext, act: NodeAction) -> None:
    ctx.variables["in_ghost_battle"] = False
    ctx.variables["ghost_battle_done"] = False
    ctx.variables["zhuogui_rounds"] = ctx.variables.get("zhuogui_rounds", 0) + 1
    logger.info(f"Ghost Hunting completed round {ctx.variables['zhuogui_rounds']}")


def apply_join_ghost_team(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "team", "btn_join_team", (1050, 600, 90, 35))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["in_team"] = True
    ctx.variables["is_following"] = True


def is_following_leader(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("is_following", True)


# ==============================================================================
# 2. 副本 (Dungeon 320/520) Handlers
# ==============================================================================

def is_activity_open(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("activity_open", False)


def click_open_activity(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "common", "btn_activity", (450, 40, 45, 45))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["activity_open"] = True


def find_fuben_entry(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("activity_open", True)


def click_enter_fuben(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    fuben_type = ctx.variables.get("fuben_type", "320")
    btn_key = "btn_select_fuben_320" if fuben_type == "320" else "btn_select_fuben_520"
    cx, cy = _get_coord_center(coords, "fuben", btn_key, (450, 280, 120, 40))
    if ctx.device:
        ctx.device.click(cx, cy)
        time.sleep(0.1)
        cx2, cy2 = _get_coord_center(coords, "fuben", "btn_enter_fuben", (930, 580, 110, 40))
        ctx.device.click(cx2, cy2)
    ctx.variables["activity_open"] = False
    ctx.variables["inside_fuben"] = True
    ctx.variables["fuben_stage"] = 1


def is_fuben_dialog_active(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("fuben_dialog_active", True) and ctx.variables.get("inside_fuben", False)


def click_skip_fuben_dialog(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "fuben", "btn_skip_dialog", (1120, 580, 80, 30))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["fuben_dialog_active"] = False
    ctx.variables["in_fuben_battle"] = True


def is_fuben_in_battle(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("in_fuben_battle", False)


def handle_fuben_combat(ctx: PipelineContext, act: NodeAction) -> None:
    time.sleep(act.duration if act and act.duration > 0 else 0.1)
    ctx.variables["in_fuben_battle"] = False
    ctx.variables["fuben_stage_cleared"] = True


def is_fuben_battle_ended(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return not ctx.variables.get("in_fuben_battle", False) or ctx.variables.get("fuben_stage_cleared", False)


def advance_fuben_stage(ctx: PipelineContext, act: NodeAction) -> None:
    ctx.variables["in_fuben_battle"] = False
    ctx.variables["fuben_stage_cleared"] = False
    stage = ctx.variables.get("fuben_stage", 1) + 1
    ctx.variables["fuben_stage"] = stage
    if stage > ctx.variables.get("fuben_max_stages", 3):
        ctx.variables["fuben_settlement_ready"] = True
    else:
        ctx.variables["fuben_dialog_active"] = True


def is_fuben_settlement_ready(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("fuben_settlement_ready", False)


def click_fuben_settlement(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "fuben", "btn_fuben_settlement", (640, 580, 120, 45))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["inside_fuben"] = False
    ctx.variables["fuben_completed"] = True


# ==============================================================================
# 3. 工坊考古 (Workshop Archaeology) Handlers
# ==============================================================================

def needs_shovels(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    shovels = ctx.variables.get("shovel_count", 0)
    return shovels <= 0


def click_buy_shovels(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "kaogu", "btn_buy_shovel", (880, 520, 70, 30))
    if ctx.device:
        ctx.device.click(cx, cy)
    buy_amount = ctx.variables.get("buy_shovel_amount", 5)
    ctx.variables["shovel_count"] = buy_amount
    logger.info(f"Purchased {buy_amount} Luoyang shovels")


def has_shovels(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("shovel_count", 0) > 0


def click_use_shovel(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "kaogu", "btn_use_shovel", (720, 520, 80, 35))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["navigating_to_tomb"] = True


def is_tomb_reached(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("navigating_to_tomb", True)


def trigger_compass_dig(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "kaogu", "btn_compass_spin", (640, 360, 100, 100))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["navigating_to_tomb"] = False
    ctx.variables["shovel_count"] = max(0, ctx.variables.get("shovel_count", 1) - 1)
    ctx.variables["digs_completed"] = ctx.variables.get("digs_completed", 0) + 1
    # Check if triggered battle with tomb thief or found relic
    if ctx.variables.get("dig_event_thief", False):
        ctx.variables["in_thief_battle"] = True
    else:
        ctx.variables["unappraised_relics"] = ctx.variables.get("unappraised_relics", 0) + 1


def is_thief_battle_active(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("in_thief_battle", False)


def click_appraise_and_sell(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "kaogu", "btn_appraise_relic", (720, 480, 80, 35))
    if ctx.device:
        ctx.device.click(cx, cy)
        time.sleep(0.1)
        cx2, cy2 = _get_coord_center(coords, "kaogu", "btn_sell_fake", (820, 480, 80, 35))
        ctx.device.click(cx2, cy2)
    ctx.variables["unappraised_relics"] = 0
    ctx.variables["kaogu_finished"] = True


# ==============================================================================
# 4. 活力商会 (Vigor & Chamber of Commerce) Handlers
# ==============================================================================

def check_huoli_sufficient(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    huoli = ctx.variables.get("current_huoli", 500)
    min_huoli = ctx.variables.get("min_huoli_threshold", 300)
    return huoli >= min_huoli


def execute_huoli_work(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    strategy = ctx.variables.get("huoli_strategy", "work")  # "work", "cooking", "alchemy"
    btn_key = "btn_quick_work" if strategy == "work" else "btn_cook_alchemy"
    cx, cy = _get_coord_center(coords, "huoli", btn_key, (920, 580, 100, 40))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["current_huoli"] = max(0, ctx.variables.get("current_huoli", 500) - 300)
    ctx.variables["huoli_consumed"] = True


def click_open_shanghui(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "shanghui", "btn_shop_tab", (1080, 40, 45, 45))
    if ctx.device:
        ctx.device.click(cx, cy)
        time.sleep(0.1)
        cx2, cy2 = _get_coord_center(coords, "shanghui", "btn_shanghui_tab", (220, 120, 80, 35))
        ctx.device.click(cx2, cy2)
    ctx.variables["shanghui_open"] = True


def has_items_to_sell(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("has_unbound_items", True)


def click_batch_sell(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "shanghui", "btn_batch_sell", (1020, 600, 110, 40))
    if ctx.device:
        ctx.device.click(cx, cy)
        time.sleep(0.1)
        cx2, cy2 = _get_coord_center(coords, "shanghui", "btn_confirm_sell", (640, 480, 90, 35))
        ctx.device.click(cx2, cy2)
    ctx.variables["has_unbound_items"] = False
    ctx.variables["shanghui_cleared"] = True


# ==============================================================================
# 5. 新手起号与基础主线任务 (Basic & Novice Tasks) Handlers
# ==============================================================================

def click_enter_game_world(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "novice", "btn_enter_game", (640, 520, 160, 45))
    if ctx.device:
        ctx.device.click(cx, cy)
    if ctx.variables.get("need_create_role", False):
        ctx.variables["is_role_selection"] = True
    else:
        ctx.variables["in_world"] = True
    logger.info("Executed click_enter_game_world; character entered game world.")


def is_role_selection_screen(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("is_role_selection", False)


def click_confirm_role_and_sect(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "novice", "btn_confirm_role", (980, 620, 120, 45))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["is_role_selection"] = False
    ctx.variables["role_created"] = True
    ctx.variables["in_world"] = True
    logger.info("Character role and sect creation confirmed.")


def find_novice_quest_tracker(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("has_novice_quest", True)


def click_novice_quest_tracker(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "novice", "btn_novice_track", (1120, 195, 120, 35))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["novice_quest_active"] = True
    ctx.variables["story_dialog_open"] = True


def is_story_dialog_open(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("story_dialog_open", True)


def click_skip_or_advance_dialog(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "novice", "btn_skip_dialog", (1180, 50, 60, 30))
    if ctx.device:
        ctx.device.click(cx, cy)
        time.sleep(0.1)
        cx2, cy2 = _get_coord_center(coords, "novice", "btn_dialog_next", (950, 480, 120, 40))
        ctx.device.click(cx2, cy2)
    ctx.variables["story_dialog_open"] = False
    # Check if this dialogue leads to combat or directly to reward
    if ctx.variables.get("leads_to_combat", True):
        ctx.variables["novice_in_battle"] = True
    else:
        ctx.variables["novice_reward_ready"] = True


def is_novice_battle_active(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("novice_in_battle", False)


def handle_novice_combat_actions(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "battle", "btn_auto_battle", (1120, 620, 60, 40))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["novice_battle_auto_engaged"] = True
    ctx.variables["novice_in_battle"] = False
    ctx.variables["novice_battle_ended"] = True
    logger.info("Engaged auto-battle for novice story combat.")


def is_novice_battle_ended(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("novice_battle_ended", True)


def increment_novice_progress(ctx: PipelineContext, act: NodeAction) -> None:
    ctx.variables["novice_step"] = ctx.variables.get("novice_step", 0) + 1
    ctx.variables["novice_battle_ended"] = False
    ctx.variables["novice_reward_ready"] = True
    logger.info(f"Novice basic quest step progress: [{ctx.variables['novice_step']}/3]")


def is_novice_reward_available(ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
    return ctx.variables.get("novice_reward_ready", True)


def click_claim_novice_reward(ctx: PipelineContext, act: NodeAction) -> None:
    coords = ctx.variables.get("coordinates", {})
    cx, cy = _get_coord_center(coords, "novice", "btn_claim_reward", (640, 480, 100, 40))
    if ctx.device:
        ctx.device.click(cx, cy)
    ctx.variables["novice_reward_ready"] = False
    ctx.variables["level"] = ctx.variables.get("level", 1) + 5
    logger.info(f"Claimed novice quest rewards. Character level up -> {ctx.variables['level']}")


def finish_novice_tasks(ctx: PipelineContext, act: NodeAction) -> None:
    ctx.variables["basic_tasks_completed"] = True
    logger.info("Novice basic tasks pipeline successfully finished.")

    ctx.variables["shanghui_open"] = False
    ctx.variables["shanghui_cleared"] = True
