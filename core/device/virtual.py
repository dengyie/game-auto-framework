"""
Virtual / Mock Device for Headless Testing, Simulation, Live Stream Monitoring and CI/CD pipelines.
Generates realistic dynamic 1280x720 simulated game frames with live HUD, task tracker,
interactive touch feedback, and telemetry overlays to prevent black-screen monitors.
"""

from __future__ import annotations
import io
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from core.device.base import BaseDevice
from core.input.driver import BaseInputDriver, VirtualInputDriver

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def _get_font(size: int = 14) -> ImageFont.ImageFont:
    """Load system font with Chinese character support or fallback to default."""
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


class VirtualDevice(BaseDevice):
    """
    Simulated device running purely in memory with rich dynamic game canvas generation.
    Supports real-time HUD, task progression, interactive touch ripple rendering, and live telemetry.
    """

    _cached_base_image: Optional[Image.Image] = None
    _base_image_lock = threading.Lock()

    def __init__(self, name: str = "virtual_mock", resolution: Tuple[int, int] = (1280, 720)) -> None:
        super().__init__(name=name, resolution=resolution)
        self._driver = VirtualInputDriver()
        self._manual_frame: Optional[bytes] = None
        self._cached_frame: Optional[bytes] = None
        self._last_frame_time: float = 0.0
        self._touch_history: List[Tuple[float, float, float, str]] = []  # (x, y, timestamp, action)
        self._touch_lock = threading.Lock()
        self._font_sm = _get_font(12)
        self._font_md = _get_font(14)
        self._font_lg = _get_font(16)

        # Character profile based on device name / ID
        self.profile = self._derive_profile(name)

    @property
    def platform_type(self) -> str:
        return "virtual"

    @property
    def input_driver(self) -> BaseInputDriver:
        return self._driver

    def _derive_profile(self, name: str) -> dict:
        """Derive role, school, and character name for realistic game stream rendering."""
        n = name.lower()
        if "inst_01" in n or "大队长" in n or "剑侠客" in n:
            return {
                "name": "剑侠客",
                "school": "大唐官府",
                "role": "队长",
                "level": 69,
                "hp_max": 3850,
                "mp_max": 1820,
                "proxy": "上海家宽 127.0.0.1:10801",
                "task": "[组队抓鬼] 正在寻路巡逻 (第 6/10 环)",
            }
        elif "inst_02" in n or "普陀" in n or "玄彩娥" in n:
            return {
                "name": "玄彩娥",
                "school": "普陀山",
                "role": "队员",
                "level": 69,
                "hp_max": 4120,
                "mp_max": 2400,
                "proxy": "上海家宽 127.0.0.1:10802",
                "task": "[组队抓鬼] 随队战斗待命",
            }
        elif "inst_03" in n or "地府" in n or "骨精灵" in n:
            return {
                "name": "骨精灵",
                "school": "阴曹地府",
                "role": "队员",
                "level": 69,
                "hp_max": 3950,
                "mp_max": 2100,
                "proxy": "上海家宽 127.0.0.1:10803",
                "task": "[组队抓鬼] 随队战斗待命",
            }
        elif "inst_04" in n or "龙宫" in n or "龙太子" in n:
            return {
                "name": "龙太子",
                "school": "龙宫",
                "role": "队员",
                "level": 69,
                "hp_max": 3100,
                "mp_max": 3150,
                "proxy": "上海家宽 127.0.0.1:10804",
                "task": "[组队抓鬼] 随队战斗待命",
            }
        elif "inst_05" in n or "狮驼" in n or "虎头怪" in n:
            return {
                "name": "虎头怪",
                "school": "狮驼岭",
                "role": "队员",
                "level": 69,
                "hp_max": 3780,
                "mp_max": 1650,
                "proxy": "上海家宽 127.0.0.1:10805",
                "task": "[组队抓鬼] 随队战斗待命",
            }
        return {
            "name": name,
            "school": "通用角色",
            "role": "独立节点",
            "level": 60,
            "hp_max": 3000,
            "mp_max": 1500,
            "proxy": "直连节点 (Local)",
            "task": "[常规日常] 状态机平稳流转",
        }

    @classmethod
    def _get_base_image(cls, target_res: Tuple[int, int]) -> Image.Image:
        """Load or procedurally generate the base game world canvas."""
        with cls._base_image_lock:
            if cls._cached_base_image is not None and cls._cached_base_image.size == target_res:
                return cls._cached_base_image.copy()

            # Try loading existing acceptance artifacts
            base_dir = Path(__file__).resolve().parent.parent.parent
            candidates = [
                base_dir / "docs" / "acceptance_artifacts" / "mhxy_after_accept.png",
                base_dir / "docs" / "acceptance_artifacts" / "03_game_title_screen.png",
                base_dir / "docs" / "acceptance_artifacts" / "register_screen.png",
            ]
            for p in candidates:
                if p.exists():
                    try:
                        loaded = Image.open(p).convert("RGB")
                        if loaded.size != target_res:
                            loaded = loaded.resize(target_res, Image.Resampling.BILINEAR)
                        cls._cached_base_image = loaded
                        return loaded.copy()
                    except Exception:
                        continue

            # Fallback: Generate attractive procedural game world canvas
            w, h = target_res
            img = Image.new("RGB", (w, h), color=(15, 23, 42))
            draw = ImageDraw.Draw(img)
            # Procedural terrain gradient
            for y in range(h):
                ratio = y / h
                r = int(18 + ratio * 20)
                g = int(24 + ratio * 35)
                b = int(38 + ratio * 50)
                draw.line([(0, y), (w, y)], fill=(r, g, b))

            # Ground paths and fantasy grid
            for x in range(0, w, 80):
                draw.line([(x, 0), (x, h)], fill=(30, 41, 59, 120))
            for y in range(0, h, 60):
                draw.line([(0, y), (w, y)], fill=(30, 41, 59, 120))

            cls._cached_base_image = img
            return img.copy()

    def record_touch(self, x: float, y: float, action: str = "tap") -> None:
        """Record interactive touch event for on-screen ripple animation."""
        now = time.time()
        with self._touch_lock:
            self._touch_history.append((float(x), float(y), now, action))
            self._touch_history = [t for t in self._touch_history if now - t[2] < 2.0][-10:]
            self._cached_frame = None  # Force immediate re-render on next frame request

    def click(self, x: float, y: float, radius: float = 6.0) -> Tuple[int, int]:
        """Execute click and record visual feedback."""
        coords = super().click(x, y, radius=radius)
        self.record_touch(coords[0], coords[1], "tap")
        return coords

    def swipe(self, sx: float, sy: float, ex: float, ey: float, steps: int = 25) -> Any:
        """Execute swipe and record visual feedback."""
        res = super().swipe(sx, sy, ex, ey, steps=steps)
        self.record_touch(ex, ey, "swipe")
        return res

    def set_mock_frame(self, image_bytes: bytes) -> None:
        """Override with a static frame (for deterministic unit tests)."""
        self._manual_frame = image_bytes
        self._cached_frame = None

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def screencap(self) -> bytes:
        """
        Capture live frame. If no manual mock frame is set, procedurally renders
        live game world scene with real-time HUD, telemetry, and touch ripples.
        """
        if not self._connected:
            raise RuntimeError(f"Device {self.name} is not connected.")

        if self._manual_frame is not None:
            return self._manual_frame

        now = time.time()
        # Cache frame for 50ms (20 FPS cap) unless a touch occurred
        if self._cached_frame is not None and (now - self._last_frame_time < 0.05):
            return self._cached_frame

        self._cached_frame = self._render_live_game_frame(now)
        self._last_frame_time = now
        return self._cached_frame

    def _render_live_game_frame(self, now: float) -> bytes:
        """Render complete in-game scene with dynamic HUD, clock, task, and touch ripples."""
        w, h = self.resolution
        frame = self._get_base_image(self.resolution)
        draw = ImageDraw.Draw(frame)

        prof = self.profile
        char_name = prof["name"]
        school = prof["school"]
        role = prof["role"]
        level = prof["level"]
        hp_max = prof["hp_max"]
        mp_max = prof["mp_max"]

        # Subtle wandering bobbing animation
        bob_offset = int(math.sin(now * 3.0) * 3)

        # -------------------------------------------------------------
        # 1. Top-Left Player HUD
        # -------------------------------------------------------------
        hud_w, hud_h = 320, 84
        draw.rectangle([12, 12, 12 + hud_w, 12 + hud_h], fill=(15, 20, 30), outline=(56, 189, 248), width=2)
        # Avatar badge
        draw.ellipse([20, 20, 72, 72], fill=(30, 41, 59), outline=(250, 204, 21), width=2)
        draw.text((32, 38), role[:2], fill=(255, 255, 255), font=self._font_md)

        # Character title & school
        title_str = f"【{school}】{char_name} (Lv.{level})"
        draw.text((82, 18), title_str, fill=(255, 215, 0), font=self._font_md)

        # HP Bar
        hp_cur = hp_max - (bob_offset * 15)
        hp_ratio = max(0.1, min(1.0, hp_cur / hp_max))
        draw.rectangle([82, 42, 310, 52], fill=(69, 10, 10))
        draw.rectangle([82, 42, int(82 + (310 - 82) * hp_ratio), 52], fill=(239, 68, 68))
        draw.text((150, 40), f"气血 {hp_cur}/{hp_max}", fill=(255, 255, 255), font=self._font_sm)

        # MP Bar
        mp_cur = mp_max
        mp_ratio = max(0.1, min(1.0, mp_cur / mp_max))
        draw.rectangle([82, 58, 310, 68], fill=(12, 44, 76))
        draw.rectangle([82, 58, int(82 + (310 - 82) * mp_ratio), 68], fill=(14, 165, 233))
        draw.text((150, 56), f"魔法 {mp_cur}/{mp_max}", fill=(255, 255, 255), font=self._font_sm)

        # -------------------------------------------------------------
        # 2. Top-Right Minimap Radar & Clock
        # -------------------------------------------------------------
        map_w, map_h = 280, 80
        mx = w - map_w - 14
        draw.rectangle([mx, 12, w - 14, 12 + map_h], fill=(15, 20, 30), outline=(56, 189, 248), width=2)
        draw.text((mx + 12, 18), f"场景: 长安城 ({230 + bob_offset}, {120 - bob_offset})", fill=(255, 215, 0), font=self._font_md)
        draw.text((mx + 12, 38), "延迟: 18ms | 帧率: 10.0 FPS", fill=(34, 197, 94), font=self._font_sm)
        live_clock = time.strftime("%Y-%m-%d %H:%M:%S")
        draw.text((mx + 12, 56), f"{live_clock}.{int((now % 1) * 10)}", fill=(148, 163, 184), font=self._font_sm)

        # -------------------------------------------------------------
        # 3. Quest Tracker Banner (Right Side)
        # -------------------------------------------------------------
        qw, qh = 280, 54
        qy = 100
        draw.rectangle([mx, qy, w - 14, qy + qh], fill=(15, 23, 42), outline=(100, 116, 139), width=1)
        draw.text((mx + 10, qy + 8), prof["task"], fill=(250, 204, 21), font=self._font_md)
        draw.text((mx + 10, qy + 28), "状态机: 自动寻路中 · 避免遇怪", fill=(226, 232, 240), font=self._font_sm)

        # -------------------------------------------------------------
        # 4. Interactive Touch Ripples Animation
        # -------------------------------------------------------------
        with self._touch_lock:
            touches = list(self._touch_history)

        for tx, ty, t_time, action in touches:
            age = now - t_time
            if 0 <= age <= 1.8:
                # Animated expansion: radius from 10 to 60px
                radius = int(12 + (age / 1.8) * 45)
                # Outer glowing ring
                draw.ellipse([tx - radius, ty - radius, tx + radius, ty + radius], outline=(250, 204, 21), width=3)
                # Inner pulse ring
                if radius > 15:
                    draw.ellipse([tx - (radius - 10), ty - (radius - 10), tx + (radius - 10), ty + (radius - 10)], outline=(56, 189, 248), width=2)
                # Crosshair
                draw.line([(tx - 15, ty), (tx + 15, ty)], fill=(255, 255, 255), width=2)
                draw.line([(tx, ty - 15), (tx, ty + 15)], fill=(255, 255, 255), width=2)
                # Text indicator
                draw.text((tx + 18, ty - 10), f"TOUCH ({int(tx)}, {int(ty)})", fill=(250, 204, 21), font=self._font_sm)

        # -------------------------------------------------------------
        # 5. Bottom Telemetry Status Bar
        # -------------------------------------------------------------
        bar_h = 32
        draw.rectangle([0, h - bar_h, w, h], fill=(15, 20, 28))
        draw.line([(0, h - bar_h), (w, h - bar_h)], fill=(56, 189, 248), width=1)
        telemetry_text = f"【节点: {self.name}】 状态: 运行正常 | 代理: {prof['proxy']} | 流协议: 实时帧驱动 | 分辨率: {w}x{h}"
        draw.text((16, h - bar_h + 8), telemetry_text, fill=(56, 189, 248), font=self._font_sm)

        buf = io.BytesIO()
        frame.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
