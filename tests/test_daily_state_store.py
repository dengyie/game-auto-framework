"""Tests for the SQLite daily-progress persistence (plugins/mhxy_mobile/custom/daily_state.py).

Cross-run continuity: a restarted run resumes today's completed dailies and last
活跃度 without redoing them, while rows are day-keyed so nothing leaks across the
0 点 daily reset.
"""

import sqlite3
from datetime import date, timedelta

from plugins.mhxy_mobile.custom.daily_state import (
    _connect,
    load_daily_state,
    save_daily_state,
)


def test_save_and_load_roundtrip(tmp_path):
    db = tmp_path / "state.db"
    save_daily_state(["师门任务", "宝图任务"], huoyue=30, db_path=db)
    state = load_daily_state(db_path=db)
    assert set(state["completed_tasks"]) == {"师门任务", "宝图任务"}
    assert len(state["completed_tasks"]) == 2
    assert state["huoyue"] == 30


def test_save_is_idempotent_and_merges(tmp_path):
    db = tmp_path / "state.db"
    save_daily_state(["师门任务"], huoyue=20, db_path=db)
    save_daily_state(["师门任务", "秘境降妖"], huoyue=45, db_path=db)
    state = load_daily_state(db_path=db)
    assert sorted(state["completed_tasks"]) == ["师门任务", "秘境降妖"]
    assert state["huoyue"] == 45


def test_only_todays_rows_are_loaded(tmp_path):
    """Yesterday's rows must be invisible across the 0 点 daily reset."""
    db = tmp_path / "state.db"
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    save_daily_state(["师门任务"], huoyue=20, db_path=db)
    # Simulate yesterday's leftover rows via direct SQL.
    conn = _connect(db)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_progress (day, task) VALUES (?, ?)",
                (yesterday, "师门任务"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO daily_progress (day, task) VALUES (?, ?)",
                (yesterday, "运镖"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO daily_meta (day, huoyue) VALUES (?, ?)",
                (yesterday, 100),
            )
    finally:
        conn.close()

    state = load_daily_state(db_path=db)
    assert state["completed_tasks"] == ["师门任务"]  # today's only
    assert state["huoyue"] == 20  # today's only, not yesterday's 100
    assert today in state["completed_tasks"] or True  # no-op guard for readability


def test_load_empty_db_returns_empty_state(tmp_path):
    db = tmp_path / "fresh.db"
    state = load_daily_state(db_path=db)
    assert state == {"completed_tasks": [], "huoyue": None}


def test_save_creates_parent_dirs(tmp_path):
    db = tmp_path / "nested" / "deeper" / "state.db"
    save_daily_state(["宝图任务"], db_path=db)
    assert db.exists()
    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT task FROM daily_progress").fetchall()
    conn.close()
    assert rows == [("宝图任务",)]
