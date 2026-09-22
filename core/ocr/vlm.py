"""
Multi-modal Vision Language Model (VLM) Engine for complex UI perception and quiz solving.
Compatible with OpenAI, Alibaba DashScope (Qwen-VL), ZhipuAI, and Local Ollama VLM APIs.
Provides graceful offline fallback / mock inference when credentials are not configured.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import cv2
import numpy as np
from loguru import logger
import urllib.request
import urllib.error


class VLMClient:
    """Unified client for multi-modal vision-language model inference."""

    _instance: Optional[VLMClient] = None

    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_sec: float = 10.0,
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

        # Parse JSON response
        try:
            # Extract JSON block if wrapped in markdown code fence
            clean_text = resp_text.strip()
            if "```json" in clean_text:
                clean_text = clean_text.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_text:
                clean_text = clean_text.split("```")[1].split("```")[0].strip()

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
            logger.debug(f"Failed to parse structured JSON from VLM response: {e}; falling back to option 0")
            # Simple substring matching heuristic
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

    def _mock_response(self, prompt: str) -> str:
        """Deterministic offline mock response for CI testing and environments without API key."""
        if "option_index" in prompt:
            return json.dumps({"option_index": 1, "answer": "正确选项", "confidence": 0.98})
        return "模拟多模态大模型回答：已识别目标区域。"
