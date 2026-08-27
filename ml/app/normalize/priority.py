"""Deterministic priority scoring.

Not a model call. Priority is arithmetic over four signals, so it has exact
expected values in tests, costs nothing, doesn't drift when a model version
changes, and can explain itself to a student who asks why.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..config import PRIORITY_CUTOFFS, PRIORITY_WEIGHTS, TYPE_WEIGHT
from ..schemas import Priority, Task

# A deadline this far out contributes nothing to urgency.
PROXIMITY_HORIZON_DAYS = 30


def proximity(due: date | None, today: date) -> float:
    """1.0 = due now or overdue, 0.0 = a month or more away."""
    if due is None:
        return 0.0
    days = (due - today).days
    if days <= 0:
        return 1.0
    return max(0.0, 1.0 - days / PROXIMITY_HORIZON_DAYS)


def _bucket(score: float) -> Priority:
    for name, cutoff in PRIORITY_CUTOFFS:
        if score >= cutoff:
            return Priority(name)
    return Priority.LOW


def score_task(task: Task, today: date, week_load: float = 0.0) -> Task:
    type_weight = TYPE_WEIGHT.get(task.type.value, 0.3)
    # 30% of a grade is a lot; normalize against that rather than 100, or every
    # single item scores near zero on this axis.
    grade_norm = min((task.grade_pct or 0.0) / 30.0, 1.0)
    prox = proximity(task.due_date, today)
    load = min(week_load / 12.0, 1.0)

    score = (
        PRIORITY_WEIGHTS["type"] * type_weight
        + PRIORITY_WEIGHTS["grade"] * grade_norm
        + PRIORITY_WEIGHTS["proximity"] * prox
        + PRIORITY_WEIGHTS["week_load"] * load
    )

    task.priority = _bucket(score)

    # Escalation, not arithmetic: anything past its deadline and unfinished is
    # critical by definition. A 25%-of-grade paper due last week scores 0.747 on
    # the formula, which would file it below a comfortable upcoming exam.
    if (
        task.due_date is not None
        and task.due_date < today
        and not task.completed
    ):
        task.priority = Priority.CRITICAL
        score = max(score, PRIORITY_CUTOFFS[0][1])

    task.priority_score = round(score, 3)
    task.priority_reason = _explain(task, today, grade_norm, prox, load)
    return task


def _explain(task: Task, today: date, grade_norm: float, prox: float, load: float) -> str:
    """Every score gets a sentence. A wrong priority should be debuggable, not
    mysterious — and the UI can show the student why something is red."""
    parts: list[str] = []

    if task.grade_pct:
        parts.append(f"{task.grade_pct:g}% of final grade")
    if task.type.value in ("final", "midterm", "exam"):
        parts.append("exam-type")
    elif task.type.value in ("project", "paper"):
        parts.append("major deliverable")

    if task.due_date:
        days = (task.due_date - today).days
        if days < 0:
            parts.append(f"overdue by {abs(days)} days")
        elif days == 0:
            parts.append("due today")
        elif prox > 0:
            parts.append(f"due in {days} days")
        else:
            parts.append(f"due {task.due_date.isoformat()}")
    else:
        parts.append("no due date found")

    if load > 0.5:
        parts.append("lands in a high-workload week")

    return "; ".join(parts) if parts else "baseline priority"


def score_all(tasks: list[Task], today: date, week_loads: dict[date, float] | None = None) -> list[Task]:
    week_loads = week_loads or {}
    for task in tasks:
        load = 0.0
        if task.due_date is not None:
            monday = task.due_date - timedelta(days=task.due_date.weekday())
            load = week_loads.get(monday, 0.0)
        score_task(task, today, load)
    return tasks
