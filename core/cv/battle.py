from __future__ import annotations

from typing import Optional, Union, Tuple
import cv2
import numpy as np

from core.cv.matcher import TemplateMatcher, MatchResult


class BattleDetector:
    """Specialized combat detector for turn-based game states (in-battle vs peaceful)."""

    def __init__(
        self,
        auto_battle_template: Optional[Union[np.ndarray, bytes, str]] = None,
        auto_battle_roi: Tuple[int, int, int, int] = (1000, 500, 280, 220),
    ):
        self.auto_battle_template = auto_battle_template
        self.auto_battle_roi = auto_battle_roi

    def is_in_battle(
        self,
        frame: Union[np.ndarray, bytes],
        custom_checker: Optional[callable] = None,
    ) -> bool:
        """Determine whether the current screen represents an active combat session."""
        if custom_checker:
            return bool(custom_checker(frame))

        if self.auto_battle_template is not None:
            res = TemplateMatcher.match(
                frame,
                self.auto_battle_template,
                threshold=0.75,
                roi=self.auto_battle_roi,
            )
            if res.found:
                return True

        # Fallback HSV color-based heuristic: Combat UI in MHXY typically displays
        # bright yellow/gold countdown timer or auto-battle status in the combat action area.
        return self._detect_combat_hsv(frame)

    def _detect_combat_hsv(self, frame: Union[np.ndarray, bytes]) -> bool:
        if isinstance(frame, bytes):
            nparr = np.frombuffer(frame, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        else:
            img = frame

        if img is None:
            return False

        rx, ry, rw, rh = self.auto_battle_roi
        h, w = img.shape[:2]
        crop = img[ry : min(h, ry + rh), rx : min(w, rx + rw)]
        if crop.size == 0:
            return False

        # Check for vibrant combat indicator highlights in HSV
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        # Golden / Yellow / Orange highlight range
        lower_gold = np.array([15, 120, 120])
        upper_gold = np.array([35, 255, 255])
        mask = cv2.inRange(hsv, lower_gold, upper_gold)
        ratio = float(np.count_nonzero(mask)) / float(mask.size)

        # In combat, button area has significant gold/yellow UI elements
        return ratio > 0.05
