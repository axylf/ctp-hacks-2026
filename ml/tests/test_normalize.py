"""Stage 5: dates, inference, dedupe, priority. All deterministic, all exact."""
from __future__ import annotations

from datetime import date

import pytest

from ml.app.normalize.dates import TermCalendar, parse_due, term_calendar_from_label
from ml.app.normalize.dedupe import dedupe
from ml.app.normalize.infer import infer_schedule
from ml.app.normalize.priority import proximity, score_task
from ml.app.schemas import DateSource, Priority, TaskType
from ml.tests.conftest import TERM_END, TERM_START, TODAY, make_task

TERM = TermCalendar(TERM_START, TERM_END)


# --- dates -----------------------------------------------------------------

def test_dates_relative():
    assert parse_due("Week 5 Monday", TERM) == date(2026, 2, 23)


def test_dates_week_without_weekday_lands_on_monday():
    assert parse_due("Week 5", TERM) == date(2026, 2, 23)


def test_dates_weekday_within_week():
    assert parse_due("Friday of week 5", TERM) == date(2026, 2, 27)


def test_dates_year_inference():
    """A bare 3/10 in a Spring 2026 course is 2026 — never the current year."""
    assert parse_due("3/10", TERM) == date(2026, 3, 10)
    assert parse_due("March 10", TERM) == date(2026, 3, 10)
    assert parse_due("Mar. 10th", TERM) == date(2026, 3, 10)


def test_dates_explicit_year_is_respected():
    assert parse_due("March 10, 2027", TERM) == date(2027, 3, 10)


@pytest.mark.parametrize("text", ["TBA", "tbd", "posted on Blackboard", "", "   "])
def test_dates_unknown_returns_none(text):
    """None is the correct answer. A guessed date is worse than no date."""
    assert parse_due(text, TERM) is None


def test_dates_without_a_term_wont_invent_a_week():
    assert parse_due("Week 5", None) is None


def test_term_calendar_from_label():
    term = term_calendar_from_label("Spring 2026")
    assert term and term.start.year == 2026 and term.start.month == 1
    assert term_calendar_from_label("no term here") is None


def test_week_start_is_clamped_into_the_term():
    assert TERM.week_start(99) == TERM.end
    assert TERM.week_start(0) >= TERM.start


# --- inference -------------------------------------------------------------

def test_infer_schedule_spreads_a_series():
    tasks = [
        make_task(f"a{i}", f"Programming Assignment {i}", TaskType.ASSIGNMENT, None, 10.0)
        for i in range(1, 5)
    ]
    infer_schedule(tasks, TERM)

    dates = [t.due_date for t in tasks]
    assert all(d is not None for d in dates)
    assert dates == sorted(dates), "series must run forward in time"
    assert len(set(dates)) == 4, "four assignments must not land on one day"
    assert all(TERM.contains(d) for d in dates)
    assert all(t.date_source is DateSource.INFERRED for t in tasks)
    assert all(t.needs_review for t in tasks), "inferred dates must be flagged"


def test_infer_schedule_anchors_exams():
    midterm = make_task("m", "Midterm", TaskType.MIDTERM, None, 20.0)
    final = make_task("f", "Final", TaskType.FINAL, None, 30.0)
    infer_schedule([midterm, final], TERM)

    assert midterm.due_date < final.due_date
    assert final.due_date == TERM_END
    # A midterm belongs mid-term, not in week 2 or finals week.
    assert TERM_START < midterm.due_date < TERM_END


def test_infer_schedule_leaves_explicit_dates_alone():
    fixed = make_task("q", "Quiz 1", TaskType.QUIZ, date(2026, 3, 3), 5.0)
    infer_schedule([fixed], TERM)
    assert fixed.due_date == date(2026, 3, 3)
    assert fixed.date_source is DateSource.EXPLICIT
    assert not fixed.needs_review


# --- dedupe ----------------------------------------------------------------

def test_dedupe_merges_naming_variants():
    a = make_task("1", "HW 3", TaskType.ASSIGNMENT, None)
    b = make_task("2", "Homework 3", TaskType.ASSIGNMENT, date(2026, 3, 4), 8.0)
    merged = dedupe([a, b])
    assert len(merged) == 1
    # The merged task keeps the information, not just the first record.
    assert merged[0].due_date == date(2026, 3, 4)
    assert merged[0].grade_pct == 8.0


def test_dedupe_keeps_differently_numbered_work():
    """'Assignment 1' vs 'Assignment 2' fuzzy-match at 96. The number is the
    entire difference, and collapsing them loses three quarters of the course."""
    tasks = [
        make_task(str(i), f"Programming Assignment {i}", TaskType.ASSIGNMENT, None, 10.0)
        for i in range(1, 5)
    ]
    assert len(dedupe(tasks)) == 4


def test_dedupe_keeps_different_types():
    quiz = make_task("1", "Unit 1", TaskType.QUIZ, None)
    exam = make_task("2", "Unit 1", TaskType.EXAM, None)
    assert len(dedupe([quiz, exam])) == 2


def test_dedupe_keeps_same_title_on_different_dates():
    a = make_task("1", "Weekly Quiz", TaskType.QUIZ, date(2026, 3, 3))
    b = make_task("2", "Weekly Quiz", TaskType.QUIZ, date(2026, 3, 10))
    assert len(dedupe([a, b])) == 2


# --- priority --------------------------------------------------------------

def test_priority_ordering():
    """A 30% final outranks a 5% quiz even though the quiz is sooner."""
    final = make_task("f", "Final Exam", TaskType.FINAL, date(2026, 5, 20), 30.0)
    quiz = make_task("q", "Quiz 2", TaskType.QUIZ, date(2026, 2, 3), 5.0)
    score_task(final, TODAY)
    score_task(quiz, TODAY)
    assert final.priority_score > quiz.priority_score


def test_priority_reason_is_always_populated():
    for task in [
        make_task("a", "Paper", TaskType.PAPER, date(2026, 3, 1), 25.0),
        make_task("b", "Undated thing", TaskType.OTHER, None),
    ]:
        score_task(task, TODAY)
        assert task.priority_reason.strip()


def test_priority_reason_mentions_the_grade_and_the_deadline():
    task = make_task("a", "Final", TaskType.FINAL, date(2026, 2, 8), 30.0)
    score_task(task, TODAY)
    assert "30% of final grade" in task.priority_reason
    assert "due in 7 days" in task.priority_reason


def test_priority_overdue_is_critical():
    task = make_task("a", "Late Paper", TaskType.PAPER, date(2026, 1, 20), 25.0)
    score_task(task, TODAY)
    assert task.priority is Priority.CRITICAL
    assert "overdue by 12 days" in task.priority_reason


def test_priority_crunch_week_raises_an_identical_task():
    quiet = make_task("a", "Project", TaskType.PROJECT, date(2026, 3, 10), 20.0)
    busy = make_task("b", "Project", TaskType.PROJECT, date(2026, 3, 10), 20.0)
    score_task(quiet, TODAY, week_load=0.0)
    score_task(busy, TODAY, week_load=14.0)
    assert busy.priority_score > quiet.priority_score
    assert "high-workload week" in busy.priority_reason


def test_proximity_curve():
    assert proximity(None, TODAY) == 0.0
    assert proximity(date(2026, 1, 1), TODAY) == 1.0      # overdue
    assert proximity(TODAY, TODAY) == 1.0
    assert proximity(date(2026, 12, 1), TODAY) == 0.0     # beyond the horizon
