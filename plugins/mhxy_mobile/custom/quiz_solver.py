"""
Local deterministic quiz engine (`quiz_solver.py`) for MHXY Mobile 科举/三界奇缘.

Upstream lineage (Milestone 7 doctrine: borrow from the reference projects, do not
reinvent — see 开发文档 17.2):
- 0xn0ne/MHXYExamAssistant      : SQLite question/answer bank + exam corpus (838 条).
- gitlihang/Maa_MHXY_MG         : tiku.txt multi-answer bank (393 条), text
                                  normalization rules, OCR misread replacement
                                  table, and the 80-point confidence policy.
- kslf-interest/mhxy_exam_answer: JS [question, answer] bank (446 条).
- PilyTang/XYQQuiz              : PC 科举 corpus with pre-normalized fields (2586 条).

Zero-model-token contract: 100% offline SQLite + RapidFuzz, millisecond lookups.
Tier-2 VLM escalation is the CALLER's decision (see daily_handlers.handle_quiz);
this module never performs network or model calls.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from loguru import logger
from rapidfuzz import fuzz, process

from core.ocr.fuzzy import find_best_match

_DATA_DIR = Path(__file__).parent / "data"
_SOURCES_DIR = _DATA_DIR / "quiz_sources"
_DEFAULT_DB_PATH = _DATA_DIR / "mhxy_quiz_bank.db"

# --- text normalization (borrowed from Maa_MHXY_MG searchAnswer.normalize_text) --
_PUNCT_RE = re.compile(r"[，,、。！？?!：:；;“”\"'‘’（）()【】《》<>「」『』\[\]\-·—…～~\s\t\r\n]+")

# Upstream OCR misread replacement table (game font quirks observed by Maa_MHXY_MG)
OCR_REPLACE_TABLE: Tuple[Tuple[str, str], ...] = (
    ("味", "昧"),
    ("邮", "邺"),
    ("尺", "尸"),
    ("频", "濒"),
    ("铜", "锢"),
)

# Question index / progress markers, e.g. "第12题：" "（3/10）" (upstream reco_sjqy)
_QUIZ_MARKER_RE = re.compile(r"第\d+题[：:]?|[（(]\d+\s*/\s*\d+[）)]")


def normalize_text(text: str) -> str:
    """NFKC + lowercase + strip punctuation/whitespace for deterministic matching."""
    if not text:
        return ""
    return _PUNCT_RE.sub("", unicodedata.normalize("NFKC", text).lower())


def fix_ocr_noise(text: str) -> str:
    """Apply the upstream OCR misread replacement table (三昧真火 not 三味真火...)."""
    for wrong, right in OCR_REPLACE_TABLE:
        text = text.replace(wrong, right)
    return text


def clean_question_text(text: str) -> str:
    """Strip question index / progress markers from an assembled question string."""
    return _QUIZ_MARKER_RE.sub("", text or "").strip()


# --- upstream bank format parsers -------------------------------------------------
#
# All parsers return a list of (question_raw, [valid answers, ...]) tuples.


def parse_tiku_txt(path: Union[str, Path]) -> List[Tuple[str, List[str]]]:
    """Maa_MHXY_MG tiku.txt format: "question":["a","b"] lines (upstream loader regex)."""
    content = Path(path).read_text(encoding="utf-8")
    entries: List[Tuple[str, List[str]]] = []
    for question, answers in re.findall(r'"\s*([^"]+)\s*"\s*:\s*\[\s*([^\]]*?)\s*\]', content):
        parsed = re.findall(r'"([^"]+)"', answers)
        if not parsed:
            parsed = [a.strip().strip('"') for a in answers.split(",") if a.strip()]
        # upstream: answers merged by 中文逗号 are actually multiple valid answers
        expanded: List[str] = []
        for ans in parsed:
            expanded.extend([p.strip() for p in ans.split("，")] if "，" in ans else [ans])
        if question and expanded:
            entries.append((question, expanded))
    return entries


def parse_js_pairs(path: Union[str, Path]) -> List[Tuple[str, List[str]]]:
    """mhxy_exam_answer answer.js format: [['question', 'answer'], ...]."""
    content = Path(path).read_text(encoding="utf-8")
    return [
        (q, [a])
        for q, a in re.findall(r"\[\s*'([^']+)'\s*,\s*'([^']+)'\s*\]", content)
        if q and a
    ]


def parse_keju_json(path: Union[str, Path]) -> List[Tuple[str, List[str]]]:
    """XYQQuiz keju_questions.json format: [{question, answer, ...}, ...]."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        (it["question"], [it["answer"]])
        for it in data
        if isinstance(it, dict) and it.get("question") and it.get("answer")
    ]


