"""The Flask surface — the two buttons, end to end.

Gemini is mocked where a vision path is being asserted; everything else runs on
the offline extractor, which is how CI will run it.
"""
from __future__ import annotations

import io
from datetime import date

import cv2
import pytest
from werkzeug.datastructures import MultiDict

from ml.app.schemas import PipelinePath, RawCourse, RawExtraction, RawTask, TaskType
from ml.tests.conftest import TERM_END, TERM_START, TODAY, encode, make_page_image, make_task

pytestmark = pytest.mark.usefixtures("client")


def _pdf_upload(syllabus_bytes, **form):
    data = {"file": (io.BytesIO(syllabus_bytes), "syllabus.pdf", "application/pdf")}
    data.update(form)
    return data


# --- health ----------------------------------------------------------------

def test_health_reports_whether_a_key_is_configured(client):
    body = client.get("/api/health").get_json()
    assert body["status"] == "ok"
    assert "gemini_configured" in body
    if not body["gemini_configured"]:
        assert "GEMINI_API_KEY" in body["extractor"]


def test_api_root_lists_endpoints(client):
    endpoints = client.get("/api/").get_json()["endpoints"]
    assert "/api/syllabus/upload" in endpoints
    assert "/api/syllabus/scan" in endpoints


# --- button 1: file upload -------------------------------------------------

