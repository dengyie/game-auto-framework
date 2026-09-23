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
        """Procedurally generate the base game world canvas with architectural backdrop and river."""
        with cls._base_image_lock:
            if cls._cached_base_image is not None and cls._cached_base_image.size == target_res:
                return cls._cached_base_image.copy()

            w, h = target_res
            img = Image.new("RGB", (w, h), color=(15, 20, 30))
            draw = ImageDraw.Draw(img)

            # 1. Sky & Horizon Gradient
            for y in range(220):
                ratio = y / 220.0
                r = int(10 + ratio * 20)
                g = int(14 + ratio * 25)
                b = int(28 + ratio * 35)
                draw.line([(0, y), (w, y)], fill=(r, g, b))

            # 2. Far mountain silhouette & City Wall
            draw.polygon([(0, 180), (200, 130), (450, 190), (700, 120), (950, 170), (1280, 140), (1280, 220), (0, 220)], fill=(22, 32, 48))

            # 3. Ground Cobblestone and Paving
            for y in range(220, h - 32):
                ratio = (y - 220.0) / max(1.0, (h - 220.0 - 32.0))
                r = int(30 + ratio * 25)
                g = int(38 + ratio * 30)
                b = int(50 + ratio * 35)
                draw.line([(0, y), (w, y)], fill=(r, g, b))

            # Cobblestone tile grid
            for gx in range(0, w, 70):
                draw.line([(gx, 220), (gx, h - 32)], fill=(40, 50, 65, 80))
            for gy in range(220, h - 32, 45):
                draw.line([(0, gy), (w, gy)], fill=(40, 50, 65, 80))

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
        """Render complete in-game scene with dynamic 2.5D RPG world, exploration/combat cycling, HUD, and touch ripples."""
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
        # 1. Ancient City Buildings & Canal Landscape
        # -------------------------------------------------------------
        # Ancient pavilions (Chang'an Inn & Tang Sect)
        draw.rectangle([80, 120, 260, 220], fill=(35, 25, 30))
        draw.polygon([(60, 130), (170, 70), (280, 130), (260, 135), (170, 85), (80, 135)], fill=(180, 83, 9))
        draw.text((120, 150), "【长安城客栈】", fill=(250, 204, 21), font=self._font_md)

        draw.rectangle([920, 110, 1140, 220], fill=(30, 28, 38))
        draw.polygon([(900, 120), (1030, 60), (1160, 120), (1140, 125), (1030, 75), (920, 125)], fill=(180, 83, 9))
        draw.text((960, 140), "【大唐官府分舵】", fill=(250, 204, 21), font=self._font_md)

        # Canal River across center-bottom with animated water waves
        water_y = 520
        draw.rectangle([0, water_y, w, water_y + 60], fill=(20, 65, 95))
        wave_shift = int((now * 40) % 60)
        for wx in range(-60, w + 60, 60):
            draw.arc([wx + wave_shift, water_y + 15, wx + wave_shift + 40, water_y + 35], 0, 180, fill=(56, 189, 248), width=2)

        # Stone Bridge over canal
        draw.rectangle([560, water_y - 15, 720, water_y + 75], fill=(71, 85, 105), outline=(148, 163, 184), width=2)
        for bx in range(570, 715, 25):
            draw.rectangle([bx, water_y - 20, bx + 15, water_y - 10], fill=(100, 116, 139))
        draw.text((615, water_y + 15), "【青龙石桥】", fill=(255, 255, 255), font=self._font_sm)

        # -------------------------------------------------------------
        # 2. Dynamic RPG State Cycling: Exploration (16s) vs Battle (14s)
        # -------------------------------------------------------------
        cycle = now % 30.0
        is_battle = cycle >= 16.0

        if not is_battle:
            # Exploration Mode: 5-man Team Walking along Path towards NPC
            t_phase = now * 0.7
            lx = 420 + int(math.sin(t_phase) * 220)
            ly = 360 + int(math.cos(t_phase) * 70)

            # Quest target NPC: Zhong Kui
            npc_x, npc_y = 920, 310
            draw.ellipse([npc_x - 18, npc_y - 36, npc_x + 18, npc_y], fill=(168, 85, 247), outline=(250, 204, 21), width=2)
            draw.rectangle([npc_x - 12, npc_y, npc_x + 12, npc_y + 30], fill=(88, 28, 135))
            draw.text((npc_x - 45, npc_y - 56), "【NPC】钟馗 (抓鬼使者)", fill=(250, 204, 21), font=self._font_md)
            # Pulsing exclamation mark
            ex_bob = int(math.sin(now * 5.0) * 5)
            draw.text((npc_x - 4, npc_y - 82 + ex_bob), "!", fill=(239, 68, 68), font=self._font_lg)

            # Navigation dotted line
            draw.line([(lx, ly), (npc_x, npc_y + 15)], fill=(250, 204, 21), width=2)

            # 5 Characters marching
            chars = [
                ("剑侠客", "大唐", "队长", (239, 68, 68), 0, 0),
                ("玄彩娥", "普陀", "队员", (56, 189, 248), -50, 20),
                ("骨精灵", "地府", "队员", (168, 85, 247), -95, 40),
                ("龙太子", "龙宫", "队员", (59, 130, 246), -140, 60),
                ("虎头怪", "狮驼", "队员", (234, 179, 8), -185, 80),
            ]
            for c_name, c_sect, c_role, color, ox, oy in chars:
                cx = lx + ox
                cy = ly + oy
                bob = int(math.sin(now * 6.0 + ox * 0.1) * 4)

                # Shadow
                draw.ellipse([cx - 20, cy + 22, cx + 20, cy + 32], fill=(10, 15, 22))
                # Body & Cloak
                draw.rectangle([cx - 14, cy - 10 + bob, cx + 14, cy + 24 + bob], fill=color, outline=(255, 255, 255), width=1)
                # Head
                draw.ellipse([cx - 15, cy - 36 + bob, cx + 15, cy - 6 + bob], fill=(254, 215, 170), outline=color, width=2)
                # Name & Sect
                draw.text((cx - 36, cy - 54 + bob), f"【{c_sect}】{c_name}", fill=(255, 255, 255), font=self._font_sm)
                if c_role == "队长":
                    draw.text((cx - 18, cy - 70 + bob), "【队长】", fill=(250, 204, 21), font=self._font_sm)

        else:
            # Battle Mode: Turn-based Encounter
            # Magic array circle in background
            draw.ellipse([250, 220, 1050, 500], outline=(147, 51, 234), width=3)
            draw.ellipse([270, 235, 1030, 485], outline=(59, 130, 246), width=1)
            draw.text((580, 230), "【八卦伏魔阵】", fill=(192, 132, 252), font=self._font_md)

            # Left: 5 Players in combat formation
            team_coords = [
                ("剑侠客", "大唐", (380, 310), (239, 68, 68)),
                ("玄彩娥", "普陀", (310, 240), (56, 189, 248)),
                ("骨精灵", "地府", (310, 380), (168, 85, 247)),
                ("龙太子", "龙宫", (240, 180), (59, 130, 246)),
                ("虎头怪", "狮驼", (240, 450), (234, 179, 8)),
            ]
            for t_name, t_sect, (px, py), col in team_coords:
                t_bob = int(math.sin(now * 4.0 + px) * 3)
                draw.ellipse([px - 22, py + 24, px + 22, py + 34], fill=(10, 15, 25))
                draw.rectangle([px - 14, py - 10 + t_bob, px + 14, py + 24 + t_bob], fill=col, outline=(255, 255, 255), width=1)
                draw.ellipse([px - 15, py - 36 + t_bob, px + 15, py - 6 + t_bob], fill=(254, 215, 170), outline=col, width=2)
                draw.text((px - 32, py - 52 + t_bob), f"【{t_sect}】{t_name}", fill=(255, 255, 255), font=self._font_sm)

            # Right: Monster Boss & Minions
            monsters = [
                ("吸血鬼王 (主怪)", (820, 310), (220, 38, 38), 35),
                ("幽灵·先锋", (890, 230), (107, 114, 128), 24),
                ("千年僵尸·头目", (890, 390), (13, 148, 136), 28),
                ("野鬼·护法", (960, 310), (107, 114, 128), 24),
            ]
            for m_name, (mx, my), m_col, m_size in monsters:
                m_bob = int(math.sin(now * 5.0 + mx) * 4)
                draw.ellipse([mx - m_size, my + m_size - 8, mx + m_size, my + m_size + 4], fill=(5, 5, 10))
                draw.ellipse([mx - m_size + 4, my - m_size + m_bob, mx + m_size - 4, my + m_size + m_bob], fill=m_col, outline=(250, 204, 21), width=2)
                draw.text((mx - 48, my - m_size - 22 + m_bob), f"【{m_name}】", fill=(248, 113, 113), font=self._font_sm)

            # Floating combat damage numbers
            hit_bob = int((now * 25) % 30)
            draw.text((810, 260 - hit_bob), "暴击 -5,840!", fill=(239, 68, 68), font=self._font_lg)
            draw.text((880, 190 - hit_bob), "-2,410", fill=(250, 204, 21), font=self._font_md)
            draw.text((370, 260 - hit_bob), "普渡众生 +1,280", fill=(34, 197, 94), font=self._font_md)

            # Action attack slash line
            draw.line([(400, 310), (810, 310)], fill=(250, 204, 21), width=4)
            draw.line([(800, 290), (840, 330)], fill=(255, 255, 255), width=3)
            draw.line([(840, 290), (800, 330)], fill=(255, 255, 255), width=3)

            # Battle timer banner
            draw.rectangle([540, 90, 740, 125], fill=(15, 23, 42), outline=(239, 68, 68), width=2)
            draw.text((555, 96), "⚔️ 回合战斗对抗中 (倒计时 14s)", fill=(250, 204, 21), font=self._font_md)

        # -------------------------------------------------------------
        # 3. Bottom-Left In-game Chat Box
        # -------------------------------------------------------------
        chat_w, chat_h = 360, 150
        chat_y = h - chat_h - 40
        draw.rectangle([16, chat_y, 16 + chat_w, chat_y + chat_h], fill=(15, 23, 42), outline=(56, 189, 248), width=1)
        # Chat Tabs
        draw.rectangle([16, chat_y, 16 + chat_w, chat_y + 26], fill=(30, 41, 59))
        draw.text((26, chat_y + 5), "【当前】  【队伍】  【帮派】  【世界】", fill=(148, 163, 184), font=self._font_sm)
        # Chat messages
        draw.text((26, chat_y + 34), "【系统】玩家 剑侠客 抓鬼获得了 五宝·金刚石*1", fill=(250, 204, 21), font=self._font_sm)
        draw.text((26, chat_y + 56), "【世界】白衣大侠: 69级抓鬼来暴力输出 4等1进组秒开+", fill=(226, 232, 240), font=self._font_sm)
        draw.text((26, chat_y + 78), "【队伍】玄彩娥: 队长辛苦，已挂机普陀点灯~", fill=(56, 189, 248), font=self._font_sm)
        draw.text((26, chat_y + 100), "【帮派】逍遥书生: 今晚8点帮战准时集合，全员带药", fill=(192, 132, 252), font=self._font_sm)
        draw.text((26, chat_y + 122), "【队伍】骨精灵: 阎罗令持续群攻中，稳过！", fill=(56, 189, 248), font=self._font_sm)

        # -------------------------------------------------------------
        # 4. Bottom-Right Action Hotbar (Skills & Spells)
        # -------------------------------------------------------------
        bar_w, bar_h = 380, 64
        bar_x = w - bar_w - 16
        bar_y = h - bar_h - 40
        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], fill=(15, 23, 42), outline=(250, 204, 21), width=1)
        skills = [("普攻", (239, 68, 68)), ("法术", (56, 189, 248)), ("特技", (168, 85, 247)), ("道具", (234, 179, 8)), ("防御", (107, 114, 128)), ("自动", (34, 197, 94))]
        for i, (s_name, s_col) in enumerate(skills):
            bx = bar_x + 18 + i * 60
            by = bar_y + 12
            draw.ellipse([bx, by, bx + 40, by + 40], fill=s_col, outline=(255, 255, 255), width=1)
            draw.text((bx + 8, by + 12), s_name, fill=(255, 255, 255), font=self._font_sm)

        # -------------------------------------------------------------
        # 5. Top-Left Player HUD
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
        # 6. Top-Right Minimap Radar & Clock
        # -------------------------------------------------------------
        map_w, map_h = 280, 80
        mx = w - map_w - 14
        draw.rectangle([mx, 12, w - 14, 12 + map_h], fill=(15, 20, 30), outline=(56, 189, 248), width=2)
        coord_x = 230 + int(math.sin(now * 0.7) * 20)
        coord_y = 120 - int(math.cos(now * 0.7) * 15)
        draw.text((mx + 12, 18), f"场景: 长安城 ({coord_x}, {coord_y})", fill=(255, 215, 0), font=self._font_md)
        draw.text((mx + 12, 38), "延迟: 18ms | 帧率: 10.0 FPS", fill=(34, 197, 94), font=self._font_sm)
        live_clock = time.strftime("%Y-%m-%d %H:%M:%S")
        draw.text((mx + 12, 56), f"{live_clock}.{int((now % 1) * 10)}", fill=(148, 163, 184), font=self._font_sm)

        # -------------------------------------------------------------
        # 7. Quest Tracker Banner (Right Side)
        # -------------------------------------------------------------
        qw, qh = 280, 54
        qy = 100
        draw.rectangle([mx, qy, w - 14, qy + qh], fill=(15, 23, 42), outline=(100, 116, 139), width=1)
        draw.text((mx + 10, qy + 8), prof["task"], fill=(250, 204, 21), font=self._font_md)
        status_text = "状态机: 回合战斗对抗中" if is_battle else "状态机: 自动寻路巡逻中"
        draw.text((mx + 10, qy + 28), status_text, fill=(226, 232, 240), font=self._font_sm)

        # -------------------------------------------------------------
        # 8. Interactive Touch Ripples Animation
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
        # 9. Bottom Telemetry Status Bar
        # -------------------------------------------------------------
        bar_h = 32
        draw.rectangle([0, h - bar_h, w, h], fill=(15, 20, 28))
        draw.line([(0, h - bar_h), (w, h - bar_h)], fill=(56, 189, 248), width=1)
        telemetry_text = f"【节点: {self.name}】 状态: 运行正常 | 代理: {prof['proxy']} | 流协议: 实时帧驱动 | 分辨率: {w}x{h}"
        draw.text((16, h - bar_h + 8), telemetry_text, fill=(56, 189, 248), font=self._font_sm)

        buf = io.BytesIO()
        frame.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
