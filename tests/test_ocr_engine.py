"""Unit tests for OCR engine and RapidFuzz text matching."""

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
    for candidate in [
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            font = ImageFont.truetype(candidate, 36)
            break
        except Exception:
            continue

    draw.text((50, 40), "师门任务", fill=(0, 0, 0), font=font)
    draw.text((50, 110), "TASK: SHIMEN", fill=(0, 0, 0), font=font)

    frame = np.array(img)
    engine = OCREngine.get_instance()

    res_shimen = engine.find_text(frame, "师门", threshold=60.0)
    if not engine.is_mock and font is not None:
        assert res_shimen is not None
        assert "师门" in res_shimen.text

    res_task = engine.find_text(frame, "SHIMEN", threshold=60.0)
    if not engine.is_mock:
        assert res_task is not None
        assert "SHIMEN" in res_task.text.upper()
