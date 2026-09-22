"""
Live Vision Language Model (VLM) Anti-Bot Solver & Humanized Execution Engine.
Orchestrates VLM perceptual inference (slider gap, sequential character click, multi-choice)
with humanized Bézier dragging, Gaussian offset clicks, and webhook alerting.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from loguru import logger

from core.device.base import BaseDevice
from core.notify.webhook import WebhookNotifier
from core.vlm.client import VLMClient


class LiveVLMDefenseSolver:
    """
    Automated multi-modal anti-bot challenge solver.
    Intercepts verification dialogs, submits screenshots to the VLM engine,
    and drives humanized Bezier / Gaussian input motions to pass the verification.
    """

    def __init__(
        self,
        device: BaseDevice,
        vlm_client: Optional[VLMClient] = None,
        notifier: Optional[WebhookNotifier] = None,
    ) -> None:
        self.device = device
        self.vlm = vlm_client or VLMClient.get_instance()
        self.notifier = notifier or WebhookNotifier.get_instance()

    @property
    def controller(self):
        return self.device.controller

    def solve_slider_puzzle(
        self,
        frame: Optional[np.ndarray] = None,
        slider_start_hint: Optional[Tuple[int, int]] = None,
        prompt_text: str = "拖动下方滑块完成拼图",
    ) -> bool:
        """
        Solve a sliding puzzle CAPTCHA end-to-end:
        1. Capture current device frame if not provided.
        2. Query VLM to detect slider thumb (start) and background gap (target).
        3. Drive humanized Bezier swipe with start acceleration, cruising, and fine deceleration.
        4. Broadcast alert via webhook if failed.
        """
        if frame is None:
            frame = self.device.screencap_mat()
        if frame is None:
            logger.error("Failed to capture frame for slider puzzle solving")
            return False

        logger.info(f"Submitting frame to VLM for slider puzzle analysis: '{prompt_text}'")
        res = self.vlm.solve_slider_captcha(frame, prompt_text=prompt_text)
        sx = res.get("slider_x", 420)
        sy = res.get("slider_y", 530)
        gx = res.get("gap_x", 710)
        gy = res.get("gap_y", 380)
        distance = res.get("distance", gx - sx)
        confidence = res.get("confidence", 0.0)

        if slider_start_hint:
            sx, sy = slider_start_hint

        logger.info(
            f"VLM Slider result: start=({sx}, {sy}), gap=({gx}, {gy}), distance={distance}px, conf={confidence:.2f}"
        )

        if distance <= 0:
            logger.warning(f"Calculated slider distance is invalid ({distance} <= 0)")
            self.notifier.send_alert(
                title="⚠️ 滑块拼图防挂机识别异常",
                message=f"设备 {self.device.name} 识别滑块滑动距离为 {distance}px，置信度 {confidence:.2f}，触发安全告警",
            )
            return False

        # Destination coordinates: start X + distance, keep Y roughly along the slider bar
        target_x = sx + distance
        target_y = sy

        logger.info(f"Executing humanized Bezier slider drag from ({sx}, {sy}) to ({target_x}, {target_y})...")
        # Humanized drag: 35 steps for realistic physics timing
        points = self.controller.human_swipe(sx, sy, target_x, target_y, steps=35)
        time.sleep(0.6)  # Wait for backend server verification animation

        logger.info(f"Slider drag completed ({len(points)} trajectory points).")
        return True

    def solve_sequential_text_click(
        self,
        frame: Optional[np.ndarray] = None,
        prompt_text: str = "请按顺序依次点击文字",
    ) -> bool:
        """
        Solve sequential click CAPTCHA:
        1. Query VLM to identify target sequence order and coordinates.
        2. Click each target in sequence with Gaussian offset and natural reaction pauses.
        """
        if frame is None:
            frame = self.device.screencap_mat()
        if frame is None:
            logger.error("Failed to capture frame for sequential click CAPTCHA")
            return False

        logger.info(f"Submitting frame to VLM for sequential click analysis: '{prompt_text}'")
        res = self.vlm.solve_sequential_captcha(frame, prompt_text=prompt_text)
        labels = res.get("labels", [])
        points = res.get("points", [])
        confidence = res.get("confidence", 0.0)

        logger.info(f"VLM Sequential targets: labels={labels}, points={points}, conf={confidence:.2f}")
        if not points:
            logger.warning("VLM returned no valid click points for sequential CAPTCHA")
            self.notifier.send_alert(
                title="⚠️ 顺序点选防挂机识别异常",
                message=f"设备 {self.device.name} 未能识别出顺序点选坐标，要求: {prompt_text}",
            )
            return False

        for idx, (px, py) in enumerate(points):
            label = labels[idx] if idx < len(labels) else f"Step {idx+1}"
            logger.info(f"Clicking target [{label}] at ({px}, {py}) with Gaussian jitter...")
            self.controller.human_click(
                px,
                py,
                radius_x=6.0,
                radius_y=6.0,
                reaction_delay_range=(0.25, 0.55),
            )

        time.sleep(0.5)
        logger.info("Sequential text clicks completed.")
        return True

    def solve_dialog_trivia(
        self,
        frame: Optional[np.ndarray] = None,
        question: str = "",
        options: Optional[List[str]] = None,
        option_bboxes: Optional[List[Tuple[int, int, int, int]]] = None,
    ) -> bool:
        """
        Solve on-screen trivia or visual selection popup:
        1. If options and bboxes are provided, invoke VLM structured selection.
        2. Click the winning option coordinates.
        """
        if frame is None:
            frame = self.device.screencap_mat()
        if frame is None:
            logger.error("Failed to capture frame for dialog trivia")
            return False

        if not options:
            options = ["选项 A", "选项 B", "选项 C", "选项 D"]

        res = self.vlm.solve_question(frame, question=question, options=options)
        opt_idx = res.get("option_index", 0)
        answer = res.get("answer", "")
        confidence = res.get("confidence", 0.0)

        logger.info(f"VLM Trivia solved: chosen index={opt_idx}, answer='{answer}', conf={confidence:.2f}")

        if option_bboxes and 0 <= opt_idx < len(option_bboxes):
            bx, by, bw, bh = option_bboxes[opt_idx]
            cx = bx + bw / 2
            cy = by + bh / 2
        else:
            # Standard dialog option layout fallback
            cx = 450 + (opt_idx % 2) * 280
            cy = 380 + (opt_idx // 2) * 80

        self.controller.human_click(cx, cy, radius_x=10.0, radius_y=10.0)
        time.sleep(0.3)
        return True

    def auto_solve_challenge(
        self,
        frame: Optional[np.ndarray] = None,
        detected_text: str = "",
        slider_start_hint: Optional[Tuple[int, int]] = None,
    ) -> bool:
        """
        Automatically classifies the anti-bot challenge type and dispatches to the
        appropriate humanized solving pipeline:
        - Slider puzzle: detects gap and generates physics-based dragging trajectory
        - Sequential click: identifies semantic ordering and applies Gaussian jitter clicks
        - General QA: parses multi-choice options and taps the winning target
        """
        text = detected_text.strip()
        logger.info(f"Auto-dispatching challenge verification for modal text: '{text}'")

        if any(kw in text for kw in ["滑块", "拼图", "拖动", "滑动", "缺口"]):
            logger.info("Classified as SLIDER puzzle challenge")
            return self.solve_slider_puzzle(
                frame=frame,
                slider_start_hint=slider_start_hint,
                prompt_text=text or "拖动下方滑块完成拼图",
            )
        elif any(kw in text for kw in ["依次点击", "语序", "成语", "顺序", "点选"]):
            logger.info("Classified as SEQUENTIAL click challenge")
            return self.solve_sequential_text_click(
                frame=frame,
                prompt_text=text or "请按顺序依次点击文字",
            )
        else:
            logger.info("Classified as general DIALOG / TRIVIA challenge")
            return self.solve_dialog_trivia(
                frame=frame,
                question=text,
            )

