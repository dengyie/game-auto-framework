"""Optical Character Recognition (OCR) and fuzzy matching engine."""

from core.ocr.engine import OCREngine, OCRResultItem
from core.ocr.fuzzy import fuzzy_match_ratio, find_best_match

__all__ = [
    "OCREngine",
    "OCRResultItem",
    "fuzzy_match_ratio",
    "find_best_match",
]
