"""
In-memory and external question bank with RapidFuzz solver for MHXY Mobile daily trivia.
Supports Keju (科举), Sanjie Qiyuan (三界奇缘), and anti-bot simple text challenges.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger
from rapidfuzz import fuzz, process

from core.ocr.fuzzy import find_best_match


BUILTIN_QUESTION_BANK: List[Dict[str, str]] = [
    {"q": "孙悟空的授业恩师是谁", "a": "菩提祖师"},
    {"q": "大唐官府的门派师傅是谁", "a": "程咬金"},
    {"q": "化生寺的门派师傅是谁", "a": "空度禅师"},
    {"q": "普陀山的门派师傅是谁", "a": "观音菩萨"},
    {"q": "阴曹地府的门派师傅是谁", "a": "地藏王"},
    {"q": "龙宫的门派师傅是谁", "a": "东海龙王"},
    {"q": "魔王寨的门派师傅是谁", "a": "牛魔王"},
    {"q": "狮驼岭的门派师傅是谁", "a": "大大王"},
    {"q": "方寸山的门派师傅是谁", "a": "菩提祖师"},
    {"q": "宝图任务找谁接取", "a": "店小二"},
    {"q": "运镖任务找谁接取", "a": "郑镖头"},
    {"q": "每天可以完成多少个双倍高额奖励师门任务", "a": "20"},
    {"q": "藏宝图每天最多可以打几张", "a": "10"},
    {"q": "运镖任务每天可以完成几次", "a": "3"},
    {"q": "玄奘法师俗家姓名叫什么", "a": "陈祎"},
    {"q": "玄奘的父亲是谁", "a": "陈光蕊"},
    {"q": "小白龙因何被贬西鹰涧", "a": "纵火烧了殿上明珠"},
    {"q": "猪八戒在高老庄叫什么名字", "a": "猪刚鬣"},
    {"q": "沙和尚在流沙河使用的兵器是", "a": "降妖宝杖"},
    {"q": "红孩儿的父亲是谁", "a": "牛魔王"},
    {"q": "红孩儿的母亲是谁", "a": "铁扇公主"},
    {"q": "金箍棒原本在大禹治水时叫什么", "a": "定海神针铁"},
    {"q": "三界奇缘每天可以回答多少道题目", "a": "10"},
    {"q": "科举乡试一共多少道题", "a": "20"},
    {"q": "大唐官府的首席大弟子在哪个城市", "a": "长安城"},
    {"q": "金疮药可以恢复什么", "a": "气血"},
    {"q": "定神香可以恢复什么", "a": "魔法"},
    {"q": "九转回魂丹的作用是什么", "a": "复活并恢复气血"},
    {"q": "佛光舍利子的作用是什么", "a": "复活队友"},
]


class QuizSolver:
    """Intelligent QA solver that fuzzy-matches questions and maps to OCR options."""

    def __init__(self, external_bank_path: Optional[Union[str, Path]] = None) -> None:
        self.bank: List[Dict[str, str]] = list(BUILTIN_QUESTION_BANK)
        if external_bank_path:
            self._load_external_bank(Path(external_bank_path))

    def _load_external_bank(self, path: Path) -> None:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.bank.extend(data)
                        logger.info(f"Loaded {len(data)} trivia QA entries from {path}")
            except Exception as e:
                logger.error(f"Failed to load external question bank: {e}")

    def solve(
        self,
        question_text: str,
        options: List[str],
        question_threshold: float = 60.0,
    ) -> Tuple[int, str, float]:
        """Given OCR-scraped question and candidate options, find the best matching choice.

        Returns:
            Tuple of (option_index [0..N-1], chosen_option_text, confidence_score [0..1.0])
        """
        if not options:
            return -1, "", 0.0

        cleaned_q = question_text.replace("?", "").replace("？", "").replace(" ", "")

        # 1. Fuzzy match question against the question bank
        questions = [entry["q"] for entry in self.bank]
        best_q_match = process.extractOne(
            cleaned_q,
            questions,
            scorer=fuzz.partial_ratio,
            score_cutoff=question_threshold,
        )

        if best_q_match:
            matched_q, q_score, q_idx = best_q_match
            canonical_answer = self.bank[q_idx]["a"]
            logger.debug(f"Matched Question ({q_score:.1f}%): '{matched_q}' -> Canonical Answer: '{canonical_answer}'")

            # 2. Fuzzy match canonical answer against OCR option texts
            best_opt, opt_score, opt_idx = find_best_match(
                canonical_answer, options, threshold=40.0
            )

            if best_opt is not None:
                confidence = (q_score / 100.0) * 0.5 + (opt_score / 100.0) * 0.5
                return opt_idx, best_opt, confidence

        # 3. Fallback: If no match found in bank, pick first non-empty option or option 1 (B) as classic default
        logger.warning(f"Question not found in bank: '{question_text}'. Using fallback choice.")
        fallback_idx = min(1, len(options) - 1)
        return fallback_idx, options[fallback_idx], 0.25
