"""
Fantasy Westward Journey Mobile Reference Plugin Implementation.
Implements domain-specific recognition, action handlers, quiz solver, and anti-bot defense.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional
from loguru import logger

from core.device.base import BaseDevice
from core.cv.battle import BattleDetector
from core.ocr.engine import OCREngine
from core.vlm import LiveVLMDefenseSolver
from plugins.base import BaseGamePlugin
from plugins.mhxy_mobile.custom.quiz_solver import QuizSolver
from plugins.mhxy_mobile.custom import handlers as h
from plugins.mhxy_mobile.custom import daily_handlers as dh
from scheduler.dag import NodeAction, NodeRecognition, PipelineContext


class MHXYMobilePlugin(BaseGamePlugin):
    """Business plugin for Fantasy Westward Journey Mobile (mhxy_mobile)."""

    def __init__(self, device: BaseDevice, plugin_dir: Optional[Path] = None) -> None:
        actual_dir = plugin_dir or (Path(__file__).parent)
        self.battle_detector = BattleDetector()
        self.ocr_engine = OCREngine.get_instance()
        self.quiz_solver = QuizSolver()
        self.vlm_defense_solver = LiveVLMDefenseSolver(device=device)
        super().__init__(plugin_dir=actual_dir, device=device)

    def register_custom_operators(self, context: PipelineContext) -> None:
        """Register domain-specific recognition and action handlers."""
        # Share coordinates in context
        context.variables["coordinates"] = self.coordinates

        # 1. Shimen Quest Handlers
        context.register_recognition("find_shimen_tracker", self._find_shimen_tracker)
        context.register_action("click_shimen_tracker", self._click_shimen_tracker)
        context.register_recognition("is_master_dialog_open", self._is_master_dialog_open)
        context.register_action("click_accept_shimen", self._click_accept_shimen)
        context.register_recognition("is_turnin_dialog_open", self._is_turnin_dialog_open)
        context.register_action("click_turnin_item", self._click_turnin_item)
        context.register_recognition("is_shop_dialog_open", self._is_shop_dialog_open)
        context.register_action("click_buy_shop_item", self._click_buy_shop_item)
        context.register_action("increment_shimen_round", self._increment_shimen_round)

        # 2. Baotu Handlers
        context.register_recognition("find_baotu_dialog", self._find_baotu_dialog)
        context.register_action("increment_baotu_count", self._increment_baotu_count)
        context.register_recognition("has_treasure_map_in_bag", self._has_treasure_map_in_bag)
        context.register_recognition("probe_map_in_bag", self._probe_map_in_bag)
        context.register_recognition("is_dig_completed", self._is_dig_completed)
        context.register_action("increment_dig_count", self._increment_dig_count)

        # 3. Yuntong Handlers
        context.register_recognition("find_zheng_biaotou", self._find_zheng_biaotou)
        context.register_recognition("is_escort_destination_reached", self._is_escort_destination_reached)
        context.register_action("increment_yuntong_count", self._increment_yuntong_count)

        # 4. Common Combat & Status Handlers
        context.register_recognition("is_battle_ended", self._is_battle_ended)

        # 5. Anti-Bot Popup Handlers
        context.register_recognition("detect_anti_bot_popup", self._detect_anti_bot_popup)
        context.register_action("resolve_anti_bot_popup", self._resolve_anti_bot_popup)

        # 6. Team Ghost Hunting (team_zhuogui) Handlers
        context.register_recognition("is_team_panel_open", h.is_team_panel_open)
        context.register_action("click_open_team", h.click_open_team)
        context.register_action("click_create_team", h.click_create_team)
        context.register_recognition("is_team_full", h.is_team_full)
        context.register_action("click_auto_match", h.click_auto_match)
        context.register_recognition("find_zhongkui", h.find_zhongkui)
        context.register_action("click_talk_zhongkui", h.click_talk_zhongkui)
        context.register_recognition("is_zhongkui_dialog_open", h.is_zhongkui_dialog_open)
        context.register_action("click_accept_ghost", h.click_accept_ghost)
        context.register_recognition("check_double_points", h.check_double_points)
        context.register_action("click_fetch_double", h.click_fetch_double)
        context.register_recognition("is_ghost_tracking", h.is_ghost_tracking)
        context.register_action("click_ghost_tracker", h.click_ghost_tracker)
        context.register_recognition("is_ghost_in_battle", h.is_ghost_in_battle)
        context.register_action("handle_ghost_combat", h.handle_ghost_combat)
        context.register_recognition("is_ghost_battle_ended", h.is_ghost_battle_ended)
        context.register_action("increment_ghost_round", h.increment_ghost_round)
        context.register_action("apply_join_ghost_team", h.apply_join_ghost_team)
        context.register_recognition("is_following_leader", h.is_following_leader)

        # 7. Dungeons (fuben_320_520) Handlers
        context.register_recognition("is_activity_open", h.is_activity_open)
        context.register_action("click_open_activity", h.click_open_activity)
        context.register_recognition("find_fuben_entry", h.find_fuben_entry)
        context.register_action("click_enter_fuben", h.click_enter_fuben)
        context.register_recognition("is_fuben_dialog_active", h.is_fuben_dialog_active)
        context.register_action("click_skip_fuben_dialog", h.click_skip_fuben_dialog)
        context.register_recognition("is_fuben_in_battle", h.is_fuben_in_battle)
        context.register_action("handle_fuben_combat", h.handle_fuben_combat)
        context.register_recognition("is_fuben_battle_ended", h.is_fuben_battle_ended)
        context.register_action("advance_fuben_stage", h.advance_fuben_stage)
        context.register_recognition("is_fuben_settlement_ready", h.is_fuben_settlement_ready)
        context.register_action("click_fuben_settlement", h.click_fuben_settlement)

        # 8. Workshop Archaeology (gongfang_kaogu) Handlers
        context.register_recognition("needs_shovels", h.needs_shovels)
        context.register_action("click_buy_shovels", h.click_buy_shovels)
        context.register_recognition("has_shovels", h.has_shovels)
        context.register_action("click_use_shovel", h.click_use_shovel)
        context.register_recognition("is_tomb_reached", h.is_tomb_reached)
        context.register_action("trigger_compass_dig", h.trigger_compass_dig)
        context.register_recognition("is_thief_battle_active", h.is_thief_battle_active)
        context.register_action("click_appraise_and_sell", h.click_appraise_and_sell)

        # 9. Vigor & Chamber of Commerce (huoli_shanghui) Handlers
        context.register_recognition("check_huoli_sufficient", h.check_huoli_sufficient)
        context.register_action("execute_huoli_work", h.execute_huoli_work)
        context.register_action("click_open_shanghui", h.click_open_shanghui)
        context.register_recognition("has_items_to_sell", h.has_items_to_sell)
        context.register_action("click_batch_sell", h.click_batch_sell)

        # 10. Novice & Basic Story (basic_tasks) Handlers
        context.register_action("click_enter_game_world", h.click_enter_game_world)
        context.register_recognition("is_role_selection_screen", h.is_role_selection_screen)
        context.register_action("click_confirm_role_and_sect", h.click_confirm_role_and_sect)
        context.register_recognition("find_novice_quest_tracker", h.find_novice_quest_tracker)
        context.register_action("click_novice_quest_tracker", h.click_novice_quest_tracker)
        context.register_recognition("is_story_dialog_open", h.is_story_dialog_open)
        context.register_action("click_skip_or_advance_dialog", h.click_skip_or_advance_dialog)
        context.register_recognition("is_novice_battle_active", h.is_novice_battle_active)
        context.register_action("handle_novice_combat_actions", h.handle_novice_combat_actions)
        context.register_recognition("is_novice_battle_ended", h.is_novice_battle_ended)
        context.register_action("increment_novice_progress", h.increment_novice_progress)
        context.register_recognition("is_novice_reward_available", h.is_novice_reward_available)
        context.register_action("click_claim_novice_reward", h.click_claim_novice_reward)
        context.register_action("finish_novice_tasks", h.finish_novice_tasks)

        # 11. Autonomous Multi-Task Daily DAG (daily_dailies) Handlers
        context.register_recognition("classify_screen", dh.classify_screen)
        context.register_recognition("always_true", dh.always_true)
        context.register_action("noop_wait", dh.noop_wait)
        context.register_action("do_battle_step", dh.do_battle_step)
        context.register_action("dismiss_popups", dh.dismiss_popups)
        context.register_action("open_activity_panel", dh.open_activity_panel)
        context.register_action("handle_activity_panel", dh.handle_activity_panel)
        context.register_action("click_shimen_board", dh.click_shimen_board)
        context.register_action("click_shop_buy", dh.click_shop_buy)
        context.register_action("click_turnin", dh.click_turnin)
        context.register_action("click_use_item", dh.click_use_item)
        context.register_action("click_deposit_confirm", dh.click_deposit_confirm)
        context.register_action("click_dialog_choice", dh.click_dialog_choice)
        context.register_action("handle_quiz", dh.handle_quiz)
        context.register_action("click_task_tracker", dh.click_task_tracker)
        context.register_action("wait_walking", dh.wait_walking)
        context.register_action("close_panel_and_finish", dh.close_panel_and_finish)
        # Dig-time treasure-map acquisition (bugfix 2026-09-29): maps are bought one
        # at a time, at the moment of digging, never stockpiled.
        context.register_recognition("needs_treasure_map", dh.needs_treasure_map)
        context.register_action("buy_treasure_map", dh.buy_treasure_map)
        # Dedicated bag cleanup (清理背包, user request 2026-10-03): whitelist-driven
        # sell of junk when the game latches 背包空间不足. Empty whitelist = scan-only.
        from plugins.mhxy_mobile.custom import bag_cleaner as bc
        context.register_recognition("needs_bag_clean", bc.needs_bag_clean)
        context.register_action("run_bag_clean_pass", bc.run_bag_clean_pass)

    # --- Shimen Handlers ---

    def _find_shimen_tracker(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if getattr(self.device, "platform_type", "") != "virtual" and frame is not None and not self.ocr_engine.is_mock:
            roi = self.coordinates.get("common", {}).get("btn_task_track_top")
            res = self.ocr_engine.find_text(frame, "师门", roi=tuple(roi) if roi else None, threshold=60.0)
            if res:
                return True
        return ctx.variables.get("has_shimen_quest", True)

    def _click_shimen_tracker(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("common", {}).get("btn_task_track_top", [1120, 195, 120, 35])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        self.device.click(cx, cy)
        ctx.variables["master_dialog_open"] = True

    def _is_master_dialog_open(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if getattr(self.device, "platform_type", "") != "virtual" and frame is not None and not self.ocr_engine.is_mock:
            res = self.ocr_engine.find_text(frame, "师傅", roi=(800, 350, 300, 200), threshold=60.0)
            if res:
                return True
        return ctx.variables.get("master_dialog_open", True)

    def _click_accept_shimen(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("shimen", {}).get("btn_accept", [930, 430, 80, 30])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        self.device.click(cx, cy)
        ctx.variables["master_dialog_open"] = False
        ctx.variables["shimen_rounds"] = ctx.variables.get("shimen_rounds", 0) + 1
        logger.info(f"Shimen round progress: [{ctx.variables['shimen_rounds']}/20]")

    def _is_turnin_dialog_open(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if getattr(self.device, "platform_type", "") != "virtual" and frame is not None and not self.ocr_engine.is_mock:
            res = self.ocr_engine.find_text(frame, "上交", roi=(800, 350, 300, 200), threshold=60.0)
            if res:
                return True
        return ctx.variables.get("turnin_dialog_open", True)

    def _click_turnin_item(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("shimen", {}).get("btn_turnin", [930, 430, 80, 30])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        self.device.click(cx, cy)
        ctx.variables["turnin_dialog_open"] = False
        ctx.variables["shimen_rounds"] = ctx.variables.get("shimen_rounds", 0) + 1
        logger.info(f"Shimen round progress: [{ctx.variables['shimen_rounds']}/20]")

    def _is_shop_dialog_open(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if getattr(self.device, "platform_type", "") != "virtual" and frame is not None and not self.ocr_engine.is_mock:
            res = self.ocr_engine.find_text(frame, "购买", roi=(750, 450, 300, 180), threshold=60.0)
            if res:
                return True
        return ctx.variables.get("shop_dialog_open", True)

    def _click_buy_shop_item(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("shimen", {}).get("btn_buy_drug", [880, 520, 60, 30])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        self.device.click(cx, cy)
        ctx.variables["shop_dialog_open"] = False
        ctx.variables["shimen_rounds"] = ctx.variables.get("shimen_rounds", 0) + 1
        logger.info(f"Shimen round progress: [{ctx.variables['shimen_rounds']}/20]")

    def _increment_shimen_round(self, ctx: PipelineContext, act: NodeAction) -> None:
        ctx.variables["shimen_rounds"] = ctx.variables.get("shimen_rounds", 0) + 1
        logger.info(f"Shimen round progress: [{ctx.variables['shimen_rounds']}/20]")

    # --- Baotu Handlers ---

    def _find_baotu_dialog(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if getattr(self.device, "platform_type", "") != "virtual" and frame is not None and not self.ocr_engine.is_mock:
            res = self.ocr_engine.find_text(frame, "宝图", roi=(800, 350, 300, 200), threshold=60.0)
            if res:
                return True
        return ctx.variables.get("baotu_dialog_open", True)

    def _increment_baotu_count(self, ctx: PipelineContext, act: NodeAction) -> None:
        ctx.variables["baotu_count"] = ctx.variables.get("baotu_count", 0) + 1
        logger.info(f"Baotu battle progress: [{ctx.variables['baotu_count']}/10]")

    def _has_treasure_map_in_bag(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        # Live: read the bag grid for a 藏宝图 row. On virtual devices (tests / demo)
        # fall back to the variable so the dig flow stays deterministic.
        if getattr(self.device, "platform_type", "") != "virtual" and frame is not None and not self.ocr_engine.is_mock:
            roi = self.coordinates.get("baotu", {}).get("bag_roi")
            res = self.ocr_engine.find_text(frame, "藏宝图", roi=tuple(roi) if roi else None, threshold=60.0)
            if res:
                ctx.variables["has_treasure_map"] = True
                return True
            # No map row read in the bag: the dig phase must buy one at dig time.
            ctx.variables["has_treasure_map"] = False
            return False
        verdict = ctx.variables.get("has_treasure_map", True)
        ctx.variables["has_treasure_map"] = verdict
        return verdict

    def _probe_map_in_bag(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        """Gate recognizer for the dig loop: refresh the bag-map state, then branch.

        The DAG can only branch on variables (not on a recognizer result), and a
        False recognition would stall the node. So this probe runs the same bag
        read as ``_has_treasure_map_in_bag`` (which stores its verdict in
        ``has_treasure_map``), but always returns True to let the branches run:
        map present -> dig it; absent -> buy exactly one at dig time.
        """
        self._has_treasure_map_in_bag(ctx, frame, rec)
        return True

    def _is_dig_completed(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        return ctx.variables.get("dig_completed", True)

    def _increment_dig_count(self, ctx: PipelineContext, act: NodeAction) -> None:
        ctx.variables["dig_count"] = ctx.variables.get("dig_count", 0) + 1
        # Each dig consumes one map, so grant a fresh one-map purchase budget and a
        # fresh no-shop attempt budget for the next dig. Deliberately do NOT clear
        # ``has_treasure_map`` here: the dig loop re-probes the bag right after this
        # node and only buys when the bag is genuinely empty. Forcing it False here
        # made every dig buy a map even when thief loot had already filled the bag
        # (review 2026-09-29: stray 购买 click per dig).
        ctx.variables["treasure_map_buys_this_dig"] = 0
        ctx.variables["treasure_map_buy_attempts"] = 0
        logger.info(f"Treasure map dig progress: [{ctx.variables['dig_count']}/10]")

    # --- Yuntong Handlers ---

    def _find_zheng_biaotou(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if getattr(self.device, "platform_type", "") != "virtual" and frame is not None and not self.ocr_engine.is_mock:
            res = self.ocr_engine.find_text(frame, "押镖", roi=(800, 350, 300, 200), threshold=60.0)
            if res:
                return True
        return ctx.variables.get("zheng_dialog_open", True)

    def _is_escort_destination_reached(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        return ctx.variables.get("escort_reached", True)

    def _increment_yuntong_count(self, ctx: PipelineContext, act: NodeAction) -> None:
        ctx.variables["yuntong_completed"] = ctx.variables.get("yuntong_completed", 0) + 1
        logger.info(f"Yuntong escort progress: [{ctx.variables['yuntong_completed']}/3]")

    # --- Combat & Global Handlers ---

    def _is_battle_ended(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if frame is not None:
            if not self.battle_detector.is_in_battle(frame):
                return True
        return ctx.variables.get("battle_ended", True)

    def _detect_anti_bot_popup(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        """Global interrupt: checks for anti-bot verification modal."""
        if ctx.variables.get("anti_bot_popup_active", False):
            return True
        if getattr(self.device, "platform_type", "") == "virtual":
            return False

        # Rate limit OCR checking for interrupts to at most once per 2 seconds
        now = time.time()
        last_check = ctx.variables.get("_last_antibot_ocr_time", 0.0)
        if now - last_check < 2.0:
            return False
        ctx.variables["_last_antibot_ocr_time"] = now

        if frame is not None and not self.ocr_engine.is_mock:
            dialog_roi = self.coordinates.get("anti_bot", {}).get("dialog_bbox")
            res = self.ocr_engine.find_any_text(
                frame,
                ["验证码", "防沉迷", "请选择", "防挂机", "滑块", "拼图", "拖动", "依次点击"],
                roi=tuple(dialog_roi) if dialog_roi else None,
                threshold=70.0,
            )
            if res:
                ctx.variables["anti_bot_prompt_text"] = res.text
                return True
        return False

    def _resolve_anti_bot_popup(self, ctx: PipelineContext, act: NodeAction) -> None:
        """Resolves anti-bot captcha and clicks corresponding answer option."""
        prompt_text = ctx.variables.get("anti_bot_prompt_text", "")
        logger.warning(f"Anti-bot modal active! Resolving via LiveVLMDefenseSolver with prompt: '{prompt_text}'...")
        frame = self.device.screencap_mat()
        slider_hint = self.coordinates.get("anti_bot", {}).get("slider_start_hint")
        success = self.vlm_defense_solver.auto_solve_challenge(
            frame=frame,
            detected_text=prompt_text,
            slider_start_hint=tuple(slider_hint) if slider_hint else None,
        )
        if not success:
            logger.warning("VLM solver reported failure, executing fallback click")
            opt1 = self.coordinates.get("anti_bot", {}).get("option_1", [420, 360, 180, 40])
            cx = opt1[0] + opt1[2] / 2
            cy = opt1[1] + opt1[3] / 2
            self.device.click(cx, cy)
        ctx.variables["anti_bot_popup_active"] = False
        ctx.variables["anti_bot_prompt_text"] = ""
        logger.info("Anti-bot verification handled and dismissed.")

    def on_pipeline_started(self, pipeline_name: str, account_id: Optional[str] = None) -> None:
        """Reset cross-pipeline runtime state on every (re)start.

        The shared PluginContext persists across pipelines inside a routine, so
        ``_last_frame_items`` / ``_last_frame`` populated by a previous pipeline's
        sense node (classify_screen) would leak into the next pipeline. Handlers
        like buy_treasure_map must never act on a stale cached frame of a
        different screen, and a retried dig loop must not inherit exhausted
        purchase budgets from the failed run (routine.py keeps ctx.variables
        across retries on purpose).
        """
        self.context.variables.pop("_last_frame_items", None)
        self.context.variables.pop("_last_frame", None)
        if pipeline_name == "daily_baotu":
            v = self.context.variables
            v["treasure_map_buy_attempts"] = 0
            v["treasure_map_buys_this_dig"] = 0

    def on_pipeline_completed(self, pipeline_name: str, account_id: Optional[str] = None) -> None:
        """Record MHXY-specific pipeline completion rewards."""
        if not account_id:
            return
        try:
            from cluster.account import AccountMatrix
            matrix = AccountMatrix.get_instance()
            matrix.record_income(
                account_id=account_id,
                gold=2200,
                silver=180000,
                active_points=20,
            )
        except Exception as ex:
            logger.debug(f"Failed to record mhxy pipeline income: {ex}")

    def on_routine_completed(self, routine_name: str, account_id: Optional[str] = None) -> None:
        """Record MHXY-specific routine completion rewards."""
        if not account_id:
            return
        try:
            from cluster.account import AccountMatrix
            matrix = AccountMatrix.get_instance()
            matrix.record_income(
                account_id=account_id,
                gold=9000,
                silver=700000,
                active_points=80,
            )
        except Exception as ex:
            logger.debug(f"Failed to record mhxy routine income: {ex}")
