"""Daily progress persistence (SQLite).

completed_tasks / 活跃度 live only in ctx.variables, so every runner restart starts
from zero and must re-derive progress from a full activity-panel scan (live 2026-09-30:
Run 7 died mid-run leaving summary completed_tasks=[] while 活跃度 was actually 30;
Run 8 cold-started with a full panel rescan to rebuild what Run 6/7 had done).

This store keeps the day's progress keyed by calendar date, so:
- a restarted run resumes without redoing completed dailies (tracker routing and
  panel dispatch both filter on completed_tasks);
- state can never leak across the 0 点 daily reset (rows are day-keyed and only
  today's rows are loaded).
The game server remains the source of truth — this is a routing cache, and the
activity panel's own is_done cards still re-verify completion at claim time.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Union

DB_PATH = Path(__file__).resolve().parent / "data" / "daily_state.db"


def _connect(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS daily_progress ("
        "day TEXT NOT NULL, task TEXT NOT NULL, PRIMARY KEY (day, task))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS daily_meta ("
        "day TEXT PRIMARY KEY, huoyue INTEGER NOT NULL DEFAULT 0)"
    )
    return conn


def save_daily_state(
    completed_tasks: Optional[List[str]] = None,
    huoyue: Optional[int] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Upsert today's completed tasks and latest 活跃度 reading."""
    day = date.today().isoformat()
    conn = _connect(db_path)
    try:
        with conn:
            for task in completed_tasks or []:
                conn.execute(
                    "INSERT OR REPLACE INTO daily_progress (day, task) VALUES (?, ?)",
                    (day, str(task)),
                )
            if huoyue is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO daily_meta (day, huoyue) VALUES (?, ?)",
                    (day, int(huoyue)),
                )
    finally:
        conn.close()


def load_daily_state(db_path: Optional[Union[str, Path]] = None) -> Dict[str, object]:
    """Load today's state only — yesterday's rows are invisible across the daily reset."""
    day = date.today().isoformat()
    conn = _connect(db_path)
    try:
        tasks: List[str] = [
            row[0] for row in conn.execute("SELECT task FROM daily_progress WHERE day = ?", (day,))
        ]
        row = conn.execute("SELECT huoyue FROM daily_meta WHERE day = ?", (day,)).fetchone()
        return {"completed_tasks": tasks, "huoyue": row[0] if row else None}
    finally:
        conn.close()