def test_upload_pdf_endpoint(client, syllabus_bytes, term_form):
    response = client.post(
        "/api/syllabus/upload",
        data=_pdf_upload(syllabus_bytes, **term_form),
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    body = response.get_json()

    assert body["course"]["code"] == "CMP 405/743"
    assert len(body["tasks"]) == 6
    assert body["meta"]["pages"] == 3
    assert body["meta"]["grade_weight_total"] == 100.0
    # Contract shape, as documented for the frontend.
    for key in ("course", "tasks", "workload_analysis", "recommendations", "meta"):
        assert key in body
    for key in ("id", "title", "type", "due_date", "priority", "priority_reason",
                "needs_review", "date_source", "source_quote"):
        assert key in body["tasks"][0]


def test_upload_respects_infer_dates_false(client, syllabus_bytes, term_form):
    response = client.post(
        "/api/syllabus/upload",
        data=_pdf_upload(syllabus_bytes, infer_dates="false", **term_form),
        content_type="multipart/form-data",
    )
    body = response.get_json()
    assert all(t["due_date"] is None for t in body["tasks"])
    assert all(t["needs_review"] for t in body["tasks"])


def test_upload_uses_supplied_term_dates(client, syllabus_bytes):
    response = client.post(
        "/api/syllabus/upload",
        data=_pdf_upload(syllabus_bytes, term_start="2026-09-01",
                         term_end="2026-12-15", today="2026-09-05"),
        content_type="multipart/form-data",
    )
    body = response.get_json()
    assert all("2026-09-01" <= t["due_date"] <= "2026-12-15" for t in body["tasks"])


def test_reject_non_pdf(client):
    response = client.post(
        "/api/syllabus/upload",
        data={"file": (io.BytesIO(b"MZ\x90\x00fake exe"), "virus.exe",
                       "application/octet-stream")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "not a PDF" in response.get_json()["error"]


def test_reject_missing_file(client):
    response = client.post("/api/syllabus/upload", data={},
                           content_type="multipart/form-data")
    assert response.status_code == 400
    assert "no file" in response.get_json()["error"]


def test_reject_empty_file(client):
    response = client.post(
        "/api/syllabus/upload",
        data={"file": (io.BytesIO(b""), "empty.pdf", "application/pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_reject_oversize(client, app):
    app.config["MAX_CONTENT_LENGTH"] = 1024
    response = client.post(
        "/api/syllabus/upload",
        data={"file": (io.BytesIO(b"%PDF-" + b"x" * 5000), "big.pdf", "application/pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413
    assert "too large" in response.get_json()["error"]


# --- button 2: camera scan -------------------------------------------------

def _frames(n: int = 1, blur: bool = False) -> list[bytes]:
    out = []
    for i in range(n):
        img = make_page_image(lines=20 + i)
        if blur:
            img = cv2.GaussianBlur(img, (31, 31), 12)
        out.append(encode(img, ".jpg"))
    return out


def test_scan_endpoint(client, fake_gemini, term_form):
    """One camera frame, Gemini mocked -> the vision path runs."""
    fake_gemini(returns=RawExtraction(
        course=RawCourse(code="CMP 405/743", name="Intro to Networks",
                         term="Spring 2026", confidence=0.9),
        tasks=[RawTask(title="Midterm", type=TaskType.MIDTERM, due_raw="March 10",
                       grade_pct=20.0, confidence=0.9, source_page=1,
                       source_quote="20% - midterm")],
    ))
    data = {"images": (io.BytesIO(_frames(1)[0]), "page1.jpg", "image/jpeg")}
    data.update(term_form)

    response = client.post("/api/syllabus/scan", data=data,
                           content_type="multipart/form-data")
    assert response.status_code == 200
    body = response.get_json()
    assert body["meta"]["pipeline_path"] == PipelinePath.VISION.value
    assert body["tasks"][0]["due_date"] == "2026-03-10"


def test_scan_multi_page(client, fake_gemini, term_form):
    """Three frames go into ONE extraction call, so a course name on page 1 and
    a deadline on page 3 stay attached to each other."""
    fake_gemini(returns=RawExtraction(
        course=RawCourse(code="CMP 405/743", name="Intro to Networks", term="Spring 2026"),
        tasks=[
            RawTask(title="Midterm", type=TaskType.MIDTERM, due_raw="March 10", grade_pct=20.0),
            RawTask(title="Final", type=TaskType.FINAL, due_raw="May 18", grade_pct=30.0),
        ],
    ))

    # NOTE: MultiDict, not dict -- "images" repeats, and a plain dict would
    # silently collapse three frames into one.
    data = MultiDict(
        [("images", (io.BytesIO(f), f"page{i}.jpg", "image/jpeg"))
         for i, f in enumerate(_frames(3), start=1)]
        + list(term_form.items())
    )
    response = client.post("/api/syllabus/scan", data=data,
                           content_type="multipart/form-data")
    assert response.status_code == 200
    body = response.get_json()
    assert body["meta"]["pages"] == 3
    assert {t["title"] for t in body["tasks"]} == {"Midterm", "Final"}


def test_scan_reports_an_empty_vision_extraction(client, fake_gemini, term_form):
    fake_gemini(returns=RawExtraction(
        course=RawCourse(code="CMP 405/743", name="Intro to Networks"), tasks=[]
    ))
    data = {"images": (io.BytesIO(_frames(1)[0]), "page1.jpg", "image/jpeg")}
    data.update(term_form)

    response = client.post("/api/syllabus/scan", data=data,
                           content_type="multipart/form-data")
    assert response.status_code == 422
    assert response.get_json()["reason"] == "no_tasks_found"


def test_scan_rejects_blurry_frames_before_calling_the_model(client, term_form):
    """A too-blurry photo must fail with a retake prompt, not a wasted API call."""
    data = {"images": (io.BytesIO(_frames(1, blur=True)[0]), "blurry.jpg", "image/jpeg")}
    data.update(term_form)
    response = client.post("/api/syllabus/scan", data=data,
                           content_type="multipart/form-data")

    assert response.status_code == 422
    body = response.get_json()
    assert body["retake"] is True
    assert body["reason"] == "too_blurry"


def test_scan_requires_images(client):
    response = client.post("/api/syllabus/scan", data={},
                           content_type="multipart/form-data")
    assert response.status_code == 400
    assert "no images" in response.get_json()["error"]


def test_scan_rejects_a_pdf_sent_to_the_camera_endpoint(client, syllabus_bytes):
    response = client.post(
        "/api/syllabus/scan",
        data={"images": (io.BytesIO(syllabus_bytes), "syllabus.pdf", "application/pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "unsupported image type" in response.get_json()["error"]


def test_scan_rejects_too_many_frames(client):
    data = MultiDict([("images", (io.BytesIO(f), f"p{i}.jpg", "image/jpeg"))
                      for i, f in enumerate(_frames(1) * 13)])
    response = client.post("/api/syllabus/scan", data=data,
                           content_type="multipart/form-data")
    assert response.status_code == 400
    assert "too many frames" in response.get_json()["error"]


# --- cross-course analysis -------------------------------------------------

def test_analyze_multi_course(client):
    """The flagship feature: three courses colliding in one week. Only the
    backend holds the union of tasks, so this is where it runs."""
    tasks = [
        make_task("cs-final", "Final Exam", TaskType.FINAL, date(2026, 5, 12), 30.0, "CMP 405"),
        make_task("hist-paper", "Term Paper", TaskType.PAPER, date(2026, 5, 13), 25.0, "HIS 210"),
        make_task("bio-proj", "Lab Project", TaskType.PROJECT, date(2026, 5, 14), 20.0, "BIO 180"),
        make_task("math-quiz", "Quiz 9", TaskType.QUIZ, date(2026, 3, 3), 5.0, "MAT 175"),
    ]
    response = client.post("/api/analyze", json={
        "tasks": [t.model_dump(mode="json") for t in tasks],
        "today": TODAY.isoformat(),
    })
    assert response.status_code == 200
    body = response.get_json()

    critical = [w for w in body["workload_analysis"]["windows"] if w["severity"] == "critical"]
    assert critical, "three majors in three days must be critical"
    assert len(critical[0]["task_ids"]) == 3
    assert any(r["type"] == "start_early" for r in body["recommendations"])
    # The lone March quiz must not be swept into the May crunch.
    assert "math-quiz" not in critical[0]["task_ids"]


def test_analyze_rejects_a_bad_payload(client):
    assert client.post("/api/analyze", json={}).status_code == 400
    bad = client.post("/api/analyze", json={"tasks": [{"nope": 1}]})
    assert bad.status_code == 400
    assert "detail" in bad.get_json()


# --- editing (human in the loop) ------------------------------------------

def test_mark_task_complete(client, syllabus_bytes, term_form):
    upload = client.post("/api/syllabus/upload",
                         data=_pdf_upload(syllabus_bytes, **term_form),
                         content_type="multipart/form-data").get_json()
    task_id = upload["tasks"][0]["id"]

    patched = client.patch(f"/api/tasks/{task_id}", json={"completed": True})
    assert patched.status_code == 200
    assert patched.get_json()["completed"] is True
    assert client.get("/api/tasks").get_json()["tasks"]


def test_correcting_a_date_clears_the_review_flag(client, syllabus_bytes, term_form):
    """The other half of the confidence design: a human overrides the guess and
    the task stops being flagged."""
    upload = client.post("/api/syllabus/upload",
                         data=_pdf_upload(syllabus_bytes, **term_form),
                         content_type="multipart/form-data").get_json()
    task_id = next(t["id"] for t in upload["tasks"] if t["needs_review"])

    patched = client.patch(f"/api/tasks/{task_id}", json={"due_date": "2026-04-02"})
    body = patched.get_json()
    assert body["due_date"] == "2026-04-02"
    assert body["date_source"] == "explicit"
    assert body["needs_review"] is False


def test_reject_bad_edits(client, syllabus_bytes, term_form):
    upload = client.post("/api/syllabus/upload",
                         data=_pdf_upload(syllabus_bytes, **term_form),
                         content_type="multipart/form-data").get_json()
    task_id = upload["tasks"][0]["id"]

    assert client.patch(f"/api/tasks/{task_id}", json={"id": "hacked"}).status_code == 400
    assert client.patch(f"/api/tasks/{task_id}", json={"due_date": "nonsense"}).status_code == 400
    assert client.patch("/api/tasks/does-not-exist", json={"completed": True}).status_code == 404


# --- demo fallbacks --------------------------------------------------------

def test_demo_sample_needs_no_key_and_no_upload(client):
    body = client.get("/api/demo/sample").get_json()
    assert body["course"]["code"] == "CMP 405/743"
    assert len(body["tasks"]) == 6


def test_demo_page_serves(client):
    page = client.get("/")
    assert page.status_code == 200
    assert b"Upload Syllabus PDF" in page.data
    assert b"Scan with Camera" in page.data
