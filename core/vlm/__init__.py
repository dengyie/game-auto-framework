"""
Core VLM package: Unified Vision-Language Model perception and live anti-bot defense.
"""

from core.vlm.client import VLMClient
from core.vlm.live_solver import LiveVLMDefenseSolver

__all__ = ["VLMClient", "LiveVLMDefenseSolver"]
