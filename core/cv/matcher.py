from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

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


@dataclass
class _CachedTemplate:
    mtime: float
    bgr: np.ndarray
    gray: np.ndarray
    h: int
    w: int


_TEMPLATE_CACHE: Dict[str, _CachedTemplate] = {}


class TemplateMatcher:
    """High-performance template matcher supporting single, multi-scale, and multi-object detection."""

    @classmethod
    def clear_template_cache(cls) -> None:
        """Clear the in-memory template cache."""
        _TEMPLATE_CACHE.clear()

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
            cached = _TEMPLATE_CACHE.get(path_str)
            if cached is not None:
                try:
                    mtime = os.path.getmtime(path_str)
                    if cached.mtime == mtime:
                        return cached.bgr
                except OSError:
                    pass
            img = cv2.imread(path_str, cv2.IMREAD_COLOR)
            if img is not None:
                try:
                    mtime = os.path.getmtime(path_str)
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    h, w = img.shape[:2]
                    _TEMPLATE_CACHE[path_str] = _CachedTemplate(mtime=mtime, bgr=img, gray=gray, h=h, w=w)
                except OSError:
                    pass
            return img
        return None

    @classmethod
    def _load_template_gray(
        cls, template_input: Union[np.ndarray, bytes, str, Path]
    ) -> Optional[Tuple[np.ndarray, int, int]]:
        """Return (gray_img, height, width) with in-memory caching for zero disk I/O."""
        if isinstance(template_input, (str, Path)):
            path_str = str(template_input)
            if not os.path.exists(path_str):
                logger.warning(f"Template path does not exist: {path_str}")
                return None
            cached = _TEMPLATE_CACHE.get(path_str)
            try:
                mtime = os.path.getmtime(path_str)
                if cached is not None and cached.mtime == mtime:
                    return cached.gray, cached.h, cached.w
            except OSError:
                mtime = 0.0

            img = cv2.imread(path_str, cv2.IMREAD_COLOR)
            if img is None:
                return None
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape[:2]
            _TEMPLATE_CACHE[path_str] = _CachedTemplate(mtime=mtime, bgr=img, gray=gray, h=h, w=w)
            return gray, h, w

        if isinstance(template_input, np.ndarray):
            if len(template_input.shape) == 3:
                gray = cv2.cvtColor(template_input, cv2.COLOR_BGR2GRAY)
            else:
                gray = template_input
            h, w = gray.shape[:2]
            return gray, h, w

        if isinstance(template_input, bytes):
            nparr = np.frombuffer(template_input, np.uint8)
            gray = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
            if gray is None:
                return None
            h, w = gray.shape[:2]
            return gray, h, w

        return None

    @classmethod
    def _to_gray(cls, image_input: Union[np.ndarray, bytes, str, Path]) -> Optional[np.ndarray]:
        """Convert any image input directly to 1-channel grayscale matrix."""
        if isinstance(image_input, np.ndarray):
            if len(image_input.shape) == 3:
                return cv2.cvtColor(image_input, cv2.COLOR_BGR2GRAY)
            return image_input
        if isinstance(image_input, bytes):
            nparr = np.frombuffer(image_input, np.uint8)
            return cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        if isinstance(image_input, (str, Path)):
            tpl_info = cls._load_template_gray(image_input)
            return tpl_info[0] if tpl_info else None
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
        img_gray = cls._to_gray(image)
        tpl_info = cls._load_template_gray(template)

        if img_gray is None or tpl_info is None:
            return MatchResult.not_found()

        tpl_gray, th, tw = tpl_info

        offset_x, offset_y = 0, 0
        if roi:
            rx, ry, rw, rh = roi
            h, w = img_gray.shape[:2]
            rx = max(0, min(rx, w - 1))
            ry = max(0, min(ry, h - 1))
            rw = min(rw, w - rx)
            rh = min(rh, h - ry)
            if rw <= 0 or rh <= 0:
                return MatchResult.not_found()
            img_gray = img_gray[ry : ry + rh, rx : rx + rw]
            offset_x, offset_y = rx, ry

        ih, iw = img_gray.shape[:2]
        if th > ih or tw > iw:
            return MatchResult.not_found()

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
        """Match template across multiple scale ratios with single image decode."""
        img_gray = cls._to_gray(image)
        tpl_info = cls._load_template_gray(template)
        if img_gray is None or tpl_info is None:
            return MatchResult.not_found()

        tpl_gray, orig_th, orig_tw = tpl_info

        offset_x, offset_y = 0, 0
        if roi:
            rx, ry, rw, rh = roi
            h, w = img_gray.shape[:2]
            rx = max(0, min(rx, w - 1))
            ry = max(0, min(ry, h - 1))
            rw = min(rw, w - rx)
            rh = min(rh, h - ry)
            if rw <= 0 or rh <= 0:
                return MatchResult.not_found()
            img_gray = img_gray[ry : ry + rh, rx : rx + rw]
            offset_x, offset_y = rx, ry

        ih, iw = img_gray.shape[:2]
        best_result = MatchResult.not_found()

        for s in scales:
            new_w = max(4, int(orig_tw * s))
            new_h = max(4, int(orig_th * s))
            if new_h > ih or new_w > iw:
                continue

            if abs(s - 1.0) < 1e-4:
                scaled_tpl = tpl_gray
            else:
                scaled_tpl = cv2.resize(tpl_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)

            res = cv2.matchTemplate(img_gray, scaled_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            top_left_x = max_loc[0] + offset_x
            top_left_y = max_loc[1] + offset_y
            center_x = top_left_x + new_w // 2
            center_y = top_left_y + new_h // 2
            match_res = MatchResult(
                found=max_val >= threshold,
                confidence=float(max_val),
                bbox=(top_left_x, top_left_y, new_w, new_h),
                center=(center_x, center_y),
            )

            if match_res.confidence > best_result.confidence:
                best_result = match_res
            if match_res.found:
                return match_res

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
        img_gray = cls._to_gray(image)
        tpl_info = cls._load_template_gray(template)

        if img_gray is None or tpl_info is None:
            return []

        tpl_gray, th, tw = tpl_info

        offset_x, offset_y = 0, 0
        if roi:
            rx, ry, rw, rh = roi
            h, w = img_gray.shape[:2]
            img_gray = img_gray[ry : min(h, ry + rh), rx : min(w, rx + rw)]
            offset_x, offset_y = rx, ry

        ih, iw = img_gray.shape[:2]
        if th > ih or tw > iw:
            return []

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
