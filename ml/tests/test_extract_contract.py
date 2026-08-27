"""Stage 4: the model boundary.

Nothing here touches the network. These tests pin down what happens when the
model behaves, misbehaves, is rate-limited, or is missing entirely.
"""
from __future__ import annotations

from datetime import date

import pytest

from ml.app.extract import fallback, gemini
from ml.app.extract.gemini import GeminiUnavailable, is_retryable, parse_response_text
from ml.app.pipeline import PipelineOptions, process_pdf
from ml.app.schemas import (
    DateSource,
    PipelinePath,
    RawCourse,
    RawExtraction,
    RawTask,
    TaskType,
)
from ml.tests.conftest import TERM_END, TERM_START, TODAY

OPTIONS = PipelineOptions(term_start=TERM_START, term_end=TERM_END, today=TODAY)


def _raw(tasks: list[RawTask]) -> RawExtraction:
    return RawExtraction(
        course=RawCourse(code="CMP 405/743", name="Intro to Networks",
                         term="Spring 2026", confidence=0.95),
        tasks=tasks,
    )


# --- parsing ---------------------------------------------------------------

def test_schema_enforced(syllabus_bytes, fake_gemini):
    """A well-formed model response flows through into the contract types."""
    fake_gemini(returns=_raw([
        RawTask(title="Midterm", type=TaskType.MIDTERM, due_raw="March 10",
                grade_pct=20.0, confidence=0.9, source_page=2,
                source_quote="20% - midterm"),
    ]))
    result = process_pdf(syllabus_bytes, OPTIONS)

    assert result.meta.pipeline_path is PipelinePath.NATIVE_TEXT
    assert result.meta.model == "gemini-2.5-flash-mock"
    task = result.tasks[0]
    assert task.title == "Midterm"
    assert task.due_date == date(2026, 3, 10)
    assert task.date_source is DateSource.EXPLICIT
    assert task.source_quote == "20% - midterm"


def test_parse_strips_markdown_fences():
    parsed = parse_response_text('```json\n{"course":{"code":"X 1"},"tasks":[]}\n```')
    assert parsed.course.code == "X 1"


def test_parse_rejects_empty_response():
    with pytest.raises(ValueError, match="empty response"):
        parse_response_text("   ")


def test_malformed_response_falls_back(syllabus_bytes, fake_gemini):
    """Garbage from the model must not take the request down with it."""
    fake_gemini(raises=ValueError("Expecting value: line 1 column 1"))
    result = process_pdf(syllabus_bytes, OPTIONS)

    assert result.meta.pipeline_path is PipelinePath.FALLBACK
    assert result.meta.model == "offline-regex"
    assert result.tasks, "fallback must still produce tasks"


def test_api_down_degrades(syllabus_bytes, fake_gemini):
    fake_gemini(raises=GeminiUnavailable("503 backend unavailable"))
    result = process_pdf(syllabus_bytes, OPTIONS)
    assert result.meta.pipeline_path is PipelinePath.FALLBACK
    assert len(result.tasks) == 6


def test_empty_extraction_falls_back(syllabus_bytes, fake_gemini):
    """A model that returns zero tasks on a syllabus that plainly has some is
    wrong; prefer the regex baseline over an empty planner."""
    fake_gemini(returns=_raw([]))
    result = process_pdf(syllabus_bytes, OPTIONS)
    assert result.meta.pipeline_path is PipelinePath.FALLBACK
    assert result.tasks


# --- retries ---------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [(429, True), (500, True), (503, True),
                                           (400, False), (401, False), (404, False)])
def test_retryable_classification(code, expected):
    assert is_retryable(type("Err", (Exception,), {"code": code})()) is expected


