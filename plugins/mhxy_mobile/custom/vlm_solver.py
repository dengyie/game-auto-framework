"""
Vision Language Model Solver specialized for Fantasy Westward Journey Mobile.
Combines local OCR and Multi-modal VLM for unknown questions and anti-bot verification challenges.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from loguru import logger

from core.ocr.vlm import VLMClient


class MHXYVLMSolver:
    """Specialized VLM Solver for MHXY exam and anti-bot captcha challenges."""

    def __init__(self, vlm_client: Optional[VLMClient] = None) -> None:
        self.vlm = vlm_client or VLMClient.get_instance()

    def solve_exam(
        self,
        image: Union[np.ndarray, bytes, str, Path],
        question: str,
        options: List[str],
    ) -> Dict[str, Any]:
        """Solve Keju / Sanjie multi-choice exam questions."""
        return self.vlm.solve_question(image=image, question=question, options=options)

    def solve_anti_bot_captcha(
        self,
        image: Union[np.ndarray, bytes, str, Path],
        prompt_text: str = "",
        option_bboxes: Optional[List[Tuple[int, int, int, int]]] = None,
    ) -> Tuple[int, int]:
        """
        Solve anti-bot popups (e.g. identify character facing forward, choose idioms).
        Returns the (x, y) screen coordinates to click.
        """
        prompt = (
            f"这是《梦幻西游手游》的防挂机验证弹窗：\n"
            f"提示文字：{prompt_text}\n"
            f"请识别弹窗中符合要求的正确目标选项，并输出其相对整张画面的点击坐标 (x, y)。\n"
            f"以严格的 JSON 格式输出：{{\"click_x\": 520, \"click_y\": 380, \"reason\": \"...\"}}"
        )

        resp_text = self.vlm.ask_image(image=image, prompt=prompt)

        try:
            clean = resp_text.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()
            data = json.loads(clean)
            cx = int(data.get("click_x", 640))
            cy = int(data.get("click_y", 360))
            return cx, cy
        except Exception as e:
            logger.debug(f"Failed to parse coordinates from VLM response: {e}; returning default center target")
            if option_bboxes and len(option_bboxes) > 0:
                bx, by, bw, bh = option_bboxes[0]
                return bx + bw // 2, by + bh // 2
            return 640, 360
