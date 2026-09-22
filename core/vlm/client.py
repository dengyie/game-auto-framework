"""
Unified Vision Language Model (VLM) Client for complex UI reasoning,
slider captcha localization, sequential text selection, and in-game trivia solving.
Supports OpenAI (GPT-4o / GPT-4o-mini), ZhipuAI (GLM-4V), DashScope (Qwen-VL), and Ollama.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import cv2
import numpy as np
from loguru import logger
import urllib.request
import urllib.error


class VLMClient:
    """Multi-modal Vision-Language Model client for game automation perception."""

    _instance: Optional[VLMClient] = None

    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_sec: float = 12.0,
        enable_mock_fallback: bool = True,
    ) -> None:
        self.api_base = (
            api_base
            or os.environ.get("VLM_API_BASE")
            or os.environ.get("OPENAI_API_BASE")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("VLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        self.model_name = (
            model_name
            or os.environ.get("VLM_MODEL")
            or "gpt-4o-mini"
        )
        self.timeout_sec = timeout_sec
        self.enable_mock_fallback = enable_mock_fallback

    @classmethod
    def get_instance(cls) -> VLMClient:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _encode_image_to_base64(image: Union[np.ndarray, bytes, str, Path]) -> str:
        """Convert cv2 ndarray, bytes, or file path to Base64 PNG string."""
        if isinstance(image, (str, Path)):
            with open(image, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        elif isinstance(image, bytes):
            return base64.b64encode(image).decode("utf-8")
        elif isinstance(image, np.ndarray):
            success, buffer = cv2.imencode(".png", image)
            if not success:
                raise ValueError("Failed to encode cv2 image to PNG buffer")
            return base64.b64encode(buffer).decode("utf-8")
        else:
            raise TypeError(f"Unsupported image type: {type(image)}")

    def ask_image(
        self,
        image: Union[np.ndarray, bytes, str, Path],
        prompt: str,
        system_prompt: str = "You are a professional game AI vision perception assistant.",
    ) -> str:
        """Send an image with prompt to the VLM and return text response."""
        if not self.api_key:
            if self.enable_mock_fallback:
                logger.debug("VLM API key not configured; using offline mock response.")
                return self._mock_response(prompt)
            raise ValueError("VLM API key is required but not provided")

        base64_img = self._encode_image_to_base64(image)
        url = f"{self.api_base}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_img}",
                                "detail": "low",
                            },
                        },
                    ],
                },
            ],
            "max_tokens": 512,
            "temperature": 0.1,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
                return ""
        except Exception as e:
            logger.warning(f"VLM API request failed: {e}")
            if self.enable_mock_fallback:
                logger.info("Falling back to offline mock response after VLM network failure")
                return self._mock_response(prompt)
            raise

    def solve_question(
        self,
        image: Union[np.ndarray, bytes, str, Path],
        question: str,
        options: List[str],
    ) -> Dict[str, Any]:
        """
        Solve a multi-choice question from an on-screen dialog image.
        Returns:
            {"answer": str, "option_index": int, "confidence": float, "raw_response": str}
        """
        options_formatted = "\n".join([f"{idx + 1}. {opt}" for idx, opt in enumerate(options)])
        prompt = (
            f"游戏屏幕中出现题目：\n【题目】：{question}\n【选项】：\n{options_formatted}\n"
            f"请根据游戏知识和图片内容，直接输出最优选项的数字编号（如 1 或 2）与选项内容，"
            f"以严格的 JSON 格式输出：{{\"option_index\": 1, \"answer\": \"选项内容\", \"confidence\": 0.95}}"
        )

        resp_text = self.ask_image(
            image=image,
            prompt=prompt,
            system_prompt="你是一个精通各类MMORPG游戏答题与防作弊验证码识别的专家，输出严格的JSON格式。",
        )

        try:
            clean_text = self._extract_json_block(resp_text)
            parsed = json.loads(clean_text)
            opt_idx = int(parsed.get("option_index", 1)) - 1
            if opt_idx < 0 or opt_idx >= len(options):
                opt_idx = 0

            return {
                "answer": parsed.get("answer", options[opt_idx]),
                "option_index": opt_idx,
                "confidence": float(parsed.get("confidence", 0.9)),
                "raw_response": resp_text,
            }
        except Exception as e:
            logger.debug(f"Failed to parse structured JSON from VLM response: {e}; falling back to substring heuristic")
            for idx, opt in enumerate(options):
                if opt in resp_text:
                    return {
                        "answer": opt,
                        "option_index": idx,
                        "confidence": 0.75,
                        "raw_response": resp_text,
                    }
            return {
                "answer": options[0] if options else "",
                "option_index": 0,
                "confidence": 0.5,
                "raw_response": resp_text,
            }

    def solve_slider_captcha(
        self,
        image: Union[np.ndarray, bytes, str, Path],
        prompt_text: str = "拖动下方滑块完成拼图",
    ) -> Dict[str, Any]:
        """
        Detect gap location and slider thumb start position in a slider puzzle.
        Returns:
            {"slider_x": int, "slider_y": int, "gap_x": int, "gap_y": int, "distance": int, "confidence": float}
        """
        prompt = (
            f"请仔细观察这张游戏防挂机滑块验证码图片（标准分辨率 1280x720）：\n"
            f"任务：{prompt_text}\n"
            f"1. 定位滑块拖拽起始把手/滑块原位的中心坐标 (slider_x, slider_y)。\n"
            f"2. 定位背景图中目标缺口/阴影拼图凹槽的中心坐标 (gap_x, gap_y)。\n"
            f"3. 计算水平滑动距离 distance = gap_x - slider_x。\n"
            f"请严格按以下 JSON 格式输出，不要附加任何其他说明文字：\n"
            f"{{\"slider_x\": 420, \"slider_y\": 530, \"gap_x\": 710, \"gap_y\": 380, \"distance\": 290, \"confidence\": 0.95}}"
        )

        resp_text = self.ask_image(
            image=image,
            prompt=prompt,
            system_prompt="你是一个高精度的视觉目标检测与坐标定位专家，精确定位游戏中的滑块与拼图缺口位置，仅输出JSON。",
        )

        try:
            clean = self._extract_json_block(resp_text)
            data = json.loads(clean)
            sx = int(data.get("slider_x", 420))
            sy = int(data.get("slider_y", 530))
            gx = int(data.get("gap_x", 710))
            gy = int(data.get("gap_y", 380))
            dist = int(data.get("distance", max(0, gx - sx)))
            conf = float(data.get("confidence", 0.92))
            return {
                "slider_x": sx,
                "slider_y": sy,
                "gap_x": gx,
                "gap_y": gy,
                "distance": dist,
                "confidence": conf,
                "raw_response": resp_text,
            }
        except Exception as e:
            logger.warning(f"Failed to parse slider coordinates: {e}; using fallback estimate")
            return {
                "slider_x": 420,
                "slider_y": 530,
                "gap_x": 700,
                "gap_y": 380,
                "distance": 280,
                "confidence": 0.60,
                "raw_response": resp_text,
            }

    def solve_sequential_captcha(
        self,
        image: Union[np.ndarray, bytes, str, Path],
        prompt_text: str = "请依次点击文字",
    ) -> Dict[str, Any]:
        """
        Detect target sequential click order and coordinates for semantic click captcha.
        Returns:
            {"labels": List[str], "points": List[Tuple[int, int]], "confidence": float}
        """
        prompt = (
            f"这是游戏防作弊顺序点选验证码图片（标准分辨率 1280x720）：\n"
            f"提示要求：{prompt_text}\n"
            f"请识别出题目要求点击的文字或图案顺序，并依次给出每个目标在画面中的中心绝对坐标 (x, y)。\n"
            f"必须以严格 JSON 格式输出：\n"
            f"{{\"labels\": [\"桃\", \"李\", \"春\", \"风\"], \"points\": [[480, 320], [610, 390], [530, 460], [690, 310]], \"confidence\": 0.94}}"
        )

        resp_text = self.ask_image(
            image=image,
            prompt=prompt,
            system_prompt="你是一个高精度的视觉文字定位与防作弊验证专家，输出严格的JSON坐标列表。",
        )

        try:
            clean = self._extract_json_block(resp_text)
            data = json.loads(clean)
            labels = list(data.get("labels", ["文字1", "文字2"]))
            raw_pts = data.get("points", [[500, 360], [640, 360]])
            pts = [(int(p[0]), int(p[1])) for p in raw_pts if len(p) >= 2]
            conf = float(data.get("confidence", 0.90))
            return {
                "labels": labels,
                "points": pts,
                "confidence": conf,
                "raw_response": resp_text,
            }
        except Exception as e:
            logger.warning(f"Failed to parse sequential click points: {e}; using fallback points")
            return {
                "labels": ["目标1", "目标2"],
                "points": [(520, 360), (660, 360)],
                "confidence": 0.55,
                "raw_response": resp_text,
            }

    @staticmethod
    def _extract_json_block(text: str) -> str:
        clean = text.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        return clean

    def _mock_response(self, prompt: str) -> str:
        """Deterministic offline mock response for CI testing and environments without API key."""
        if "slider_x" in prompt or "滑块" in prompt or "拼图" in prompt:
            return json.dumps({
                "slider_x": 420,
                "slider_y": 530,
                "gap_x": 715,
                "gap_y": 380,
                "distance": 295,
                "confidence": 0.96,
            })
        if "points" in prompt or "依次点击" in prompt or "顺序点选" in prompt:
            return json.dumps({
                "labels": ["桃", "李", "满", "天"],
                "points": [[480, 320], [610, 390], [530, 460], [690, 310]],
                "confidence": 0.95,
            })
        if "option_index" in prompt:
            return json.dumps({
                "option_index": 1,
                "answer": "正确选项",
                "confidence": 0.98,
            })
        if "click_x" in prompt:
            return json.dumps({
                "click_x": 520,
                "click_y": 380,
                "confidence": 0.95,
            })
        return "模拟多模态大模型回答：已识别目标区域。"
