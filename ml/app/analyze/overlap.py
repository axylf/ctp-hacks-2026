"""Stage 6: find the weeks that will hurt.

Two views, because they answer different questions:
  - ISO weeks drive what the calendar highlights (weeks are how students think)
  - a rolling 7-day window is what actually catches crunch: a paper due Friday
    and two exams the following Monday is a brutal four-day stretch that ISO
    weeks split down the middle and miss entirely
"""
from __future__ import annotations

from datetime import date, timedelta

from ..config import EFFORT_UNITS, MAJOR_TYPES, SEVERITY_RULES
from ..schemas import Severity, Task, WorkloadAnalysis, WorkloadWindow


def task_load(task: Task) -> float:
    """Effort units, scaled by how much of the grade rides on it."""
    base = EFFORT_UNITS.get(task.type.value, 2)
    weight = 1.0 + (task.grade_pct or 0.0) / 100.0
    return base * weight


def _severity(load: float, majors: int) -> Severity | None:
    for name, load_cut, major_cut in SEVERITY_RULES:
        if load >= load_cut or majors >= major_cut:
            return Severity(name)
    return None


# A window has to contain a COLLISION to be worth flagging. One project,
# however heavy, is just a deadline -- highlighting it would light up most of
# the semester and train students to ignore the highlighting.
MIN_TASKS_PER_WINDOW = 2


def _describe(tasks: list[Task], days: int) -> str:
    majors = [t for t in tasks if t.type.value in MAJOR_TYPES]
    if len(majors) >= 2:
        return f"{len(majors)} major deadlines in {days} days"
    return f"{len(tasks)} deadlines in {days} days"


def _window(start: date, end: date, tasks: list[Task], kind: str) -> WorkloadWindow | None:
    if len(tasks) < MIN_TASKS_PER_WINDOW:
        return None
    load = sum(task_load(t) for t in tasks)
    majors = sum(1 for t in tasks if t.type.value in MAJOR_TYPES)
    severity = _severity(load, majors)
    if severity is None:
        return None
    return WorkloadWindow(
        start=start,
        end=end,
        load_score=round(load, 2),
        severity=severity,
        task_ids=[t.id for t in tasks],
        label=_describe(tasks, (end - start).days + 1),
        kind=kind,
    )


def weekly_windows(tasks: list[Task]) -> list[WorkloadWindow]:
    """ISO-week buckets — what the calendar highlights."""
    buckets: dict[date, list[Task]] = {}
    for task in tasks:
        if task.due_date is None or task.completed:
            continue
        monday = task.due_date - timedelta(days=task.due_date.weekday())
        buckets.setdefault(monday, []).append(task)

    windows = []
    for monday, group in sorted(buckets.items()):
        window = _window(monday, monday + timedelta(days=6), group, "iso_week")
        if window:
            windows.append(window)
    return windows


def rolling_windows(tasks: list[Task], span_days: int = 7) -> list[WorkloadWindow]:
    """Every 7-day span, stepped daily, keeping only non-overlapping peaks.

    This is the one that catches crunch straddling a week boundary.
    """
    dated = sorted(
        (t for t in tasks if t.due_date is not None and not t.completed),
        key=lambda t: t.due_date,
    )
    if not dated:
        return []

    candidates: list[WorkloadWindow] = []
    first, last = dated[0].due_date, dated[-1].due_date
    day = first
    while day <= last:
        end = day + timedelta(days=span_days - 1)
        group = [t for t in dated if day <= t.due_date <= end]
        window = _window(day, end, group, "rolling_7d")
        if window:
            candidates.append(window)
        day += timedelta(days=1)

    # Greedy peak-picking: strongest window first, then drop anything it overlaps.
    # Without this, one crunch week emits seven near-identical windows.
    candidates.sort(key=lambda w: (-w.load_score, w.start))
    chosen: list[WorkloadWindow] = []
    for window in candidates:
        if any(not (window.end < c.start or window.start > c.end) for c in chosen):
            continue
        chosen.append(window)
    return sorted(chosen, key=lambda w: w.start)


def week_loads(tasks: list[Task]) -> dict[date, float]:
    """Monday -> total load, fed back into priority scoring so a task in a
    crunch week is ranked above an identical task in a quiet one."""
    loads: dict[date, float] = {}
    for task in tasks:
        if task.due_date is None:
            continue
        monday = task.due_date - timedelta(days=task.due_date.weekday())
        loads[monday] = loads.get(monday, 0.0) + task_load(task)
    return loads


def analyze(tasks: list[Task]) -> WorkloadAnalysis:
    """Both views, minus the double-reporting.

    A rolling window earns its place only when it groups tasks that no ISO
    week already groups -- that is the entire reason it exists. Without this
    filter the same three deadlines surface twice and the UI shows two
    CRITICAL cards for one bad week.
    """
    weekly = weekly_windows(tasks)
    covered = [set(w.task_ids) for w in weekly]
    rolling = [
        w for w in rolling_windows(tasks)
        if not any(set(w.task_ids) <= seen for seen in covered)
    ]
    return WorkloadAnalysis(windows=weekly + rolling)
