"""
Fantasy Westward Journey Mobile Reference Plugin Implementation.
Demonstrates custom operator registration, coordinate lookup, and anti-bot resolution.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any
from loguru import logger

from core.device.base import BaseDevice
from plugins.base import BaseGamePlugin
from scheduler.dag import NodeAction, NodeRecognition, PipelineContext


class MHXYMobilePlugin(BaseGamePlugin):
    """Business plugin for Fantasy Westward Journey Mobile (mhxy_mobile)."""

    def __init__(self, device: BaseDevice, plugin_dir: Optional[Path] = None) -> None:
        actual_dir = plugin_dir or (Path(__file__).parent)
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

        # 2. Anti-Bot Popup Handlers
        context.register_recognition("detect_anti_bot_popup", self._detect_anti_bot_popup)
        context.register_action("resolve_anti_bot_popup", self._resolve_anti_bot_popup)

    # --- Operator Implementations ---

    def _find_shimen_tracker(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        # Check if task tracker has shimen text or template
        return ctx.variables.get("has_shimen_quest", True)

    def _click_shimen_tracker(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("common", {}).get("btn_task_track_top", [1120, 195, 120, 35])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        logger.info(f"Clicking task tracker at ({cx}, {cy})")
        self.device.click(cx, cy)

    def _is_master_dialog_open(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        return ctx.variables.get("master_dialog_open", False)

    def _click_accept_shimen(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("shimen", {}).get("btn_accept", [930, 430, 80, 30])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        self.device.click(cx, cy)

    def _is_turnin_dialog_open(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        return ctx.variables.get("turnin_dialog_open", False)

    def _click_turnin_item(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("shimen", {}).get("btn_turnin", [930, 430, 80, 30])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        self.device.click(cx, cy)

    def _is_shop_dialog_open(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        return ctx.variables.get("shop_dialog_open", False)

    def _click_buy_shop_item(self, ctx: PipelineContext, act: NodeAction) -> None:
        coords = self.coordinates.get("shimen", {}).get("btn_buy_drug", [880, 520, 60, 30])
        cx = coords[0] + coords[2] / 2
        cy = coords[1] + coords[3] / 2
        self.device.click(cx, cy)

    def _detect_anti_bot_popup(self, ctx: PipelineContext, frame: Any, rec: NodeRecognition) -> bool:
        """Global interrupt: checks for anti-bot verification modal."""
        return ctx.variables.get("anti_bot_popup_active", False)

    def _resolve_anti_bot_popup(self, ctx: PipelineContext, act: NodeAction) -> None:
        """Resolves anti-bot captcha and clicks corresponding answer option."""
        logger.warning("Anti-bot modal active! Resolving via question answer pipeline...")
        # Simulated selection of option 1
        opt1 = self.coordinates.get("anti_bot", {}).get("option_1", [420, 360, 180, 40])
        cx = opt1[0] + opt1[2] / 2
        cy = opt1[1] + opt1[3] / 2
        self.device.click(cx, cy)
        ctx.variables["anti_bot_popup_active"] = False
        logger.info("Anti-bot option clicked and dismissed.")