def parse_sqlite_bank(path: Union[str, Path]) -> List[Tuple[str, List[str]]]:
    """MHXYExamAssistant database.db format: question(question TEXT, answer TEXT)."""
    conn = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT question, answer FROM question").fetchall()
    finally:
        conn.close()
    return [(q, [a]) for q, a in rows if q and a]


_SOURCE_LOADERS: Tuple[Tuple[str, str, str, str], ...] = (
    # (file name, parser kind, source tag, category)
    ("mhxy_exam_assistant.db", "sqlite", "exam_assistant", "mobile"),
    ("maa_mhxy_mg_tiku.txt", "tiku", "maa_mhxy_mg", "mobile"),
    ("mhxy_exam_answer_bank.js", "js", "mhxy_exam_answer", "mobile"),
    ("xyq_keju_questions.json", "keju_json", "xyq_quiz", "pc_keju"),
)
_PARSERS = {
    "sqlite": parse_sqlite_bank,
    "tiku": parse_tiku_txt,
    "js": parse_js_pairs,
    "keju_json": parse_keju_json,
}


class QuizBank:
    """SQLite-backed MHXY trivia bank: multi-answer aware, dedup by normalized question."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None, auto_seed: bool = True) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._ensure_schema()
        if auto_seed and self.count() == 0:
            added, skipped = self.import_sources()
            logger.info(f"[quiz_bank] auto-seeded {added} questions from vendored upstream sources ({skipped} duplicates skipped)")

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    q_norm TEXT NOT NULL UNIQUE,
                    q_raw TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    answers_json TEXT NOT NULL DEFAULT '[]',
                    category TEXT NOT NULL DEFAULT 'general',
                    source TEXT NOT NULL DEFAULT 'import'
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_source ON questions(source)")
            self._conn.commit()

    def add_question(
        self,
        q_raw: str,
        answers: Sequence[str],
        category: str = "general",
        source: str = "import",
    ) -> bool:
        """Insert one question; returns False when empty or a duplicate (q_norm)."""
        q_raw = (q_raw or "").strip()
        clean_answers = [a.strip() for a in (answers or []) if a and a.strip()]
        q_norm = normalize_text(q_raw)
        if not q_norm or not clean_answers:
            return False
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO questions (q_norm, q_raw, answer, answers_json, category, source) VALUES (?,?,?,?,?,?)",
                (q_norm, q_raw, clean_answers[0], json.dumps(clean_answers, ensure_ascii=False), category, source),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def add_many(
        self, rows: Sequence[Tuple[str, Sequence[str], str, str]]
    ) -> Tuple[int, int]:
        """Bulk insert [(q_raw, answers, category, source)]; returns (added, skipped)."""
        rows = list(rows)
        seen = set()
        payload = []
        for q_raw, answers, category, source in rows:
            q_raw = (q_raw or "").strip()
            clean_answers = [a.strip() for a in (answers or []) if a and a.strip()]
            q_norm = normalize_text(q_raw)
            if not q_norm or not clean_answers or q_norm in seen:
                continue
            seen.add(q_norm)
            payload.append(
                (q_norm, q_raw, clean_answers[0], json.dumps(clean_answers, ensure_ascii=False), category, source)
            )
        with self._lock:
            before = self.count()
            self._conn.executemany(
                "INSERT OR IGNORE INTO questions (q_norm, q_raw, answer, answers_json, category, source) VALUES (?,?,?,?,?,?)",
                payload,
            )
            self._conn.commit()
            added = self.count() - before
        return added, max(len(rows) - added, 0)

    def import_sources(self, sources_dir: Optional[Union[str, Path]] = None) -> Tuple[int, int]:
        """Import all vendored upstream banks; returns (added, skipped)."""
        root = Path(sources_dir) if sources_dir else _SOURCES_DIR
        rows: List[Tuple[str, Sequence[str], str, str]] = []
        for fname, kind, source, category in _SOURCE_LOADERS:
            path = root / fname
            if not path.exists():
                logger.warning(f"[quiz_bank] upstream source missing, skipped: {path}")
                continue
            entries = _PARSERS[kind](path)
            rows.extend((q, a, category, source) for q, a in entries)
            logger.info(f"[quiz_bank] parsed {len(entries):4d} entries from [{source}] {fname}")
        return self.add_many(rows)

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT count(*) FROM questions").fetchone()[0])

    def count_by_source(self) -> Dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT source, count(*) FROM questions GROUP BY source").fetchall()
        return {source: int(n) for source, n in rows}

    def load_all(self) -> List[Tuple[str, str, str]]:
        """Rows of (q_norm, q_raw, answers_json) ordered by id."""
        with self._lock:
            return self._conn.execute(
                "SELECT q_norm, q_raw, answers_json FROM questions ORDER BY id"
            ).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


@dataclass
class QuizDecision:
    """Result of one local quiz lookup (zero token, fully deterministic)."""

    option_index: int = -1        # -1 = no mappable option on screen
    option_text: str = ""
    confidence: float = 0.0       # 0.0 ~ 0.98 blended question/option confidence
    bank_hit: bool = False
    matched_question: str = ""    # canonical bank question (raw text)
    question_score: float = 0.0   # 0 ~ 100 RapidFuzz similarity
    option_score: float = 0.0     # 0 ~ 100 option mapping similarity
    source: str = "miss"          # exact | fuzzy | fuzzy_low | miss
    elapsed_ms: float = 0.0
    answers: List[str] = field(default_factory=list)  # every valid bank answer, not just the one mapped on screen


class QuizSolver:
    """Zero-token local quiz solver: normalized exact index + RapidFuzz fuzzy match.

    Matching policy borrowed from Maa_MHXY_MG `searchAnswer` (exact -> similarity,
    with a low-confidence band logged but not auto-clicked), upgraded to RapidFuzz
    for millisecond latency, with the exam-grade threshold raised from upstream's
    70 to the 0.82 spec in 开发文档 17.8.
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        auto_seed: bool = True,
        question_threshold: float = 82.0,
        low_band_threshold: float = 70.0,
        option_threshold: float = 55.0,
    ) -> None:
        self.bank = QuizBank(db_path=db_path, auto_seed=auto_seed)
        self.question_threshold = question_threshold
        self.low_band_threshold = low_band_threshold
        self.option_threshold = option_threshold
        self._cache: Dict[str, QuizDecision] = {}
        self._cache_cap = 512
        self.reload()

    def reload(self) -> None:
        rows = self.bank.load_all()
        self._q_norms = [r[0] for r in rows]
        self._raw_by_norm = {r[0]: r[1] for r in rows}
        self._answers_by_norm: Dict[str, List[str]] = {}
        for r in rows:
            try:
                answers = json.loads(r[2])
            except (TypeError, ValueError):
                answers = []
            self._answers_by_norm[r[0]] = answers if answers else []
        self._cache.clear()
        logger.info(f"[quiz_solver] loaded {len(self._q_norms)} questions from {self.bank.db_path}")

    @property
    def size(self) -> int:
        return len(self._q_norms)

    def import_bank(self, path: Union[str, Path], source: Optional[str] = None) -> Tuple[int, int]:
        """Import an external bank file (auto-detects .db/.txt/.js/.json) and reload."""
        path = Path(path)
        kind = source or path.suffix.lower()
        parser = {
            ".db": parse_sqlite_bank,
            ".sqlite": parse_sqlite_bank,
            ".txt": parse_tiku_txt,
            ".js": parse_js_pairs,
            ".json": parse_keju_json,
        }.get(kind)
        if parser is None:
            raise ValueError(f"Unsupported question bank format: {path}")
        entries = parser(path)
        added, skipped = self.bank.add_many(
            (q, a, "external", path.stem) for q, a in entries
        )
        self.reload()
        logger.info(f"[quiz_solver] imported {added} questions from {path.name} ({skipped} duplicates)")
        return added, skipped

    def answer(self, question_text: str, options: Sequence[str]) -> QuizDecision:
        """Match an OCR-scraped question against the bank and map the answer to options."""
        t0 = time.perf_counter()
        decision = self._match(question_text, list(options or []))
        decision.elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return decision

    def _match(self, question_text: str, options: List[str]) -> QuizDecision:
        q_norm = normalize_text(question_text or "")
        if not q_norm:
            return QuizDecision(source="miss", matched_question=question_text or "")

        cached = self._cache.get(q_norm)
        if cached is not None:
            decision = QuizDecision(
                option_index=cached.option_index,
                option_text=cached.option_text,
                confidence=cached.confidence,
                bank_hit=cached.bank_hit,
                matched_question=cached.matched_question,
                question_score=cached.question_score,
                option_score=cached.option_score,
                source=cached.source,
            )
            return self._map_options(decision, options)

        # 1) Exact normalized hit (upstream "精确匹配")
        canonical = q_norm if q_norm in self._answers_by_norm else None
        q_score = 100.0
        source = "exact"

        # 2) Fuzzy hit (RapidFuzz full-ratio, exam-grade threshold)
        if canonical is None:
            res = process.extractOne(
                q_norm, self._q_norms, scorer=fuzz.ratio, score_cutoff=self.question_threshold
            )
            source = "fuzzy"
            if res is None:
                # 3) Low-confidence band: reported for logging/online expansion, never
                #    auto-clicked silently (mirrors upstream's <80 policy).
                res = process.extractOne(
                    q_norm, self._q_norms, scorer=fuzz.ratio, score_cutoff=self.low_band_threshold
                )
                source = "fuzzy_low"
            if res is None:
                decision = QuizDecision(source="miss", matched_question=question_text or "")
                self._cache_put(q_norm, decision)
                return self._map_options(decision, options)
            canonical, q_score, _idx = res

        decision = QuizDecision(
            bank_hit=True,
            matched_question=self._raw_by_norm.get(canonical, canonical),
            question_score=float(q_score),
            source=source,
        )
        if source == "fuzzy_low":
            logger.info(f"[quiz_solver] low-band match ({q_score:.0f}): '{decision.matched_question}'")
        self._cache_put(q_norm, decision)
        return self._map_options(decision, options)

    def _map_options(self, decision: QuizDecision, options: List[str]) -> QuizDecision:
        """Map the canonical answers onto on-screen options; blends final confidence."""
        if not decision.bank_hit:
            return decision

        answers = self._answers_by_norm.get(normalize_text(decision.matched_question), [])
        decision.answers = list(answers)
        if not options or not answers:
            decision.confidence = round(0.55 * (decision.question_score / 100.0), 4)
            return decision

        best_score, best_idx, best_opt = 0.0, -1, ""
        for ans in answers:
            opt, score, idx = find_best_match(ans, options, threshold=self.option_threshold)
            if opt is not None and score > best_score:
                best_score, best_idx, best_opt = float(score), idx, opt
        decision.option_score = best_score
        decision.option_index = best_idx
        decision.option_text = best_opt
        if best_idx >= 0:
            decision.confidence = round(
                min(0.98, 0.55 * (decision.question_score / 100.0) + 0.45 * (best_score / 100.0)), 4
            )
        else:
            # Bank hit but none of the answers matched an on-screen option (OCR issue)
            decision.confidence = round(0.55 * (decision.question_score / 100.0) * 0.6, 4)
        return decision

    def _cache_put(self, q_norm: str, decision: QuizDecision) -> None:
        if len(self._cache) >= self._cache_cap:
            self._cache.clear()
        self._cache[q_norm] = decision

    def solve(
        self,
        question_text: str,
        options: List[str],
        question_threshold: float = 60.0,
    ) -> Tuple[int, str, float]:
        """Legacy-compatible API (custom/quiz.py): returns (option_index, option_text, confidence).

        Bank miss falls back to the FIRST option with 0.25 confidence — the upstream
        Maa_MHXY_MG policy for unanswered questions.
        """
        decision = self.answer(question_text, options)
        if decision.bank_hit and decision.option_index >= 0:
            return decision.option_index, decision.option_text, max(decision.confidence, 0.6)
        if not options:
            return -1, "", 0.0
        return 0, options[0], 0.25


