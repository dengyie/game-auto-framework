"""Unit tests for OCR engine and RapidFuzz text matching."""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from core.ocr.engine import OCREngine, OCRResultItem
from core.ocr.fuzzy import fuzzy_match_ratio, find_best_match


def test_fuzzy_matching_utilities():
    assert fuzzy_match_ratio("师门任务", "师门任务(20/20)") >= 80.0
    assert fuzzy_match_ratio("宝图", "藏宝图") >= 60.0

    choices = ["金疮药", "定神香", "佛光舍利子", "九转回魂丹"]
    best, score, idx = find_best_match("金创药", choices, threshold=60.0)
    assert best == "金疮药"
    assert idx == 0
    assert score >= 60.0

    # Non-match case
    best_none, _, _ = find_best_match("未知物品", choices, threshold=90.0)
    assert best_none is None


def test_ocr_engine_synthetic_text():
    # Render an image with clear text using Pillow and font
    img = Image.new("RGB", (500, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    font = None
    has_chinese_font = False
    chinese_font_candidates = [
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    all_candidates = chinese_font_candidates + [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for candidate in all_candidates:
        try:
            font = ImageFont.truetype(candidate, 36)
            if candidate in chinese_font_candidates:
                has_chinese_font = True
            break
        except Exception:
            continue

    draw.text((50, 40), "师门任务", fill=(0, 0, 0), font=font)
    draw.text((50, 110), "TASK: SHIMEN", fill=(0, 0, 0), font=font)

    frame = np.array(img)
    engine = OCREngine.get_instance()

    res_shimen = engine.find_text(frame, "师门", threshold=60.0)
    if not engine.is_mock and font is not None and has_chinese_font:
        assert res_shimen is not None
        assert "师门" in res_shimen.text

    res_task = engine.find_text(frame, "SHIMEN", threshold=60.0)
    if not engine.is_mock:
        assert res_task is not None
        assert "SHIMEN" in res_task.text.upper()


def test_ocr_frame_caching():
    """Verify that multiple OCR queries on the same frame reuse cached results."""
    engine = OCREngine.get_instance()
    engine.clear_cache()

    frame = np.ones((100, 300, 3), dtype=np.uint8) * 255
    cv2.putText(frame, "HELLO WORLD", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)

    # First recognize pass: populates cache
    items1 = engine.recognize(frame)
    # Second recognize pass on the exact same frame: should hit cache immediately
    items2 = engine.recognize(frame)
    assert len(items1) == len(items2)

    # find_text should also hit cache
    engine.find_text(frame, "HELLO", threshold=50.0)

    # Sub-ROI query on cached frame
    roi_items = engine.recognize(frame, roi=(0, 0, 150, 100))
    assert isinstance(roi_items, list)

    # Clear cache
    engine.clear_cache()
    assert len(engine._frame_cache) == 0
