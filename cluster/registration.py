"""
Account Registration Manager & 5-Player Team Provisioning Engine.
Automates 5-account registration, NetEase/MPay UI onboarding flows,
and registers accounts into AccountMatrix with 1 Leader + 4 Members topology.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from cluster.account import AccountConfig, AccountMatrix, AccountStatus
from core.device.base import BaseDevice
from core.ocr.engine import OCREngine


STANDARD_5PLAYER_SPECS: List[Dict[str, Any]] = [
    {
        "account_id": "acc_team01_01_leader",
        "username": "mhxy_lead_hs01@163.com",
        "role_name": "剑侠客_大队长",
        "sect": "化生寺",
        "team_role_preference": "leader",
        "level": 1,
    },
    {
        "account_id": "acc_team01_02_member",
        "username": "mhxy_memb_pt02@163.com",
        "role_name": "玄彩娥_普陀",
        "sect": "普陀山",
        "team_role_preference": "member",
        "level": 1,
    },
    {
        "account_id": "acc_team01_03_member",
        "username": "mhxy_memb_df03@163.com",
        "role_name": "骨精灵_地府",
        "sect": "阴曹地府",
        "team_role_preference": "member",
        "level": 1,
    },
    {
        "account_id": "acc_team01_04_member",
        "username": "mhxy_memb_lg04@163.com",
        "role_name": "龙太子_龙宫",
        "sect": "龙宫",
        "team_role_preference": "member",
        "level": 1,
    },
    {
        "account_id": "acc_team01_05_member",
        "username": "mhxy_memb_st05@163.com",
        "role_name": "虎头怪_狮驼",
        "sect": "狮驼岭",
        "team_role_preference": "member",
        "level": 1,
    },
]


class AccountRegistrationManager:
    """Manages batch registration, device UI onboarding, and team provisioning."""

    def __init__(
        self,
        matrix: Optional[AccountMatrix] = None,
        ocr_engine: Optional[OCREngine] = None,
    ) -> None:
        self.matrix = matrix or AccountMatrix.get_instance()
        self.ocr_engine = ocr_engine or OCREngine.get_instance()

    def generate_5player_team(
        self,
        server_name: str = "东海湾",
        password: str = "Mhxy2026Auto!",
        team_prefix: str = "team01",
    ) -> List[AccountConfig]:
        """Generate 5 standard account configurations for a 1 Leader + 4 Members team."""
        accounts: List[AccountConfig] = []
        for i, spec in enumerate(STANDARD_5PLAYER_SPECS, start=1):
            account_id = f"acc_{team_prefix}_{i:02d}_{spec['team_role_preference']}"
            username = f"mhxy_{team_prefix}_{spec['sect']}_{i:02d}@163.com"
            cfg = AccountConfig(
                account_id=account_id,
                username=username,
                password=password,
                server_name=server_name,
                role_name=spec["role_name"],
                sect=spec["sect"],
                team_role_preference=spec["team_role_preference"],
                level=spec.get("level", 1),
                status=AccountStatus.IDLE,
                gold_coins=0,
                silver_coins=0,
                vitality=500,
                daily_active_points=0,
            )
            accounts.append(cfg)
        return accounts

    def register_and_save_team(
        self,
        accounts: Optional[List[AccountConfig]] = None,
        config_path: str = "config/accounts.json",
        server_name: str = "东海湾",
    ) -> List[AccountConfig]:
        """Register team accounts into AccountMatrix and save to config/accounts.json."""
        team = accounts or self.generate_5player_team(server_name=server_name)
        self.matrix.batch_register(team)
        self.matrix.save_to_json(config_path)
        logger.info(
            f"Successfully registered and saved {len(team)} team accounts to {config_path}."
        )
        return team

    def automate_device_registration(
        self,
        device: BaseDevice,
        account: AccountConfig,
        max_steps: int = 12,
    ) -> Dict[str, Any]:
        """
        Execute automated UI interaction on device (real ADB or virtual)
        to complete NetEase login, registration, and initial server entry.
        """
        logger.info(
            f"Starting device registration flow for account [{account.account_id}] ({account.username}) on device [{device.name}]."
        )
        steps_log: List[str] = []

        if not device.is_connected():
            device.connect()

        # If device is virtual or mock mode, execute fast synthetic flow
        from core.device.virtual import VirtualDevice
        is_virtual = (
            isinstance(device, VirtualDevice)
            or getattr(device, "platform_type", "") == "virtual"
            or getattr(device, "device_type", "") == "virtual"
            or self.ocr_engine.is_mock
        )
        if is_virtual:
            steps_log.append("virtual_env: accepted_user_agreement")
            steps_log.append("virtual_env: selected_email_login_mode")
            steps_log.append(f"virtual_env: filled_credentials_{account.username}")
            steps_log.append("virtual_env: submitted_registration_form")
            steps_log.append(f"virtual_env: selected_server_{account.server_name}")
            return {
                "status": "success",
                "mode": "synthetic",
                "account_id": account.account_id,
                "server_name": account.server_name,
                "role_name": account.role_name,
                "steps": steps_log,
            }

        # Real Device Live ADB Vision Interaction
        for step in range(max_steps):
            frame = device.screencap()
            ocr_items = self.ocr_engine.recognize(frame)
            text_map = {item.text: item for item in ocr_items}

            # 1. Check for Initial Terms & Conditions modal dialog
            accept_btn = None
            for t, it in text_map.items():
                if "接受" in t or "同意" in t:
                    accept_btn = it
                    break
            if accept_btn and any("用户协议" in t for t in text_map):
                cx, cy = accept_btn.center
                device.click(cx, cy)
                steps_log.append(f"step_{step}: clicked_accept_agreement at ({cx},{cy})")
                time.sleep(1.5)
                continue

            # 2. Check for resource downloading prompt ("确定")
            confirm_btn = text_map.get("确定")
            if confirm_btn and any("资源文件" in t or "下载" in t for t in text_map):
                cx, cy = confirm_btn.center
                device.click(cx, cy)
                steps_log.append(f"step_{step}: clicked_confirm_download at ({cx},{cy})")
                time.sleep(1.5)
                continue

            # 3. Check for Exit Dialog ("取消")
            cancel_btn = text_map.get("取消")
            if cancel_btn and any("退出游戏" in t for t in text_map):
                cx, cy = cancel_btn.center
                device.click(cx, cy)
                steps_log.append(f"step_{step}: clicked_cancel_exit at ({cx},{cy})")
                time.sleep(1.5)
                continue

            # 4. Check for Main "登录游戏" entry button
            login_btn = None
            for t, it in text_map.items():
                if "登录游戏" in t:
                    login_btn = it
                    break
            if login_btn and not any("网易邮箱" in t or "快速游戏" in t for t in text_map):
                cx, cy = login_btn.center
                device.click(cx, cy)
                steps_log.append(f"step_{step}: clicked_login_game at ({cx},{cy})")
                time.sleep(1.5)
                continue

            # 5. Check for NetEase MPay Login Dialog
            # 5a. Check TOS checkbox if present
            agree_checkbox = None
            for t, it in text_map.items():
                if "用户协议与隐私政策" in t or "我已详细阅读" in t:
                    agree_checkbox = it
                    break
            if agree_checkbox:
                # Checkbox is to the left of the text
                cb_x = max(20, agree_checkbox.bbox[0] - 30)
                cb_y = agree_checkbox.center[1]
                device.click(cb_x, cb_y)
                steps_log.append(f"step_{step}: clicked_tos_checkbox at ({cb_x},{cb_y})")
                time.sleep(0.5)

            # 5b. Choose "快速游戏" (Guest) or "网易邮箱"
            fast_btn = text_map.get("快速游戏")
            email_btn = None
            for t, it in text_map.items():
                if "网易邮箱" in t:
                    email_btn = it
                    break

            if fast_btn:
                cx, cy = fast_btn.center
                device.click(cx, cy)
                steps_log.append(f"step_{step}: clicked_quick_game at ({cx},{cy})")
                time.sleep(2.0)
                continue
            elif email_btn:
                cx, cy = email_btn.center
                device.click(cx, cy)
                steps_log.append(f"step_{step}: clicked_email_login at ({cx},{cy})")
                time.sleep(1.5)
                # Form filling
                device.input_text(account.username)
                device.key_event(66)  # Enter
                device.input_text(account.password)
                continue

            # 6. Check for Server / Character Enter
            enter_btn = None
            for t, it in text_map.items():
                if "进入游戏" in t or "开始游戏" in t:
                    enter_btn = it
                    break
            if enter_btn:
                cx, cy = enter_btn.center
                device.click(cx, cy)
                steps_log.append(f"step_{step}: clicked_enter_game at ({cx},{cy})")
                time.sleep(2.0)
                return {
                    "status": "success",
                    "mode": "live_adb",
                    "account_id": account.account_id,
                    "server_name": account.server_name,
                    "role_name": account.role_name,
                    "steps": steps_log,
                }

            time.sleep(1.0)

        return {
            "status": "partial",
            "mode": "live_adb",
            "account_id": account.account_id,
            "steps": steps_log,
        }
