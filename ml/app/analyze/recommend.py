"""Stage 7: proactive advice.

Rules decide WHAT to say; Gemini only decides HOW to say it. The advice is
therefore never hallucinated — worst case it's phrased blandly. Subtask
breakdowns come from the model (it knows a research paper decomposes
differently than a socket-programming assignment) but every offset it returns
is validated before a date is computed from it.
"""
from __future__ import annotations

import logging
from datetime import date

from ..config import MAJOR_TYPES
from ..schemas import (
    Recommendation,
    Severity,
    Subtask,
    Task,
    TaskType,
    WorkloadAnalysis,
)

log = logging.getLogger(__name__)

MIN_SPLIT_GRADE_PCT = 20.0
EXAM_CLUSTER_HOURS = 48

# Generic fallbacks, used when Gemini isn't available. Deliberately typed by
# work kind — a paper and a project don't decompose the same way.
_DEFAULT_BREAKDOWN: dict[TaskType, list[tuple[str, float]]] = {
    TaskType.PAPER: [
        ("Pick a topic and find sources", 1.0),
        ("Outline the argument", 0.75),
        ("Write a full draft", 0.4),
        ("Revise and proofread", 0.15),
    ],
    TaskType.PROJECT: [
        ("Scope the project and sketch a design", 1.0),
        ("Build a working skeleton", 0.7),
        ("Implement core functionality", 0.4),
        ("Test, debug, and write it up", 0.15),
    ],
    TaskType.PRESENTATION: [
        ("Decide the through-line", 1.0),
        ("Build the slides", 0.5),
        ("Rehearse out loud once", 0.2),
    ],
}
# How long the breakdown itself should span. Scaling the steps across the
# FULL lead time produces "start reading the spec 100 days early", which is
# advice nobody follows. Work backwards from the deadline over a realistic
# working period instead, and let the earlier weeks stay free.
MAX_BREAKDOWN_SPAN_DAYS: dict[TaskType, int] = {
    TaskType.PAPER: 21,
    TaskType.PROJECT: 28,
    TaskType.PRESENTATION: 14,
}
DEFAULT_BREAKDOWN_SPAN_DAYS = 14

_GENERIC_BREAKDOWN = [
    ("Read the spec and list what's required", 1.0),
    ("Do a first pass", 0.6),
    ("Finish and review", 0.2),
]


def _lead_days(task: Task, today: date) -> int:
    if task.due_date is None:
        return 0
    return max((task.due_date - today).days, 0)


def default_subtasks(task: Task, today: date) -> list[Subtask]:
    lead = _lead_days(task, today)
    if lead < 3:
        return []
    span = min(
        lead,
        MAX_BREAKDOWN_SPAN_DAYS.get(task.type, DEFAULT_BREAKDOWN_SPAN_DAYS),
    )
    template = _DEFAULT_BREAKDOWN.get(task.type, _GENERIC_BREAKDOWN)
    out: list[Subtask] = []
    for title, fraction in template:
        days_before = max(1, int(round(span * fraction)))
        if days_before > lead:
            continue
        out.append(
            Subtask(
                title=title,
                days_before=days_before,
                due_date=task.due_date - _days(days_before),
            )
        )
    return out


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)


def validate_subtasks(subtasks: list[Subtask], task: Task, today: date) -> list[Subtask]:
    """Reject offsets that are negative, zero, or further back than the task's
    own lead time — a subtask due before today helps nobody."""
    lead = _lead_days(task, today)
    valid: list[Subtask] = []
    for sub in subtasks:
        if sub.days_before < 1 or sub.days_before > lead:
            continue
        if task.due_date is not None:
            sub.due_date = task.due_date - _days(sub.days_before)
        valid.append(sub)
    return sorted(valid, key=lambda s: -s.days_before)


def _heaviest(tasks: list[Task]) -> Task | None:
    majors = [t for t in tasks if t.type.value in MAJOR_TYPES] or tasks
    return max(majors, key=lambda t: (t.grade_pct or 0, t.priority_score), default=None)


