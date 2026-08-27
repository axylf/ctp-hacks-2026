"""Flask Blueprint.

Deliberately a Blueprint, not an app: the real backend is Flask, so it can do

    from ml.app.routes import syllabus_bp
    app.register_blueprint(syllabus_bp)

and the ML endpoints become part of their service. No second process, no
cross-service HTTP hop.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from pydantic import ValidationError

from .config import settings
from .ingest.pdf import is_pdf
from .pipeline import PipelineOptions, TooBlurry, analyze_tasks, process_images, process_pdf
from .schemas import DateSource, Task
from .storage import InMemoryRepository

log = logging.getLogger(__name__)

syllabus_bp = Blueprint("syllabus", __name__, url_prefix="/api")

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


def repo():
    return current_app.extensions.setdefault("syllabus_repo", InMemoryRepository())


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _options_from_request() -> PipelineOptions:
    source = request.form if request.form else (request.get_json(silent=True) or {})
    infer_raw = str(source.get("infer_dates", "true")).lower()
    return PipelineOptions(
        term_start=_parse_date(source.get("term_start")),
        term_end=_parse_date(source.get("term_end")),
        infer_dates=infer_raw not in ("false", "0", "no"),
        today=_parse_date(source.get("today")),
    )


def _error(message: str, status: int, **extra):
    return jsonify({"error": message, **extra}), status


# ---------------------------------------------------------------------------

@syllabus_bp.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "gemini_configured": settings.gemini_enabled,
            "model": settings.gemini_model if settings.gemini_enabled else "offline-regex",
            "extractor": "gemini" if settings.gemini_enabled else "offline fallback "
            "(add GEMINI_API_KEY to .env to enable Gemini)",
        }
    )


@syllabus_bp.post("/syllabus/upload")
def upload_syllabus():
    """Button 1: file upload."""
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return _error("no file uploaded; send a PDF as the 'file' field", 400)

    data = uploaded.read()
    if not data:
        return _error("uploaded file is empty", 400)
    if not is_pdf(data):
        return _error(
            f"'{uploaded.filename}' is not a PDF. Use the camera button for photos.", 400
        )

    try:
        result = process_pdf(data, _options_from_request())
    except Exception as exc:  # noqa: BLE001 - surface a usable message, log the rest
        log.exception("upload failed")
        return _error(f"could not process that PDF: {exc}", 422)

    repo().save_result(result)
    return jsonify(result.model_dump(mode="json"))


@syllabus_bp.post("/syllabus/scan")
def scan_syllabus():
    """Button 2: camera capture, one or more frames."""
    frames = request.files.getlist("images") or request.files.getlist("images[]")
    if not frames:
        single = request.files.get("image")
        frames = [single] if single else []
    if not frames:
        return _error("no images uploaded; send frames as the 'images' field", 400)
    if len(frames) > settings.max_scan_frames:
        return _error(f"too many frames (max {settings.max_scan_frames})", 400)

    payload: list[bytes] = []
    for frame in frames:
        mimetype = (frame.mimetype or "").lower()
        if mimetype and mimetype not in _ALLOWED_IMAGE_TYPES:
            return _error(f"unsupported image type: {mimetype}", 400)
        data = frame.read()
        if data:
            payload.append(data)
    if not payload:
        return _error("all uploaded frames were empty", 400)

    try:
        result = process_images(payload, _options_from_request())
    except TooBlurry as exc:
        # Distinct, actionable failure: the user can fix this by retaking.
        return _error(str(exc), 422, retake=True, reason="too_blurry")
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        log.exception("scan failed")
        return _error(f"could not process those images: {exc}", 422)

    repo().save_result(result)
    return jsonify(result.model_dump(mode="json"))


@syllabus_bp.post("/analyze")
def analyze():
    """Cross-course overlap. The backend holds the union of tasks, so this is
    where the flagship feature actually runs."""
    body = request.get_json(silent=True) or {}
    raw_tasks = body.get("tasks")
    if raw_tasks is None:
        return _error("send {'tasks': [...]} using the task shape from /syllabus/upload", 400)
    try:
        tasks = [Task.model_validate(t) for t in raw_tasks]
    except ValidationError as exc:
        return _error("invalid task payload", 400, detail=exc.errors()[:5])

    tasks, workload, recommendations = analyze_tasks(tasks, _options_from_request())
    return jsonify(
        {
            "tasks": [t.model_dump(mode="json") for t in tasks],
            "workload_analysis": workload.model_dump(mode="json"),
            "recommendations": [r.model_dump(mode="json") for r in recommendations],
        }
    )


@syllabus_bp.get("/tasks")
def list_tasks():
    tasks = repo().all_tasks()
    tasks.sort(key=lambda t: (-t.priority_score, t.due_date or date.max))
    return jsonify({"tasks": [t.model_dump(mode="json") for t in tasks]})


@syllabus_bp.patch("/tasks/<task_id>")
def update_task(task_id: str):
    """Mark complete / correct a wrong extraction — the human-in-the-loop half
    of the confidence design."""
    changes = request.get_json(silent=True) or {}
    allowed = {"completed", "title", "due_date", "type", "priority", "needs_review", "grade_pct"}
    unknown = set(changes) - allowed
    if unknown:
        return _error(f"cannot edit: {', '.join(sorted(unknown))}", 400)
    if "due_date" in changes and isinstance(changes["due_date"], str):
        parsed = _parse_date(changes["due_date"])
        if parsed is None:
            return _error("due_date must be YYYY-MM-DD", 400)
        changes["due_date"] = parsed
        changes["date_source"] = DateSource.EXPLICIT   # a human said so; trust it
        changes["needs_review"] = False

    try:
        task = repo().update_task(task_id, changes)
    except ValidationError as exc:
        return _error("invalid edit", 400, detail=exc.errors()[:5])
    if task is None:
        return _error(f"no task {task_id!r}", 404)
    return jsonify(task.model_dump(mode="json"))


@syllabus_bp.get("/demo/sample")
def demo_sample():
    """Golden fixture output. Works with no key, no upload, no network — the
    last line of defence if a live demo goes wrong."""
    import json
    from pathlib import Path

    golden = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "golden" / "intro_to_networks.json"
    if not golden.exists():
        return _error("sample not generated yet; run scripts/make_golden.py", 404)
    return current_app.response_class(
        golden.read_text(), mimetype="application/json"
    )


@syllabus_bp.get("/")
def api_root():
    return jsonify(
        {
            "service": "syllabus-intelligence-engine",
            "endpoints": sorted(
                str(rule) for rule in current_app.url_map.iter_rules()
                if str(rule).startswith("/api")
            ),
        }
    )
