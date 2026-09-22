"""Unit tests for CV template matching, frame diff, and battle detection."""

import numpy as np
import cv2
from core.cv.matcher import TemplateMatcher, MatchResult
from core.cv.diff import compute_dhash, calc_hamming_distance, is_frame_static, FrameDiffDetector
from core.cv.battle import BattleDetector


def test_template_matcher_synthetic():
    # Create synthetic canvas (400x300 BGR)
    canvas = np.zeros((300, 400, 3), dtype=np.uint8)
    # Draw a distinct rectangle with inner features (non-zero variance)
    cv2.rectangle(canvas, (100, 80), (140, 120), (0, 255, 0), -1)
    cv2.circle(canvas, (120, 100), 6, (0, 0, 255), -1)

    template = canvas[80:120, 100:140].copy()

    # Exact match
    res = TemplateMatcher.match(canvas, template, threshold=0.9)
    assert res.found is True
    assert res.confidence >= 0.95
    assert res.bbox == (100, 80, 40, 40)
    assert res.center == (120, 100)

    # Match with ROI containing the target
    roi_res = TemplateMatcher.match(canvas, template, threshold=0.9, roi=(50, 50, 150, 150))
    assert roi_res.found is True
    assert roi_res.center == (120, 100)

    # Match with disjoint ROI
    disjoint_res = TemplateMatcher.match(canvas, template, threshold=0.9, roi=(200, 200, 50, 50))
    assert disjoint_res.found is False


def test_template_matcher_multi_scale():
    canvas = np.zeros((300, 400, 3), dtype=np.uint8)
    cv2.circle(canvas, (200, 150), 20, (255, 255, 255), -1)

    # Template slightly smaller than canvas circle
    small_tpl = np.zeros((36, 36, 3), dtype=np.uint8)
    cv2.circle(small_tpl, (18, 18), 17, (255, 255, 255), -1)

    res = TemplateMatcher.match_multi_scale(canvas, small_tpl, threshold=0.8)
    assert res.found is True
    assert abs(res.center[0] - 200) <= 5
    assert abs(res.center[1] - 150) <= 5


def test_template_matcher_find_all():
    canvas = np.zeros((400, 600, 3), dtype=np.uint8)
    # Draw 3 distinct dots
    points = [(100, 100), (300, 100), (500, 100)]
    for pt in points:
        cv2.circle(canvas, pt, 15, (0, 0, 255), -1)

    tpl = np.zeros((30, 30, 3), dtype=np.uint8)
    cv2.circle(tpl, (15, 15), 15, (0, 0, 255), -1)

    matches = TemplateMatcher.find_all(canvas, tpl, threshold=0.85, max_count=10)
    assert len(matches) == 3


def test_frame_diff_and_dhash():
    img1 = np.ones((200, 200, 3), dtype=np.uint8) * 50
    img2 = img1.copy()
    img3 = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)

    h1 = compute_dhash(img1)
    h2 = compute_dhash(img2)
    h3 = compute_dhash(img3)

    assert calc_hamming_distance(h1, h2) == 0
    assert is_frame_static(img1, img2) is True
    assert calc_hamming_distance(h1, h3) > 5

    detector = FrameDiffDetector(max_distance=2)
    assert detector.update(img1) is True  # First frame is always new
    assert detector.update(img2) is False  # Identical frame is static
    assert detector.update(img3) is True  # Changed frame is new


def test_battle_detector():
    peace_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    battle_frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    # Simulate yellow/gold combat indicator in bottom right combat area
    cv2.rectangle(battle_frame, (1050, 550), (1200, 680), (0, 215, 255), -1)

    detector = BattleDetector(auto_battle_roi=(1000, 500, 280, 220))
    assert detector.is_in_battle(peace_frame) is False
    assert detector.is_in_battle(battle_frame) is True
