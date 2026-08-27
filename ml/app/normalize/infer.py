"""Place undated work on the term calendar — the stage that makes a dateless
syllabus (like our fixture) usable.

Every date this module produces is tagged DateSource.INFERRED and carries
needs_review=True. It is a scheduling suggestion, not a claim about the
syllabus, and the UI must render it differently.
"""
from __future__ import annotations

from datetime import timedelta

from ..schemas import DateSource, Task, TaskType
from .dates import TermCalendar

# Where each kind of work conventionally lands, as a fraction through the term.
_ANCHOR = {
    TaskType.MIDTERM: 0.50,
    TaskType.FINAL: 1.0,
    TaskType.PRESENTATION: 0.90,
    TaskType.PROJECT: 0.92,
    TaskType.PAPER: 0.85,
}


def _at_fraction(term: TermCalendar, fraction: float):
    span = (term.end - term.start).days
    return term.start + timedelta(days=int(round(span * min(max(fraction, 0.0), 1.0))))


def infer_schedule(tasks: list[Task], term: TermCalendar) -> list[Task]:
    """Fill in missing due dates. Tasks that already have an explicit date are
    left completely alone."""
    undated = [t for t in tasks if t.due_date is None]
    if not undated:
        return tasks

    # Repeated work (4 programming assignments) spreads evenly across the middle
    # of the term rather than piling onto one anchor date.
    series: dict[tuple[str, TaskType], list[Task]] = {}
    singles: list[Task] = []
    for task in undated:
        if task.type in _ANCHOR and task.type not in (TaskType.PROJECT, TaskType.PAPER):
            singles.append(task)
            continue
        key = (_series_key(task.title), task.type)
        series.setdefault(key, []).append(task)

    for task in singles:
        task.due_date = _at_fraction(term, _ANCHOR[task.type])
        _mark(task)

    for members, in ((v,) for v in series.values()):
        count = len(members)
        if count == 1:
            task = members[0]
            fraction = _ANCHOR.get(task.type, 0.75)
            task.due_date = _at_fraction(term, fraction)
            _mark(task)
            continue
        # Evenly spaced through weeks 3..(end-1), so nothing lands in week 1.
        for index, task in enumerate(members):
            fraction = 0.25 + (0.65 * index / max(count - 1, 1))
            task.due_date = _at_fraction(term, fraction)
            _mark(task)

    return tasks


def _series_key(title: str) -> str:
    import re

    return re.sub(r"\s*\d+\s*$", "", title).strip().lower()


def _mark(task: Task) -> None:
    task.date_source = DateSource.INFERRED
    task.needs_review = True
    task.confidence = min(task.confidence, 0.55)
