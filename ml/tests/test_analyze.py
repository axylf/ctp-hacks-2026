"""Stage 6-7: crunch detection and the advice built on it."""
from __future__ import annotations

from datetime import date

from ml.app.analyze.overlap import analyze, rolling_windows, task_load, weekly_windows
from ml.app.analyze.recommend import default_subtasks, recommend, validate_subtasks
from ml.app.normalize.priority import score_all
from ml.app.schemas import Severity, Subtask, TaskType
from ml.tests.conftest import TODAY, make_task


def test_overlap_detects_crunch():
    """Three majors in one week is the scenario the whole product exists for."""
    tasks = [
        make_task("a", "Final Paper", TaskType.PAPER, date(2026, 3, 16), 25.0),
        make_task("b", "Midterm", TaskType.MIDTERM, date(2026, 3, 18), 20.0),
        make_task("c", "Group Project", TaskType.PROJECT, date(2026, 3, 20), 30.0),
    ]
    weeks = weekly_windows(tasks)
    assert len(weeks) == 1
    window = weeks[0]
    assert window.severity is Severity.CRITICAL
    assert set(window.task_ids) == {"a", "b", "c"}
    assert "3 major deadlines" in window.label


def test_overlap_quiet_week_emits_nothing():
    """No false alarms: one small quiz is not a crunch."""
    assert weekly_windows([make_task("q", "Quiz 1", TaskType.QUIZ, date(2026, 3, 4), 5.0)]) == []


def test_overlap_rolling_window_catches_what_iso_weeks_split():
    """Friday paper + Monday/Tuesday exams is a brutal four-day stretch that
    falls across a week boundary. This is why the rolling window exists."""
    tasks = [
        make_task("a", "Paper", TaskType.PAPER, date(2026, 3, 20), 20.0),   # Friday
        make_task("b", "Exam 1", TaskType.EXAM, date(2026, 3, 23), 15.0),   # Monday
        make_task("c", "Exam 2", TaskType.EXAM, date(2026, 3, 24), 15.0),   # Tuesday
    ]
    weekly = weekly_windows(tasks)
    assert all(len(w.task_ids) < 3 for w in weekly), "ISO weeks should split this up"

    rolling = rolling_windows(tasks)
    assert any(len(w.task_ids) == 3 and w.severity is Severity.CRITICAL for w in rolling), (
        "the rolling window must see all three together"
    )


def test_rolling_windows_do_not_overlap():
    """One crunch period must produce one window, not seven near-identical ones."""
    tasks = [
        make_task(str(i), f"Exam {i}", TaskType.EXAM, date(2026, 3, 16 + i), 15.0)
        for i in range(4)
    ]
    windows = rolling_windows(tasks)
    for earlier, later in zip(windows, windows[1:]):
        assert earlier.end < later.start


def test_completed_work_stops_counting():
    tasks = [
        make_task("a", "Paper", TaskType.PAPER, date(2026, 3, 16), 25.0),
        make_task("b", "Midterm", TaskType.MIDTERM, date(2026, 3, 18), 20.0),
        make_task("c", "Project", TaskType.PROJECT, date(2026, 3, 20), 30.0),
    ]
    for task in tasks[:2]:
        task.completed = True
    assert weekly_windows(tasks) == []


def test_task_load_scales_with_grade_weight():
    light = make_task("a", "Exam", TaskType.EXAM, date(2026, 3, 2), 5.0)
    heavy = make_task("b", "Exam", TaskType.EXAM, date(2026, 3, 2), 40.0)
    assert task_load(heavy) > task_load(light)


# --- recommendations -------------------------------------------------------

def _analyzed(tasks):
    score_all(tasks, TODAY)
    return analyze(tasks)


def test_recommend_start_early():
    tasks = [
        make_task("a", "Research Paper", TaskType.PAPER, date(2026, 3, 16), 25.0),
        make_task("b", "Midterm", TaskType.MIDTERM, date(2026, 3, 18), 20.0),
        make_task("c", "Group Project", TaskType.PROJECT, date(2026, 3, 20), 30.0),
    ]
    recs = recommend(tasks, _analyzed(tasks), TODAY)

    start_early = [r for r in recs if r.type == "start_early"]
    assert start_early, "a three-major week must produce advice"
    # The heaviest item is the one to start early.
    assert start_early[0].target_task_id == "c"
    assert start_early[0].suggested_subtasks


def test_subtask_offsets_valid():
    """Every offset must be positive and inside the task's own lead time —
    a subtask due before today helps nobody."""
    tasks = [
        make_task("a", "Paper", TaskType.PAPER, date(2026, 3, 16), 25.0),
        make_task("b", "Midterm", TaskType.MIDTERM, date(2026, 3, 18), 20.0),
        make_task("c", "Project", TaskType.PROJECT, date(2026, 3, 20), 30.0),
    ]
    lead = {t.id: (t.due_date - TODAY).days for t in tasks}
    for rec in recommend(tasks, _analyzed(tasks), TODAY):
        for sub in rec.suggested_subtasks:
            assert sub.days_before >= 1
            assert sub.days_before <= lead[rec.target_task_id]
            assert sub.due_date is not None and sub.due_date >= TODAY


def test_validate_subtasks_rejects_impossible_offsets():
    """Guards the Gemini path: a model can return days_before=400."""
    task = make_task("a", "Paper", TaskType.PAPER, date(2026, 2, 11), 25.0)  # 10 days out
    proposed = [
        Subtask(title="ok", days_before=7),
        Subtask(title="too far back", days_before=400),
    ]
    valid = validate_subtasks(proposed, task, TODAY)
    assert [s.title for s in valid] == ["ok"]
    assert valid[0].due_date == date(2026, 2, 4)


def test_breakdown_is_typed_to_the_work():
    """A paper and a project don't decompose the same way."""
    paper = make_task("a", "Term Paper", TaskType.PAPER, date(2026, 4, 1), 25.0)
    project = make_task("b", "Capstone", TaskType.PROJECT, date(2026, 4, 1), 25.0)
    paper_steps = [s.title for s in default_subtasks(paper, TODAY)]
    project_steps = [s.title for s in default_subtasks(project, TODAY)]
    assert paper_steps != project_steps
    assert any("draft" in s.lower() for s in paper_steps)
    assert any("design" in s.lower() or "skeleton" in s.lower() for s in project_steps)


def test_recommend_front_load_for_back_to_back_exams():
    tasks = [
        make_task("a", "Midterm 1", TaskType.MIDTERM, date(2026, 3, 10), 15.0),
        make_task("b", "Midterm 2", TaskType.MIDTERM, date(2026, 3, 11), 15.0),
    ]
    recs = recommend(tasks, _analyzed(tasks), TODAY)
    assert any(r.type == "front_load_study" and r.target_task_id == "b" for r in recs)


def test_recommend_overdue():
    task = make_task("a", "Assignment 1", TaskType.ASSIGNMENT, date(2026, 1, 15), 10.0)
    recs = recommend([task], _analyzed([task]), TODAY)
    overdue = [r for r in recs if r.type == "overdue"]
    assert overdue and "isn't marked done" in overdue[0].message


def test_completed_work_gets_no_nagging():
    task = make_task("a", "Assignment 1", TaskType.ASSIGNMENT, date(2026, 1, 15), 10.0)
    task.completed = True
    assert not [r for r in recommend([task], _analyzed([task]), TODAY) if r.type == "overdue"]
