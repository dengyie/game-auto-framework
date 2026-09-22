"""
Humanized behavioral dynamics using cubic Bézier curves and Gaussian perturbation.
Simulates natural hand movement with acceleration, cruising, deceleration, and micro-jitter.
"""

from __future__ import annotations
import math
import random
from typing import List, Tuple

Point = Tuple[float, float]


def generate_gaussian_target(
    center_x: float,
    center_y: float,
    radius_x: float = 10.0,
    radius_y: float = 10.0,
    sigma: float = 2.5,
) -> Tuple[int, int]:
    """
    Generate a humanized target point inside a bounding area using 2D Gaussian distribution.
    Ensures points land naturally clustered near the center rather than dead center or uniform edges.
    """
    offset_x = random.gauss(0, sigma)
    offset_y = random.gauss(0, sigma)
    # Clamp within bounding box
    clamped_x = max(-radius_x, min(radius_x, offset_x))
    clamped_y = max(-radius_y, min(radius_y, offset_y))
    return int(round(center_x + clamped_x)), int(round(center_y + clamped_y))


def _cubic_bezier_point(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    """Calculate single point along cubic Bézier curve at parameter t in [0, 1]."""
    u = 1.0 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
    return (x, y)


def generate_bezier_trajectory(
    start: Point,
    end: Point,
    steps: int = 25,
    deviation_scale: float = 0.2,
    jitter_amp: float = 0.8,
) -> List[Tuple[int, int, float]]:
    """
    Generate humanized mouse / swipe movement trajectory using a cubic Bézier curve.
    
    Returns:
        List of (x, y, delay_ms) steps with physics-like Ease-In / Ease-Out timing.
    """
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    if distance < 5:
        return [(int(round(end[0])), int(round(end[1])), 10.0)]

    # Dynamic control points selection based on distance and angle
    mid_x = (start[0] + end[0]) / 2.0
    mid_y = (start[1] + end[1]) / 2.0
    normal_x = -(end[1] - start[1]) / distance
    normal_y = (end[0] - start[0]) / distance

    # Random deviation vector perpendicular to the main direction
    deviation = (random.random() * 2 - 1) * distance * deviation_scale
    p1 = (
        start[0] + (end[0] - start[0]) * 0.25 + normal_x * deviation * random.uniform(0.5, 1.2),
        start[1] + (end[1] - start[1]) * 0.25 + normal_y * deviation * random.uniform(0.5, 1.2),
    )
    p2 = (
        start[0] + (end[0] - start[0]) * 0.75 + normal_x * deviation * random.uniform(0.3, 0.9),
        start[1] + (end[1] - start[1]) * 0.75 + normal_y * deviation * random.uniform(0.3, 0.9),
    )

    trajectory: List[Tuple[int, int, float]] = []
    
    # Calculate non-linear parameter distribution (Ease-In, Ease-Out)
    for i in range(steps + 1):
        # Progress parameter with cosine easing
        raw_t = i / float(steps)
        # S-curve non-linear velocity profile
        t = 0.5 - 0.5 * math.cos(raw_t * math.pi)

        bx, by = _cubic_bezier_point(start, p1, p2, end, t)

        # Add minor natural sine jitter
        if 0 < i < steps:
            jitter = math.sin(i * 0.5) * jitter_amp * (1.0 - abs(raw_t - 0.5) * 2)
            bx += normal_x * jitter
            by += normal_y * jitter

        # Variable frame delay (slower near ends, faster in cruise phase)
        speed_factor = 1.0 + 2.0 * math.pow(math.sin(raw_t * math.pi), 2)
        step_delay = max(5.0, (15.0 / speed_factor) + random.uniform(-1.5, 1.5))

        trajectory.append((int(round(bx)), int(round(by)), step_delay))

    return trajectory
