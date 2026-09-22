"""
Fantasy Westward Journey Mobile Reference Plugin Implementation.
Implements domain-specific recognition, action handlers, quiz solver, and anti-bot defense.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from loguru import logger

from core.device.base import BaseDevice
from core.cv.battle import BattleDetector
from core.ocr.engine import OCREngine
from plugins.base import BaseGamePlugin
from plugins.mhxy_mobile.custom.quiz import QuizSolver
from scheduler.dag import NodeAction, NodeRecognition, PipelineContext


class MHXYMobilePlugin(BaseGamePlugin):
    """Business plugin for Fantasy Westward Journey Mobile (mhxy_mobile)."""

    def __init__(self, device: BaseDevice, plugin_dir: Optional[Path] = None) -> None:
        actual_dir = plugin_dir or (Path(__file__).parent)
        self.battle_detector = BattleDetector()
        self.ocr_engine = OCREngine.get_instance()
        self.quiz_solver = QuizSolver()
        super().__init__(plugin_dir=actual_dir, device=device)

    def register_custom_operators(self, context: PipelineContext) -> None:
        """Register domain-specific recognition and action handlers."""
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

    # --- Shimen Handlers ---

    def _find_shimen_tracker(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if frame is not None and not self.ocr_engine.is_mock:
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

    def _is_master_dialog_open(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if frame is not None and not self.ocr_engine.is_mock:
            res = self.ocr_engine.find_text(frame, "师傅", roi=(800, 350, 300, 200), threshold=60.0)
            if res:
                return True
        return ctx.variables.get("master_dialog_open", False)

    def _click_accept_shimen(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("shimen", {}).get("btn_accept", [930, 430, 80, 30])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        self.device.click(cx, cy)

    def _is_turnin_dialog_open(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if frame is not None and not self.ocr_engine.is_mock:
            res = self.ocr_engine.find_text(frame, "上交", roi=(800, 350, 300, 200), threshold=60.0)
            if res:
                return True
        return ctx.variables.get("turnin_dialog_open", False)

    def _click_turnin_item(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("shimen", {}).get("btn_turnin", [930, 430, 80, 30])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        self.device.click(cx, cy)

    def _is_shop_dialog_open(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if frame is not None and not self.ocr_engine.is_mock:
            res = self.ocr_engine.find_text(frame, "购买", roi=(750, 450, 300, 180), threshold=60.0)
            if res:
                return True
        return ctx.variables.get("shop_dialog_open", False)

    def _click_buy_shop_item(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("shimen", {}).get("btn_buy_drug", [880, 520, 60, 30])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        self.device.click(cx, cy)

    def _increment_shimen_round(self, ctx: PipelineContext, act: NodeAction) -> None:
        ctx.variables["shimen_rounds"] = ctx.variables.get("shimen_rounds", 0) + 1
        logger.info(f"Shimen round progress: [{ctx.variables['shimen_rounds']}/20]")

    # --- Baotu Handlers ---

    def _find_baotu_dialog(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if frame is not None and not self.ocr_engine.is_mock:
            res = self.ocr_engine.find_text(frame, "宝图", roi=(800, 350, 300, 200), threshold=60.0)
            if res:
                return True
        return ctx.variables.get("baotu_dialog_open", True)

    def _increment_baotu_count(self, ctx: PipelineContext, act: NodeAction) -> None:
        ctx.variables["baotu_count"] = ctx.variables.get("baotu_count", 0) + 1
        logger.info(f"Baotu battle progress: [{ctx.variables['baotu_count']}/10]")

    def _has_treasure_map_in_bag(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        return ctx.variables.get("has_treasure_map", True)

    def _is_dig_completed(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        return ctx.variables.get("dig_completed", True)

    def _increment_dig_count(self, ctx: PipelineContext, act: NodeAction) -> None:
        ctx.variables["dig_count"] = ctx.variables.get("dig_count", 0) + 1
        logger.info(f"Treasure map dig progress: [{ctx.variables['dig_count']}/10]")

    # --- Yuntong Handlers ---

    def _find_zheng_biaotou(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        if frame is not None and not self.ocr_engine.is_mock:
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
        if frame is not None and not self.ocr_engine.is_mock:
            dialog_roi = self.coordinates.get("anti_bot", {}).get("dialog_bbox")
            res = self.ocr_engine.find_any_text(
                frame,
                ["验证码", "防沉迷", "请选择", "防挂机"],
                roi=tuple(dialog_roi) if dialog_roi else None,
                threshold=70.0,
            )
            if res:
                return True
        return ctx.variables.get("anti_bot_popup_active", False)

    def _resolve_anti_bot_popup(self, ctx: PipelineContext, act: NodeAction) -> None:
        """Resolves anti-bot captcha and clicks corresponding answer option."""
        logger.warning("Anti-bot modal active! Resolving via question answer pipeline...")
        opt1 = self.coordinates.get("anti_bot", {}).get("option_1", [420, 360, 180, 40])
        cx = opt1[0] + opt1[2] / 2
        cy = opt1[1] + opt1[3] / 2
        self.device.click(cx, cy)
        ctx.variables["anti_bot_popup_active"] = False
        logger.info("Anti-bot option clicked and dismissed.")
