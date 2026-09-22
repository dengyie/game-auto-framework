from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np
from loguru import logger


@dataclass
class MatchResult:
    """Represents the outcome of a CV template matching operation."""

    found: bool
    confidence: float
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)
    center: Tuple[int, int]  # (cx, cy)

    @classmethod
    def not_found(cls) -> MatchResult:
        return cls(found=False, confidence=0.0, bbox=(0, 0, 0, 0), center=(0, 0))


class TemplateMatcher:
    """High-performance template matcher supporting single, multi-scale, and multi-object detection."""

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
                logger.warning(f"Template path does not exist: {path_str}")
                return None
            return cv2.imread(path_str, cv2.IMREAD_COLOR)
        return None

    @classmethod
    def match(
        cls,
        image: Union[np.ndarray, bytes, str, Path],
        template: Union[np.ndarray, bytes, str, Path],
        threshold: float = 0.8,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> MatchResult:
        """Find the best match of template in image, optionally restricted to an ROI."""
        img = cls._to_cv2_image(image)
        tpl = cls._to_cv2_image(template)

        if img is None or tpl is None:
            return MatchResult.not_found()

        offset_x, offset_y = 0, 0
        if roi:
            rx, ry, rw, rh = roi
            h, w = img.shape[:2]
            rx = max(0, min(rx, w - 1))
            ry = max(0, min(ry, h - 1))
            rw = min(rw, w - rx)
            rh = min(rh, h - ry)
            if rw <= 0 or rh <= 0:
                return MatchResult.not_found()
            img = img[ry : ry + rh, rx : rx + rw]
            offset_x, offset_y = rx, ry

        th, tw = tpl.shape[:2]
        ih, iw = img.shape[:2]
        if th > ih or tw > iw:
            return MatchResult.not_found()

        # Convert to grayscale if both are color to speed up matching
        if len(img.shape) == 3 and len(tpl.shape) == 3:
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        else:
            img_gray = img
            tpl_gray = tpl

        res = cv2.matchTemplate(img_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val >= threshold:
            top_left_x = max_loc[0] + offset_x
            top_left_y = max_loc[1] + offset_y
            center_x = top_left_x + tw // 2
            center_y = top_left_y + th // 2
            return MatchResult(
                found=True,
                confidence=float(max_val),
                bbox=(top_left_x, top_left_y, tw, th),
                center=(center_x, center_y),
            )

        return MatchResult(
            found=False,
            confidence=float(max_val),
            bbox=(max_loc[0] + offset_x, max_loc[1] + offset_y, tw, th),
            center=(max_loc[0] + offset_x + tw // 2, max_loc[1] + offset_y + th // 2),
        )

    @classmethod
    def match_multi_scale(
        cls,
        image: Union[np.ndarray, bytes, str, Path],
        template: Union[np.ndarray, bytes, str, Path],
        scales: Tuple[float, ...] = (0.85, 0.95, 1.0, 1.05, 1.15),
        threshold: float = 0.8,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> MatchResult:
        """Match template across multiple scale ratios."""
        tpl_orig = cls._to_cv2_image(template)
        if tpl_orig is None:
            return MatchResult.not_found()

        best_result = MatchResult.not_found()
        for s in scales:
            new_w = max(4, int(tpl_orig.shape[1] * s))
            new_h = max(4, int(tpl_orig.shape[0] * s))
            scaled_tpl = cv2.resize(tpl_orig, (new_w, new_h), interpolation=cv2.INTER_AREA)

            res = cls.match(image, scaled_tpl, threshold=threshold, roi=roi)
            if res.confidence > best_result.confidence:
                best_result = res
            if res.found:
                return res

        return best_result

    @classmethod
    def find_all(
        cls,
        image: Union[np.ndarray, bytes, str, Path],
        template: Union[np.ndarray, bytes, str, Path],
        threshold: float = 0.8,
        roi: Optional[Tuple[int, int, int, int]] = None,
        max_count: int = 20,
        min_distance: int = 15,
    ) -> List[MatchResult]:
        """Find multiple non-overlapping occurrences of the template in the image."""
        img = cls._to_cv2_image(image)
        tpl = cls._to_cv2_image(template)

        if img is None or tpl is None:
            return []

        offset_x, offset_y = 0, 0
        if roi:
            rx, ry, rw, rh = roi
            h, w = img.shape[:2]
            img = img[ry : min(h, ry + rh), rx : min(w, rx + rw)]
            offset_x, offset_y = rx, ry

        th, tw = tpl.shape[:2]
        ih, iw = img.shape[:2]
        if th > ih or tw > iw:
            return []

        if len(img.shape) == 3 and len(tpl.shape) == 3:
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        else:
            img_gray = img
            tpl_gray = tpl

        res = cv2.matchTemplate(img_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        y_locs, x_locs = np.where(res >= threshold)

        candidates = []
        for x, y in zip(x_locs, y_locs):
            candidates.append((float(res[y, x]), int(x), int(y)))

        # Sort by confidence descending
        candidates.sort(key=lambda item: item[0], reverse=True)

        results: List[MatchResult] = []
        for conf, x, y in candidates:
            if len(results) >= max_count:
                break
            abs_x = x + offset_x
            abs_y = y + offset_y
            cx = abs_x + tw // 2
            cy = abs_y + th // 2

            # Non-maximum suppression check
            too_close = False
            for existing in results:
                ex_cx, ex_cy = existing.center
                if abs(cx - ex_cx) < min_distance and abs(cy - ex_cy) < min_distance:
                    too_close = True
                    break

            if not too_close:
                results.append(
                    MatchResult(
                        found=True,
                        confidence=conf,
                        bbox=(abs_x, abs_y, tw, th),
                        center=(cx, cy),
                    )
                )

        return results
