"""Unit tests for Bezier curve generation and Gaussian target calculation."""

import math
from core.input.bezier import generate_bezier_trajectory, generate_gaussian_target
from core.input.driver import HumanizedController, VirtualInputDriver


def test_gaussian_target_bounds():
    center_x, center_y = 500, 300
    radius_x, radius_y = 15, 15

    for _ in range(100):
        gx, gy = generate_gaussian_target(center_x, center_y, radius_x, radius_y)
        assert center_x - radius_x <= gx <= center_x + radius_x
        assert center_y - radius_y <= gy <= center_y + radius_y


def test_bezier_trajectory_smoothness():
    start = (100.0, 100.0)
    end = (600.0, 500.0)
    steps = 30

    trajectory = generate_bezier_trajectory(start, end, steps=steps)
    assert len(trajectory) == steps + 1

    # Check start and end boundaries
    first_pt = trajectory[0]
    last_pt = trajectory[-1]
    assert math.isclose(first_pt[0], start[0], abs_tol=5.0)
    assert math.isclose(first_pt[1], start[1], abs_tol=5.0)
    assert math.isclose(last_pt[0], end[0], abs_tol=5.0)
    assert math.isclose(last_pt[1], end[1], abs_tol=5.0)

    # Check that points are ordered and progressing
    for i in range(len(trajectory) - 1):
        _, _, delay = trajectory[i]
        assert delay > 0.0


def test_humanized_controller_simulation():
    virtual_driver = VirtualInputDriver()
    controller = HumanizedController(virtual_driver)

    tx, ty = controller.human_click(
        400, 300, radius_x=5, radius_y=5, press_duration_range=(0.001, 0.002), micro_drift=False
    )
    assert 390 <= tx <= 410
    assert 290 <= ty <= 310
    assert len(virtual_driver.event_log) >= 3
    assert f"DOWN({tx}, {ty})" in virtual_driver.event_log
    assert f"UP({tx}, {ty})" in virtual_driver.event_log