_default_solver: Optional[QuizSolver] = None
_default_lock = threading.Lock()


def get_default_solver() -> QuizSolver:
    """Process-wide default solver (auto-seeded from the vendored upstream banks)."""
    global _default_solver
    if _default_solver is None:
        with _default_lock:
            if _default_solver is None:
                _default_solver = QuizSolver()
    return _default_solver


def _cli(argv: Optional[List[str]] = None) -> None:
    """CLI: stats | rebuild | query "<question>" [--options a b c d]."""
    import argparse

    parser = argparse.ArgumentParser(description="MHXY local quiz bank CLI (zero-token)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats", help="bank size and per-source breakdown")
    sub.add_parser("rebuild", help="delete the SQLite bank and re-import all upstream sources")
    q = sub.add_parser("query", help="try one question against the bank")
    q.add_argument("question")
    q.add_argument("--options", nargs="*", default=[])
    args = parser.parse_args(argv)

    if args.cmd == "rebuild":
        if _DEFAULT_DB_PATH.exists():
            _DEFAULT_DB_PATH.unlink()
            logger.info(f"[quiz_cli] removed {_DEFAULT_DB_PATH}")

    solver = QuizSolver()
    if args.cmd == "stats":
        print(f"bank_size={solver.size}")
        for source, n in sorted(solver.bank.count_by_source().items()):
            print(f"  [{source}] {n}")
    elif args.cmd == "query":
        d = solver.answer(args.question, args.options)
        print(
            f"source={d.source} conf={d.confidence:.2f} elapsed={d.elapsed_ms:.1f}ms\n"
            f"  matched: {d.matched_question}\n"
            f"  answer : {d.option_text or '<bank miss>'} (q={d.question_score:.0f}, opt={d.option_score:.0f})"
        )


if __name__ == "__main__":
    _cli()
