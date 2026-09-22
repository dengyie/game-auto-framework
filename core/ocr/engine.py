from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np
from loguru import logger

from core.ocr.fuzzy import fuzzy_match_ratio


@dataclass
class OCRResultItem:
    """Represents a single recognized text block with position and confidence."""

    text: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)
    center: Tuple[int, int]  # (cx, cy)


class OCREngine:
    """RapidOCR inference engine with ROI cropping and fuzzy text localization."""

    _instance: Optional[OCREngine] = None

    def __init__(self, use_mock_if_missing: bool = True):
        self._ocr = None
        self.is_mock = False

        try:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
            logger.info("RapidOCR ONNX engine initialized successfully.")
        except Exception as e:
            if use_mock_if_missing:
                logger.warning(f"Failed to initialize RapidOCR ({e}). Operating in Mock OCR mode.")
                self.is_mock = True
            else:
                raise

    @classmethod
    def get_instance(cls) -> OCREngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _to_cv2_image(image_input: Union[np.ndarray, bytes, str, Path]) -> Optional[np.ndarray]:
        if isinstance(image_input, np.ndarray):
            return image_input
        if isinstance(image_input, bytes):
            nparr = np.frombuffer(image_input, np.uint8)
            return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if isinstance(image_input, (str, Path)):
            path_str = str(image_input)
            if not os.path.exists(path_str):
                return None
            return cv2.imread(path_str, cv2.IMREAD_COLOR)
        return None

    def recognize(
        self,
        image: Union[np.ndarray, bytes, str, Path],
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> List[OCRResultItem]:
        """Run OCR on the given image or sub-ROI."""
        img = self._to_cv2_image(image)
        if img is None:
            return []

        offset_x, offset_y = 0, 0
        if roi:
            rx, ry, rw, rh = roi
            h, w = img.shape[:2]
            rx = max(0, min(rx, w - 1))
            ry = max(0, min(ry, h - 1))
            rw = min(rw, w - rx)
            rh = min(rh, h - ry)
            if rw <= 0 or rh <= 0:
                return []
            img = img[ry : ry + rh, rx : rx + rw]
            offset_x, offset_y = rx, ry

        if self.is_mock or self._ocr is None:
            return []

        try:
            ocr_results, _ = self._ocr(img)
            if not ocr_results:
                return []

            items: List[OCRResultItem] = []
            for dt_boxes, rec_res, score in ocr_results:
                # dt_boxes is 4 points: [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
                xs = [pt[0] for pt in dt_boxes]
                ys = [pt[1] for pt in dt_boxes]
                min_x = int(min(xs)) + offset_x
                max_x = int(max(xs)) + offset_x
                min_y = int(min(ys)) + offset_y
                max_y = int(max(ys)) + offset_y

                bw = max_x - min_x
                bh = max_y - min_y
                cx = min_x + bw // 2
                cy = min_y + bh // 2

                items.append(
                    OCRResultItem(
                        text=str(rec_res).strip(),
                        confidence=float(score),
                        bbox=(min_x, min_y, bw, bh),
                        center=(cx, cy),
                    )
                )
            return items
        except Exception as e:
            logger.error(f"OCR recognition error: {e}")
            return []

    def find_text(
        self,
        image: Union[np.ndarray, bytes, str, Path],
        target_text: str,
        roi: Optional[Tuple[int, int, int, int]] = None,
        threshold: float = 75.0,
    ) -> Optional[OCRResultItem]:
        """Find the text block in the image that best matches target_text."""
        items = self.recognize(image, roi=roi)
        best_item: Optional[OCRResultItem] = None
        best_score: float = 0.0

        for item in items:
            ratio = fuzzy_match_ratio(target_text, item.text)
            if ratio > best_score:
                best_score = ratio
                best_item = item

        if best_score >= threshold and best_item is not None:
            return best_item
        return None

    def find_any_text(
        self,
        image: Union[np.ndarray, bytes, str, Path],
        candidates: List[str],
        roi: Optional[Tuple[int, int, int, int]] = None,
        threshold: float = 75.0,
    ) -> Optional[Tuple[str, OCRResultItem]]:
        """Find the first matching candidate text in the image."""
        items = self.recognize(image, roi=roi)
        for cand in candidates:
            for item in items:
                ratio = fuzzy_match_ratio(cand, item.text)
                if ratio >= threshold:
                    return cand, item
        return None
