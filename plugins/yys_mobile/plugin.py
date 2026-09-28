"""
Onmyoji (yys_mobile) Game Plugin Implementation.
Demonstrates cross-game generic plugin capabilities without touching core engine code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from loguru import logger

from core.cv.battle import BattleDetector
from core.device.base import BaseDevice
from core.ocr.engine import OCREngine
from plugins.base import BaseGamePlugin
from plugins.yys_mobile.custom import handlers as h
from scheduler.dag import PipelineContext


class YYSMobilePlugin(BaseGamePlugin):
    """Business plugin for Onmyoji (yys_mobile)."""

    def __init__(self, device: BaseDevice, plugin_dir: Optional[Path] = None) -> None:
        actual_dir = plugin_dir or Path(__file__).parent
        self.battle_detector = BattleDetector()
        self.ocr_engine = OCREngine.get_instance()
        super().__init__(plugin_dir=actual_dir, device=device)

    def register_custom_operators(self, context: PipelineContext) -> None:
        """Register domain-specific recognition and action handlers."""
        # Share coordinates in context
        context.variables["coordinates"] = self.coordinates

        # 1. Yuhun (Soul 10/11) Handlers
        context.register_recognition("is_yuhun_lobby_ready", h.is_yuhun_lobby_ready)
        context.register_action("click_challenge", h.click_challenge)
        context.register_recognition("is_yuhun_battle_settlement", h.is_yuhun_battle_settlement)
        context.register_action("click_settlement_dismiss", h.click_settlement_dismiss)
        context.register_action("increment_yuhun_round", h.increment_yuhun_round)

        # 2. Jiejie (Realm Raid) Handlers
        context.register_recognition("has_raid_tickets", h.has_raid_tickets)
        context.register_action("select_raid_target", h.select_raid_target)
        context.register_recognition("is_raid_attack_button_visible", h.is_raid_attack_button_visible)
        context.register_action("click_raid_attack", h.click_raid_attack)

        # 3. Global Anti-Bot / Bounty Interceptor Handlers
        context.register_recognition("detect_bounty_invite", h.detect_bounty_invite)
        context.register_action("resolve_bounty_invite", h.resolve_bounty_invite)

        logger.info(f"Registered all domain custom operators for {self.plugin_id}")

    def on_pipeline_completed(self, pipeline_name: str, account_id: Optional[str] = None) -> None:
        """Record Onmyoji-specific rewards (coins, medals)."""
        if not account_id:
            return
        try:
            from cluster.account import AccountMatrix
            matrix = AccountMatrix.get_instance()
            matrix.record_income(
                account_id=account_id,
                gold=1500,
                silver=0,
                active_points=15,
            )
        except Exception as ex:
            logger.debug(f"Failed to record yys pipeline income: {ex}")

    def on_routine_completed(self, routine_name: str, account_id: Optional[str] = None) -> None:
        """Record Onmyoji-specific routine rewards."""
        if not account_id:
            return
        try:
            from cluster.account import AccountMatrix
            matrix = AccountMatrix.get_instance()
            matrix.record_income(
                account_id=account_id,
                gold=6000,
                silver=0,
                active_points=60,
            )
        except Exception as ex:
            logger.debug(f"Failed to record yys routine income: {ex}")
