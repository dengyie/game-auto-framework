"""Computer vision perception engine for template matching, diff analysis, and game state detection."""

from core.cv.matcher import MatchResult, TemplateMatcher
from core.cv.diff import FrameDiffDetector, is_frame_static, compute_dhash
from core.cv.battle import BattleDetector

__all__ = [
    "MatchResult",
    "TemplateMatcher",
    "FrameDiffDetector",
    "is_frame_static",
    "compute_dhash",
    "BattleDetector",
]
