"""Merge duplicate tasks within a course.

Syllabi repeat themselves: an item appears in the grading breakdown AND in the
schedule table. We want one task carrying the union of what both said.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..schemas import DateSource, Task

SIMILARITY_THRESHOLD = 88

_NOISE = re.compile(r"\b(assignment|homework|hw|pset|problem set|exam|the|a|an)\b", re.I)
_INDEX = re.compile(r"\d+")


def _canonical(title: str) -> str:
    """'HW 3' and 'Homework 3' collapse to the same key: the identifying part of
    a task title is usually its number."""
    text = title.lower().strip()
    text = _NOISE.sub(" ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _index_numbers(title: str) -> list[str]:
    return _INDEX.findall(title)


def is_duplicate(a: Task, b: Task) -> bool:
    if a.type is not b.type:
        return False

    # "Assignment 1" vs "Assignment 2" scores 96 on token_sort_ratio -- the
    # digit is the whole difference and fuzzy matching drowns it. When both
    # titles are numbered and the numbers differ, they are different work.
    nums_a, nums_b = _index_numbers(a.title), _index_numbers(b.title)
    if nums_a and nums_b and nums_a != nums_b:
        return False
    # Different explicit dates means genuinely different deliverables.
    if a.due_date and b.due_date and a.due_date != b.due_date:
        return False
    key_a, key_b = _canonical(a.title), _canonical(b.title)
    if key_a and key_a == key_b:
        return True
    return fuzz.token_sort_ratio(a.title.lower(), b.title.lower()) >= SIMILARITY_THRESHOLD


def _merge(keeper: Task, other: Task) -> Task:
    """Prefer real information over absent information, explicit over inferred."""
    if keeper.due_date is None and other.due_date is not None:
        keeper.due_date = other.due_date
        keeper.date_source = other.date_source
    elif other.date_source is DateSource.EXPLICIT and keeper.date_source is not DateSource.EXPLICIT:
        keeper.due_date, keeper.date_source = other.due_date, other.date_source

    if keeper.grade_pct is None and other.grade_pct is not None:
        keeper.grade_pct = other.grade_pct
    if not keeper.source_quote:
        keeper.source_quote = other.source_quote
    if keeper.source_page is None:
        keeper.source_page = other.source_page
    keeper.confidence = max(keeper.confidence, other.confidence)
    if len(other.title) > len(keeper.title):
        keeper.title = other.title
    return keeper


def dedupe(tasks: list[Task]) -> list[Task]:
    kept: list[Task] = []
    for task in tasks:
        match = next((k for k in kept if is_duplicate(k, task)), None)
        if match is None:
            kept.append(task)
        else:
            _merge(match, task)
    return kept
