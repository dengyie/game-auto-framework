from __future__ import annotations

from typing import Iterable, Optional, Tuple
from rapidfuzz import fuzz, process


def fuzzy_match_ratio(str1: str, str2: str) -> float:
    """Calculate partial ratio similarity (0.0 to 100.0) between two strings."""
    if not str1 or not str2:
        return 0.0
    return float(fuzz.partial_ratio(str1, str2))


def find_best_match(
    query: str,
    choices: Iterable[str],
    threshold: float = 75.0,
) -> Tuple[Optional[str], float, int]:
    """Find the best matching string from choices for the given query.

    Returns:
        (best_choice_string, score, index) or (None, 0.0, -1) if below threshold.
    """
    choices_list = list(choices)
    if not query or not choices_list:
        return None, 0.0, -1

    res = process.extractOne(
        query,
        choices_list,
        scorer=fuzz.token_set_ratio,
        score_cutoff=threshold,
    )
    if res is None:
        return None, 0.0, -1

    match_str, score, idx = res
    return match_str, float(score), idx
