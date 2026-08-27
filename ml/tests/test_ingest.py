"""Stage 1-2: does the document come in correctly, and do we pick the right path?"""
from __future__ import annotations

import pytest

from ml.app.ingest.pdf import PdfDocument, Page, extract_pdf, is_pdf, normalize_text
from ml.app.ingest.router import decide_path, decide_path_for_images
from ml.app.schemas import PipelinePath


def test_pdf_ingest(syllabus_bytes):
    doc = extract_pdf(syllabus_bytes)
    assert doc.n_pages == 3
    assert 5800 < doc.total_chars < 6200
    assert all(page.text.strip() for page in doc.pages)
    assert [p.number for p in doc.pages] == [1, 2, 3]


def test_ligatures_are_expanded(syllabus_bytes):
    """The fixture contains '30% - ﬁnal' with a U+FB01 ligature. A naive /final/
    regex misses it entirely, which would silently drop a 30%-of-grade exam."""
    doc = extract_pdf(syllabus_bytes)
    assert "ﬁ" not in doc.text, "ligature survived normalization"
    assert "final" in doc.text.lower()
    assert "official" in doc.text.lower()


def test_normalize_text_handles_smart_punctuation():
    assert normalize_text("don’t “quote” me — ok") == "don't \"quote\" me - ok"


def test_is_pdf():
    assert is_pdf(b"%PDF-1.7\n...")
    assert not is_pdf(b"\xff\xd8\xff\xe0JFIF")


def test_router_native(syllabus_bytes):
    doc = extract_pdf(syllabus_bytes)
    decision = decide_path(doc)
    assert decision.path is PipelinePath.NATIVE_TEXT
    assert decision.chars_per_page > 300


def test_router_vision_when_no_text_layer():
    doc = PdfDocument(pages=[Page(1, ""), Page(2, "  ")])
    decision = decide_path(doc)
    assert decision.path is PipelinePath.VISION
    assert decision.vision_pages == [1, 2]


def test_router_hybrid_for_mixed_document():
    """A digital syllabus with a scanned appendix stapled on."""
    doc = PdfDocument(pages=[Page(1, "x" * 900), Page(2, "")])
    decision = decide_path(doc)
    assert decision.path is PipelinePath.HYBRID
    assert decision.vision_pages == [2]


def test_router_images_always_vision():
    assert decide_path_for_images(3).path is PipelinePath.VISION


@pytest.mark.parametrize("threshold,expected", [(300, PipelinePath.NATIVE_TEXT), (99_000, PipelinePath.VISION)])
def test_router_threshold_is_configurable(syllabus_bytes, threshold, expected):
    assert decide_path(extract_pdf(syllabus_bytes), threshold).path is expected
