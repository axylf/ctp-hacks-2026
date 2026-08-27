"""Shared fixtures.

No test in this suite calls the real Gemini API. The client is mocked at the
module boundary, so the whole suite is free, offline, deterministic and CI-safe.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import cv2
import numpy as np
import pytest

from ml.app import create_app
from ml.app.config import settings as real_settings
from ml.app.schemas import DateSource, Task, TaskType

FIXTURES = Path(__file__).parent / "fixtures"
SYLLABUS_PDF = FIXTURES / "syllabi" / "intro_to_networks_spring2026.pdf"

# Fixed "today" so priority scores and golden snapshots are reproducible.
TODAY = date(2026, 2, 1)
TERM_START = date(2026, 1, 26)
TERM_END = date(2026, 5, 20)


@pytest.fixture(scope="session")
def syllabus_bytes() -> bytes:
    return SYLLABUS_PDF.read_bytes()


# --- synthetic page images -------------------------------------------------

def make_page_image(width: int = 1000, height: int = 1300, lines: int = 26) -> np.ndarray:
    """A white page with black bars standing in for text lines.

    Real enough for the geometry stages, which only care about the orientation
    and extent of dark pixels — not about glyphs.
    """
    img = np.full((height, width, 3), 245, dtype=np.uint8)
    top, margin = 90, 80
    for i in range(lines):
        y = top + i * 42
        if y > height - 80:
            break
        # Vary line length so the text block isn't a perfect rectangle — a
        # deskew that only works on perfect rectangles isn't worth much.
        end = width - margin - (140 if i % 5 == 4 else 0)
        cv2.rectangle(img, (margin, y), (end, y + 16), (25, 25, 25), -1)
    return img


def encode(img: np.ndarray, ext: str = ".png") -> bytes:
    ok, buf = cv2.imencode(ext, img)
    assert ok
    return buf.tobytes()


@pytest.fixture
def page_image() -> np.ndarray:
    return make_page_image()


@pytest.fixture
def page_png(page_image) -> bytes:
    return encode(page_image)


@pytest.fixture
def page_jpeg(page_image) -> bytes:
    return encode(page_image, ".jpg")


# --- Gemini mocking --------------------------------------------------------

@pytest.fixture
def fake_gemini(monkeypatch):
    """Install a stand-in for the model. Usage:

        fake_gemini(returns=some_RawExtraction)      # happy path
        fake_gemini(raises=GeminiUnavailable("..."))  # degradation path
    """
    from ml.app import pipeline
    from ml.app.extract.gemini import GeminiResult

    def install(returns=None, raises=None, model="gemini-2.5-flash-mock"):
        keyed = dataclasses.replace(real_settings, gemini_api_key="test-key-not-real")
        monkeypatch.setattr(pipeline, "settings", keyed)

        def handler(*args, **kwargs):
            if raises is not None:
                raise raises
            return GeminiResult(extraction=returns, model=model)

        monkeypatch.setattr(pipeline, "extract_from_text", handler)
        monkeypatch.setattr(pipeline, "extract_from_images", handler)
        return keyed

    return install


# --- task builder ----------------------------------------------------------

def make_task(
    task_id: str,
    title: str,
    task_type: TaskType,
    due: date | None,
    grade_pct: float | None = None,
    course: str = "TEST 101",
) -> Task:
    return Task(
        id=task_id,
        course_code=course,
        title=title,
        type=task_type,
        due_date=due,
        date_source=DateSource.EXPLICIT if due else DateSource.UNKNOWN,
        grade_pct=grade_pct,
        confidence=0.9,
    )


@pytest.fixture
def task_factory():
    return make_task


# --- Flask -----------------------------------------------------------------

@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def term_form() -> dict:
    return {
        "term_start": TERM_START.isoformat(),
        "term_end": TERM_END.isoformat(),
        "today": TODAY.isoformat(),
    }