def recommend(
    tasks: list[Task],
    analysis: WorkloadAnalysis,
    today: date,
    use_gemini: bool = False,
) -> list[Recommendation]:
    by_id = {t.id: t for t in tasks}
    out: list[Recommendation] = []
    already: set[str] = set()

    # --- crunch windows: start the biggest thing early -----------------------
    crunch = [
        w for w in analysis.windows
        if w.severity in (Severity.CRITICAL, Severity.HEAVY) and w.kind == "rolling_7d"
    ] or [w for w in analysis.windows if w.severity is Severity.CRITICAL]

    for window in crunch:
        window_tasks = [by_id[i] for i in window.task_ids if i in by_id]
        target = _heaviest([t for t in window_tasks if not t.completed])
        if target is None or target.id in already:
            continue
        already.add(target.id)

        lead = _lead_days(target, today)
        start_days = min(max(lead // 2, 3), 10)
        subtasks = _breakdown(target, today, use_gemini)
        out.append(
            Recommendation(
                type="start_early",
                target_task_id=target.id,
                message=(
                    f"{window.label} ({window.start:%b %d}–{window.end:%b %d}). "
                    f"{target.title} is the heaviest of them"
                    + (f" at {target.grade_pct:g}% of your grade" if target.grade_pct else "")
                    + f". Start it about {start_days} days early and work in pieces."
                ),
                window=f"{window.start.isoformat()}..{window.end.isoformat()}",
                suggested_subtasks=subtasks,
            )
        )

    # --- big single deliverables deserve a breakdown regardless --------------
    for task in tasks:
        if task.id in already or task.completed:
            continue
        if (task.grade_pct or 0) < MIN_SPLIT_GRADE_PCT:
            continue
        if task.type not in (TaskType.PAPER, TaskType.PROJECT, TaskType.PRESENTATION):
            continue
        subtasks = _breakdown(task, today, use_gemini)
        if not subtasks:
            continue
        already.add(task.id)
        out.append(
            Recommendation(
                type="break_into_subtasks",
                target_task_id=task.id,
                message=(
                    f"{task.title} is worth {task.grade_pct:g}% of your grade. "
                    "Break it into stages instead of one sitting."
                ),
                suggested_subtasks=subtasks,
            )
        )

    # --- back-to-back exams --------------------------------------------------
    exams = sorted(
        (t for t in tasks if t.type.value in ("exam", "midterm", "final") and t.due_date),
        key=lambda t: t.due_date,
    )
    for first, second in zip(exams, exams[1:]):
        gap_hours = (second.due_date - first.due_date).days * 24
        if 0 <= gap_hours <= EXAM_CLUSTER_HOURS and second.id not in already:
            already.add(second.id)
            out.append(
                Recommendation(
                    type="front_load_study",
                    target_task_id=second.id,
                    message=(
                        f"{second.title} is {gap_hours // 24 or 0} day(s) after {first.title}. "
                        "You won't get study time between them — front-load it."
                    ),
                )
            )

    # --- overdue -------------------------------------------------------------
    for task in tasks:
        if task.completed or task.due_date is None or task.due_date >= today:
            continue
        out.append(
            Recommendation(
                type="overdue",
                target_task_id=task.id,
                message=(
                    f"{task.title} was due {task.due_date:%b %d} and isn't marked done."
                ),
            )
        )

    return out


def _breakdown(task: Task, today: date, use_gemini: bool) -> list[Subtask]:
    if use_gemini:
        try:
            return validate_subtasks(_gemini_subtasks(task), task, today)
        except Exception as exc:  # never let advice generation break the pipeline
            log.warning("subtask generation via Gemini failed (%s); using defaults", exc)
    return default_subtasks(task, today)


def _gemini_subtasks(task: Task) -> list[Subtask]:
    """Ask the model to decompose one task. Schema-constrained to 3-6 steps."""
    from pydantic import BaseModel, Field

    from ..config import settings
    from ..extract.gemini import _build_client

    class _Breakdown(BaseModel):
        subtasks: list[Subtask] = Field(min_length=3, max_length=6)

    from google.genai import types

    client = _build_client()
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=(
            f"Break this coursework into 3-6 concrete steps a student can start today.\n"
            f"Task: {task.title}\nType: {task.type.value}\n"
            f"Worth: {task.grade_pct or 'unknown'}% of the grade\n"
            f"days_before is how many days before the deadline each step should be done."
        ),
        config=types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=_Breakdown,
        ),
    )
    return _Breakdown.model_validate_json(response.text).subtasks
