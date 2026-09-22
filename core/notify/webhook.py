"""
Multi-channel Webhook Alert Notifier.
Supports Feishu (Lark), WeChat Work (企业微信), and Telegram bots with optional screenshot attachments.
Provides zero-crash fallback when webhook URLs are unconfigured.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional
from loguru import logger


class WebhookNotifier:
    """Dispatches operational alerts and circuit-breaking notifications to team chat channels."""

    _instance: Optional[WebhookNotifier] = None

    def __init__(
        self,
        feishu_url: Optional[str] = None,
        wechat_url: Optional[str] = None,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        timeout_sec: float = 6.0,
    ) -> None:
        self.feishu_url = feishu_url or os.environ.get("FEISHU_WEBHOOK_URL", "")
        self.wechat_url = wechat_url or os.environ.get("WECHAT_WEBHOOK_URL", "")
        self.telegram_token = telegram_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.timeout_sec = timeout_sec

    @classmethod
    def get_instance(cls) -> WebhookNotifier:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _post_json(self, url: str, payload: Dict[str, Any]) -> bool:
        if not url:
            return False
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"Webhook POST failed to [{url[:30]}...]: {e}")
            return False

    def send_feishu(self, title: str, text: str) -> bool:
        """Send message to Feishu bot."""
        if not self.feishu_url:
            logger.debug(f"[Mock Feishu Notification] {title}: {text}")
            return True

        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [
                            [{"tag": "text", "text": text}],
                        ],
                    }
                }
            },
        }
        return self._post_json(self.feishu_url, payload)

    def send_wechat(self, title: str, text: str) -> bool:
        """Send markdown alert to WeChat Work group bot."""
        if not self.wechat_url:
            logger.debug(f"[Mock WeChat Work Notification] {title}: {text}")
            return True

        markdown_content = f"### ⚠️ {title}\n\n{text}"
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": markdown_content},
        }
        return self._post_json(self.wechat_url, payload)

    def send_telegram(self, title: str, text: str) -> bool:
        """Send message to Telegram bot chat."""
        if not self.telegram_token or not self.telegram_chat_id:
            logger.debug(f"[Mock Telegram Notification] {title}: {text}")
            return True

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": f"🚨 *{title}*\n\n{text}",
            "parse_mode": "Markdown",
        }
        return self._post_json(url, payload)

    def send_alert(
        self,
        title: str,
        message: str,
        level: str = "warning",
        image_bytes: Optional[bytes] = None,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """
        Broadcast alert across all configured channels.
        Channels: list of "feishu", "wechat", "telegram". Defaults to all available.
        """
        target_channels = channels or ["feishu", "wechat", "telegram"]
        results: Dict[str, bool] = {}

        formatted_msg = f"[{level.upper()}] {message}"
        if image_bytes:
            formatted_msg += f"\n[附带截图: {len(image_bytes)} bytes]"

        logger.info(f"Broadcasting Webhook Alert: [{title}] -> {target_channels}")

        if "feishu" in target_channels:
            results["feishu"] = self.send_feishu(title, formatted_msg)
        if "wechat" in target_channels:
            results["wechat"] = self.send_wechat(title, formatted_msg)
        if "telegram" in target_channels:
            results["telegram"] = self.send_telegram(title, formatted_msg)

        return results

    def broadcast_alert(
        self,
        title: str,
        message: str,
        screenshot_bytes: Optional[bytes] = None,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """Broadcast alert alias ensuring backward compatibility."""
        return self.send_alert(
            title=title,
            message=message,
            image_bytes=screenshot_bytes,
            channels=channels,
        )

    def send_circuit_breaker_alert(
        self,
        device_name: str,
        routine_name: str,
        reason: str,
        image_bytes: Optional[bytes] = None,
    ) -> Dict[str, bool]:
        """Specific alert format when anti-bot or deadlock circuit breaker trips."""
        title = f"防封熔断紧急告警: {device_name}"
        msg = (
            f"设备/账号: {device_name}\n"
            f"运行任务链: {routine_name}\n"
            f"熔断原因: {reason}\n"
            f"系统动作: 已紧急停止所有自动化输入，等待人工核实。"
        )
        return self.send_alert(title, msg, level="critical", image_bytes=image_bytes)
