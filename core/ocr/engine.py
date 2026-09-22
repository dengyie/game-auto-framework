from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

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


@dataclass
class OCRResultItem:
    """Represents a single recognized text block with position and confidence."""

    text: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)
    center: Tuple[int, int]  # (cx, cy)


class OCREngine:
    """RapidOCR inference engine with ROI cropping, frame caching, and fuzzy text localization."""

    _instance: Optional[OCREngine] = None

    def __init__(self, use_mock_if_missing: bool = True):
        self._ocr = None
        self.is_mock = False
        self._lock = threading.Lock()
        self._frame_cache: OrderedDict[Tuple[Any, ...], List[OCRResultItem]] = OrderedDict()
        self._cached_frame_refs: List[Any] = []
        self._max_cached_frames = 6

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

    def clear_cache(self) -> None:
        """Clear cached OCR frame results."""
        with self._lock:
            self._frame_cache.clear()
            self._cached_frame_refs.clear()

    @staticmethod
    def _get_input_key(image_input: Union[np.ndarray, bytes, str, Path]) -> Optional[Tuple[Any, ...]]:
        """Compute a fast hashable key identifying the image input instance."""
        if isinstance(image_input, np.ndarray):
            data_ptr = image_input.__array_interface__["data"][0]
            return ("ndarray", id(image_input), image_input.shape, data_ptr)
        if isinstance(image_input, bytes):
            return ("bytes", hash(image_input), len(image_input))
        if isinstance(image_input, (str, Path)):
            path_str = str(image_input)
            try:
                mtime = os.path.getmtime(path_str)
            except OSError:
                mtime = 0.0
            return ("file", path_str, mtime)
        return None

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
        """Run OCR on the given image or sub-ROI with per-frame caching and thread safety."""
        input_key = self._get_input_key(image)

        with self._lock:
            if input_key is not None:
                cache_key = (input_key, roi)
                if cache_key in self._frame_cache:
                    cached_items = self._frame_cache[cache_key]
                    return [
                        OCRResultItem(it.text, it.confidence, it.bbox, it.center)
                        for it in cached_items
                    ]

                # If full frame is already in cache and caller queries a sub-ROI
                if roi is not None:
                    full_cache_key = (input_key, None)
                    if full_cache_key in self._frame_cache:
                        rx, ry, rw, rh = roi
                        full_items = self._frame_cache[full_cache_key]
                        filtered = [
                            OCRResultItem(it.text, it.confidence, it.bbox, it.center)
                            for it in full_items
                            if rx <= it.center[0] <= rx + rw and ry <= it.center[1] <= ry + rh
                        ]
                        self._frame_cache[cache_key] = filtered
                        return filtered

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
                    items: List[OCRResultItem] = []
                else:
                    items = []
                    for dt_boxes, rec_res, score in ocr_results:
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

                # Store in cache
                if input_key is not None:
                    cache_key = (input_key, roi)
                    self._frame_cache[cache_key] = items
                    # Retain frame reference to prevent id reuse
                    self._cached_frame_refs.append(image)
                    if len(self._cached_frame_refs) > self._max_cached_frames:
                        self._cached_frame_refs.pop(0)
                    while len(self._frame_cache) > self._max_cached_frames * 4:
                        self._frame_cache.popitem(last=False)

                return [
                    OCRResultItem(it.text, it.confidence, it.bbox, it.center)
                    for it in items
                ]
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
