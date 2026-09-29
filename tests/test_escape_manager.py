"""Tests for the SelfHealingEscapeManager tier escalation (2026-09-30 re-review fix).

The old Tier-3 gate ("stalled >= 3x threshold") was unreachable: every tier fire
refreshes last_progress_time, so stalled_time never exceeded one threshold period.
Tier 3 (the runner's abort callback) was dead code. The fix caps Tier-2 attempts
(max_level_2_attempts) so persistent stalls escalate to Tier 3.
"""

import time

from scheduler.escape import EscapeLevel, SelfHealingEscapeManager


def _stall_and_check(mgr: SelfHealingEscapeManager):
    """Simulate one stall period elapsed (the tier fire refreshes last_progress_time,
    so rewinding it before each call is exactly what the real tick loop does)."""
    mgr.last_progress_time = time.time() - mgr.stall_threshold_sec - 1.0
    return mgr.check_and_heal()


def test_tier_escalation_reaches_major():
    fired = {"minor": 0, "medium": 0, "major": 0}
    mgr = SelfHealingEscapeManager(
        on_minor_escape=lambda: fired.__setitem__("minor", fired["minor"] + 1),
        on_medium_escape=lambda: fired.__setitem__("medium", fired["medium"] + 1),
        on_major_escape=lambda: fired.__setitem__("major", fired["major"] + 1),
    )
    seq = [_stall_and_check(mgr) for _ in range(7)]
    assert seq == [
        EscapeLevel.LEVEL_1_MINOR,
        EscapeLevel.LEVEL_1_MINOR,
        EscapeLevel.LEVEL_1_MINOR,
        EscapeLevel.LEVEL_2_MEDIUM,
        EscapeLevel.LEVEL_2_MEDIUM,
        EscapeLevel.LEVEL_2_MEDIUM,
        EscapeLevel.LEVEL_3_MAJOR,
    ]
    assert fired == {"minor": 3, "medium": 3, "major": 1}


def test_no_stall_returns_none():
    mgr = SelfHealingEscapeManager()
    assert mgr.check_and_heal() is None  # fresh manager: not stalled


def test_record_progress_resets_tier_counters():
    mgr = SelfHealingEscapeManager()
    # Burn the Tier-1 budget with two stall cycles.
    _stall_and_check(mgr)
    _stall_and_check(mgr)
    assert mgr.level_1_count == 2
    # Real progress (any node recognition): full reset.
    mgr.record_progress()
    assert mgr.level_1_count == 0
    assert mgr.level_2_count == 0
    assert _stall_and_check(mgr) == EscapeLevel.LEVEL_1_MINOR


def test_major_resets_counters_for_next_cycle():
    mgr = SelfHealingEscapeManager()
    for _ in range(6):
        _stall_and_check(mgr)
    assert _stall_and_check(mgr) == EscapeLevel.LEVEL_3_MAJOR
    # Tier 3 calls record_progress: the next stall starts over at Tier 1.
    assert mgr.level_1_count == 0
    assert mgr.level_2_count == 0
    assert _stall_and_check(mgr) == EscapeLevel.LEVEL_1_MINOR
