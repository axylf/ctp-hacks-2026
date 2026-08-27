"""The flagship fixture test.

A real syllabus with a real trap: it names every graded deliverable and states
their weights, and contains ZERO dates. This file is the regression net for the
hardest realistic case we have, and every assertion below was read out of the
actual PDF rather than copied from the pipeline's own output.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.app.ingest.pdf import extract_pdf
from ml.app.pipeline import PipelineOptions, process_pdf
from ml.app.schemas import DateSource, TaskType
from ml.tests.conftest import TERM_END, TERM_START, TODAY

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "intro_to_networks.json"

DATED = PipelineOptions(term_start=TERM_START, term_end=TERM_END, today=TODAY, use_gemini=False)
UNDATED = PipelineOptions(
    term_start=TERM_START, term_end=TERM_END, today=TODAY, infer_dates=False, use_gemini=False
)


@pytest.fixture(scope="module")
def result(request):
    data = (Path(__file__).parent / "fixtures" / "syllabi"
            / "intro_to_networks_spring2026.pdf").read_bytes()
    return process_pdf(data, DATED)


# --- course identity -------------------------------------------------------

def test_cross_listed_course_is_one_course(result):
    """CMP 405/743 is two catalog numbers for one class, each with its own
    description and prerequisites. Emitting two courses would double every
    deadline on the calendar."""
    assert result.course.code == "CMP 405/743"
    assert result.course.name == "Intro to Networks"


def test_course_metadata(result):
    assert result.course.instructor == "Matthew P. Johnson"
    assert result.course.term == "Spring 2026"
    assert "Lehman College" in (result.course.institution or "")


def test_prerequisite_numbers_are_not_mistaken_for_this_course(result):
    """The syllabus mentions CMP 334, CMP 338, CMP 232 as prerequisites."""
    for prereq in ("334", "338", "232"):
        assert prereq not in result.course.code


# --- the graded work -------------------------------------------------------

def test_finds_every_graded_deliverable(result):
    by_type = {}
    for task in result.tasks:
        by_type.setdefault(task.type, []).append(task)

    assert len(by_type[TaskType.FINAL]) == 1
    assert len(by_type[TaskType.MIDTERM]) == 1
    assert len(by_type[TaskType.ASSIGNMENT]) == 4, "~4 programming assignments"
    assert len(result.tasks) == 6


def test_grade_weights_match_the_syllabus(result):
    """40% assignments / 10% participation / 20% midterm / 30% final."""
    weights = {t.type: 0.0 for t in result.tasks}
    for task in result.tasks:
        weights[task.type] += task.grade_pct or 0.0

    assert weights[TaskType.ASSIGNMENT] == pytest.approx(40.0)
    assert weights[TaskType.MIDTERM] == pytest.approx(20.0)
    assert weights[TaskType.FINAL] == pytest.approx(30.0)


def test_the_whole_grading_table_is_accounted_for(result):
    """Participation is 10% of the grade but is NOT a to-do item — you can't
    complete it. It's tracked separately so we can prove nothing was silently
    dropped: task weights + non-task weight must reach 100."""
    assert result.meta.non_task_weight == pytest.approx(10.0)
    assert result.meta.grade_weight_total == pytest.approx(100.0)


def test_participation_is_not_a_task(result):
    assert not any("participation" in t.title.lower() for t in result.tasks)


def test_the_ligature_final_was_found(result):
    """The syllabus renders this as '30% - ﬁnal' with a U+FB01 ligature."""
    finals = [t for t in result.tasks if t.type is TaskType.FINAL]
    assert len(finals) == 1
    assert finals[0].grade_pct == pytest.approx(30.0)


def test_every_task_has_provenance(result):
    """source_quote is what lets a student check the AI's work."""
    for task in result.tasks:
        assert task.source_quote.strip(), f"{task.title} has no supporting quote"
        assert task.source_page in (1, 2, 3)


# --- the null-date rule ----------------------------------------------------

def test_no_fabricated_dates_when_inference_is_off(syllabus_bytes):
    """This syllabus contains no dates. With inference disabled, the honest
    answer is that we don't know — and every task says so."""
    plain = process_pdf(syllabus_bytes, UNDATED)
    assert plain.tasks, "must still extract the tasks"
    assert all(t.due_date is None for t in plain.tasks)
    assert all(t.date_source is DateSource.UNKNOWN for t in plain.tasks)
    assert all(t.needs_review for t in plain.tasks)


def test_inference_dates_everything_and_flags_it(result):
    assert all(t.due_date is not None for t in result.tasks)
    assert all(t.date_source is DateSource.INFERRED for t in result.tasks)
    assert all(t.needs_review for t in result.tasks), (
        "an inferred date must never look like a fact"
    )
    assert all(TERM_START <= t.due_date <= TERM_END for t in result.tasks)


def test_inferred_schedule_is_sensible(result):
    """Exams land where exams land, and four assignments don't pile up on one day."""
    final = next(t for t in result.tasks if t.type is TaskType.FINAL)
    midterm = next(t for t in result.tasks if t.type is TaskType.MIDTERM)
    assignments = sorted(
        (t for t in result.tasks if t.type is TaskType.ASSIGNMENT), key=lambda t: t.due_date
    )

    assert midterm.due_date < final.due_date
    assert final.due_date == TERM_END
    assert len({a.due_date for a in assignments}) == 4


def test_warnings_explain_the_inference(result):
    assert any("inferred" in w.lower() for w in result.meta.warnings)


# --- priority --------------------------------------------------------------

def test_final_outranks_an_assignment(result):
    final = next(t for t in result.tasks if t.type is TaskType.FINAL)
    assignment = next(t for t in result.tasks if t.type is TaskType.ASSIGNMENT)
    assert final.priority_score > assignment.priority_score


def test_every_task_can_explain_its_priority(result):
    for task in result.tasks:
        assert task.priority_reason.strip()
        assert f"{task.grade_pct:g}% of final grade" in task.priority_reason


def test_ran_offline(result):
    """No key in CI: this whole file exercises the regex baseline."""
    assert result.meta.model == "offline-regex"
    assert result.meta.pages == 3


# --- golden snapshot -------------------------------------------------------

def _snapshot(result) -> dict:
    """Everything except timing, which is not reproducible."""
    payload = result.model_dump(mode="json")
    payload["meta"].pop("processing_ms", None)
    return payload


def test_golden_snapshot(result):
    """Guards against silent drift: a prompt tweak or a scoring change that
    shifts output shows up in the diff instead of landing unnoticed.

    Regenerate deliberately with:  uv run python ml/scripts/make_golden.py
    """
    assert GOLDEN.exists(), "run ml/scripts/make_golden.py to create the snapshot"
    expected = json.loads(GOLDEN.read_text())
    expected["meta"].pop("processing_ms", None)
    assert _snapshot(result) == expected


def test_raw_text_stats_are_stable(syllabus_bytes):
    doc = extract_pdf(syllabus_bytes)
    assert doc.n_pages == 3
    assert doc.chars_per_page > 1900