def test_api_error_retry(monkeypatch):
    """429 then success: exactly one retry, and the result comes through."""
    calls = {"n": 0}

    class _Models:
        def generate_content(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise type("RateLimit", (Exception,), {"code": 429})("429 too many requests")
            return type("R", (), {"text": '{"course":{"code":"CMP 405"},"tasks":[]}'})()

    monkeypatch.setattr(gemini, "_build_client", lambda: type("C", (), {"models": _Models()})())
    monkeypatch.setattr(gemini, "_config", lambda: None)
    monkeypatch.setattr(gemini.time, "sleep", lambda _: None)

    result = gemini.extract_from_text("some syllabus text")
    assert calls["n"] == 2
    assert result.extraction.course.code == "CMP 405"


def test_non_retryable_error_fails_fast(monkeypatch):
    calls = {"n": 0}

    class _Models:
        def generate_content(self, **kwargs):
            calls["n"] += 1
            raise type("BadRequest", (Exception,), {"code": 400})("400 invalid argument")

    monkeypatch.setattr(gemini, "_build_client", lambda: type("C", (), {"models": _Models()})())
    monkeypatch.setattr(gemini, "_config", lambda: None)

    with pytest.raises(GeminiUnavailable):
        gemini.extract_from_text("text")
    assert calls["n"] == 1, "a 400 must not burn the retry budget"


def test_no_key_is_a_clean_unavailable(monkeypatch):
    """The error names the fix, because this is the one setup step."""
    import dataclasses

    monkeypatch.setattr(gemini, "settings", dataclasses.replace(gemini.settings, gemini_api_key=""))
    with pytest.raises(GeminiUnavailable, match="GEMINI_API_KEY"):
        gemini.extract_from_text("text")


# --- the rule that matters most -------------------------------------------

def test_no_hallucinated_dates(syllabus_bytes, fake_gemini):
    """The model returning due_raw="" is CORRECT behavior, not a failure.
    With inference off, those dates must stay null and be flagged."""
    fake_gemini(returns=_raw([
        RawTask(title="Final", type=TaskType.FINAL, due_raw="", grade_pct=30.0, confidence=0.9),
        RawTask(title="Midterm", type=TaskType.MIDTERM, due_raw="", grade_pct=20.0, confidence=0.9),
    ]))
    result = process_pdf(
        syllabus_bytes,
        PipelineOptions(term_start=TERM_START, term_end=TERM_END, today=TODAY, infer_dates=False),
    )

    assert all(t.due_date is None for t in result.tasks)
    assert all(t.date_source is DateSource.UNKNOWN for t in result.tasks)
    assert all(t.needs_review for t in result.tasks)


def test_unresolvable_date_is_flagged_not_dropped(syllabus_bytes, fake_gemini):
    """'TBA' is a date the syllabus printed. We can't resolve it, so we say so."""
    fake_gemini(returns=_raw([
        RawTask(title="Project", type=TaskType.PROJECT, due_raw="TBA", grade_pct=25.0),
    ]))
    result = process_pdf(syllabus_bytes, PipelineOptions(
        term_start=TERM_START, term_end=TERM_END, today=TODAY, infer_dates=False))

    assert result.tasks[0].needs_review
    assert any("TBA" in w for w in result.meta.warnings)


def test_low_confidence_forces_review(syllabus_bytes, fake_gemini):
    fake_gemini(returns=_raw([
        RawTask(title="Mystery Item", type=TaskType.OTHER, due_raw="March 3", confidence=0.3),
    ]))
    result = process_pdf(syllabus_bytes, OPTIONS)
    assert result.tasks[0].needs_review


def test_count_expands_into_separate_tasks(syllabus_bytes, fake_gemini):
    """'~4 programming assignments (40%)' is one model entry and four to-dos,
    each carrying a quarter of the weight."""
    fake_gemini(returns=_raw([
        RawTask(title="Programming Assignments", type=TaskType.ASSIGNMENT,
                due_raw="", grade_pct=40.0, count=4, confidence=0.9),
    ]))
    result = process_pdf(syllabus_bytes, OPTIONS)

    assert len(result.tasks) == 4
    assert {t.title for t in result.tasks} == {
        f"Programming Assignment {i}" for i in range(1, 5)
    }
    assert all(t.grade_pct == 10.0 for t in result.tasks)
    assert len({t.id for t in result.tasks}) == 4, "ids must be unique"


def test_fallback_and_gemini_agree_on_the_fixture(syllabus_bytes):
    """The regex baseline is what the eval harness measures Gemini against, so
    it has to be genuinely competent, not a stub."""
    from ml.app.ingest.pdf import extract_pdf

    doc = extract_pdf(syllabus_bytes)
    raw = fallback.extract(doc.text, [p.text for p in doc.pages])
    types_found = {t.type for t in raw.tasks}
    assert TaskType.FINAL in types_found
    assert TaskType.MIDTERM in types_found
    assert TaskType.ASSIGNMENT in types_found
