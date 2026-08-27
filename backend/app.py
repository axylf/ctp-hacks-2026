import hashlib
import logging
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np
import pytesseract

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback for lean Python envs
    def load_dotenv(path: str | os.PathLike[str] | None = None, *args, **kwargs):
        env_path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / ".env"
        if not env_path.exists():
            return False
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))
        return True

from supabase import create_client, Client

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

try:
    from env_config import get_supabase_url, get_supabase_key
except ImportError:  # pragma: no cover
    def get_supabase_url() -> str:
        return os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")

    def get_supabase_key() -> str:
        return (
            os.getenv("SUPABASE_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or ""
        )

from flask import Flask, jsonify, request
from flask_cors import CORS

try:
    import fitz
except ModuleNotFoundError:  # pragma: no cover - compatibility fallback
    import pymupdf as fitz


def configure_tesseract_path() -> None:
    """Ensure pytesseract can locate the Tesseract binary on Windows."""
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]

    tesseract_path = shutil.which("tesseract")
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        return

    for candidate in candidates:
        if os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


configure_tesseract_path()

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
CORS(app, resources={r"/api/*": {"origins": "*"}})

try:
    from ml.app.routes import syllabus_bp
    app.register_blueprint(syllabus_bp)
except Exception:
    logging.getLogger(__name__).exception("Unable to register ML syllabus blueprint")
    syllabus_bp = None

SUPABASE_URL = get_supabase_url()
SUPABASE_KEY = get_supabase_key()


def preprocess_image(image_bytes: bytes):
    """Decode image bytes and prepare them for OCR using OpenCV."""
    np_image = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(np_image, cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError("Unable to decode uploaded image.")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def extract_text_from_image(image_bytes: bytes) -> str:
    """Use OpenCV preprocessing before passing the image to Tesseract."""
    processed = preprocess_image(image_bytes)
    text = pytesseract.image_to_string(processed, config="--psm 6")

    if not text.strip():
        fallback = cv2.cvtColor(
            cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR),
            cv2.COLOR_BGR2GRAY,
        )
        text = pytesseract.image_to_string(fallback, config="--psm 6")

    return text.strip()


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Render each PDF page to an image and OCR the text on each page."""
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError("Unable to read PDF file.") from exc

    page_texts = []

    try:
        for page_number in range(document.page_count):
            page = document.load_page(page_number)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            image_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)

            if pix.n == 4:
                image_array = cv2.cvtColor(image_array, cv2.COLOR_BGRA2BGR)

            _, buffer = cv2.imencode(".png", image_array)
            page_text = extract_text_from_image(buffer.tobytes())
            if page_text:
                page_texts.append(page_text)
    finally:
        document.close()

    combined = "\n\n".join(page_texts).strip()
    if not combined:
        raise ValueError("No text found in PDF.")

    return combined


@app.get("/")
def index():
    return jsonify({
        "service": "Image OCR API",
        "status": "running",
        "endpoints": [
            {"method": "GET", "path": "/api/health"},
            {"method": "POST", "path": "/api/ocr"},
            {"method": "POST", "path": "/api/extract-text"},
            {"method": "POST", "path": "/api/syllabus/upload"},
            {"method": "POST", "path": "/api/syllabus/scan"},
            {"method": "POST", "path": "/api/analyze"},
        ],
    })


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "Image OCR API"})


def get_supabase_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase URL/key are not configured.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upsert_user(email: str, name: str | None = None) -> dict:
    client = get_supabase_client()
    clean_email = (email or "").strip().lower()
    if not clean_email:
        raise ValueError("A valid user email is required.")

    payload = {"email": clean_email}
    if name:
        payload["name"] = name

    response = client.table("users").upsert(payload, on_conflict="email").execute()
    data = response.data or []
    if not data:
        raise ValueError("Supabase user upsert returned no rows.")
    return data[0]


def upsert_course(user_id: str, code: str, name: str, institution: str | None = None, term: str | None = None,
                  instructor: str | None = None, meeting_times: str | None = None, confidence: float = 0.5) -> dict:
    if not code or not name:
        raise ValueError("Course code and name are required.")

    client = get_supabase_client()
    query = client.table("courses").select("*").eq("user_id", user_id).eq("code", code)
    if term is None:
        query = query.is_("term", "null")
    else:
        query = query.eq("term", term)

    existing = query.execute()
    rows = existing.data or []
    payload = {
        "user_id": user_id,
        "code": code,
        "name": name,
        "institution": institution,
        "term": term,
        "instructor": instructor,
        "meeting_times": meeting_times,
        "confidence": float(confidence),
    }

    if rows:
        course_id = rows[0]["id"]
        response = client.table("courses").update(payload).eq("id", course_id).execute()
        data = response.data or []
        if not data:
            raise ValueError("Supabase course update returned no rows.")
        return data[0]

    response = client.table("courses").insert(payload).execute()
    data = response.data or []
    if not data:
        raise ValueError("Supabase course insert returned no rows.")
    return data[0]


def save_extracted_syllabus_to_supabase(
    *,
    user_email: str,
    filename: str,
    mime_type: str,
    file_bytes: bytes,
    extracted_text: str,
    source: str = "file",
    course_code: str | None = None,
    course_name: str | None = None,
    term: str | None = None,
    institution: str | None = None,
    instructor: str | None = None,
    meeting_times: str | None = None,
    model: str | None = "tesseract",
    pipeline_path: str = "native_text",
    page_count: int = 1,
) -> dict:
    if not extracted_text or not extracted_text.strip():
        raise ValueError("Extracted text is empty; cannot save a syllabus record.")

    user = upsert_user(user_email)
    course_id = None
    if course_code and course_name:
        course = upsert_course(
            user_id=user["id"],
            code=course_code,
            name=course_name,
            institution=institution,
            term=term,
            instructor=instructor,
            meeting_times=meeting_times,
        )
        course_id = course["id"]

    client = get_supabase_client()
    storage_key = f"syllabi/{user['id']}/{uuid.uuid4()}-{(filename or 'syllabus').replace(os.sep, '_')}"
    content_sha256 = hashlib.sha256(file_bytes or extracted_text.encode("utf-8")).hexdigest()
    started_at = time.time()
    payload = {
        "user_id": user["id"],
        "source": source if source in {"file", "camera"} else "file",
        "original_filename": filename,
        "mime_type": mime_type or "application/octet-stream",
        "byte_size": len(file_bytes or b""),
        "storage_key": storage_key,
        "content_sha256": content_sha256,
        "page_count": max(1, int(page_count)),
        "status": "succeeded",
        "pipeline_path": pipeline_path if pipeline_path in {"native_text", "vision", "hybrid", "fallback"} else "native_text",
        "model": model,
        "processing_ms": max(1, int((time.time() - started_at) * 1000)),
        "warnings": [],
        "extraction_json": {
            "raw_text": extracted_text,
            "pages": [{"page_number": i, "text": extracted_text} for i in range(1, max(1, int(page_count)) + 1)],
            "course_code": course_code,
            "course_name": course_name,
            "term": term,
        },
        "course_id": course_id,
        "infer_dates": True,
    }

    upload_response = client.table("syllabus_uploads").insert(payload).execute()
    upload_rows = upload_response.data or []
    if not upload_rows:
        raise ValueError("Supabase syllabus upload insert returned no rows.")
    upload = upload_rows[0]

    page_rows = []
    for page_number in range(1, max(1, int(page_count)) + 1):
        page_payload = {
            "upload_id": upload["id"],
            "page_number": page_number,
            "storage_key": storage_key,
            "blur_score": None,
            "document_found": True,
            "skew_corrected_deg": None,
            "accepted": True,
            "warnings": [],
            "extracted_chars": len(extracted_text),
        }
        page_response = client.table("syllabus_upload_pages").insert(page_payload).execute()
        page_rows.extend(page_response.data or [])

    return {
        "user": user,
        "course": course_id,
        "upload": upload,
        "pages": page_rows,
    }


def autosave_ocr_result(
    *,
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
    extracted_text: str,
    user_email: str | None = None,
    course_code: str | None = None,
    course_name: str | None = None,
    term: str | None = None,
    institution: str | None = None,
    instructor: str | None = None,
    meeting_times: str | None = None,
    model: str | None = "tesseract",
    pipeline_path: str = "native_text",
    page_count: int = 1,
):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"saved": False, "reason": "supabase_not_configured"}
    if not user_email:
        return {"saved": False, "reason": "missing_user_email"}

    try:
        result = save_extracted_syllabus_to_supabase(
            user_email=user_email,
            filename=file_name,
            mime_type=mime_type or "application/octet-stream",
            file_bytes=file_bytes,
            extracted_text=extracted_text,
            source="file",
            course_code=course_code,
            course_name=course_name,
            term=term,
            institution=institution,
            instructor=instructor,
            meeting_times=meeting_times,
            model=model,
            pipeline_path=pipeline_path,
            page_count=page_count,
        )
        return {"saved": True, "data": result}
    except Exception as exc:  # pragma: no cover - depends on Supabase connectivity
        return {"saved": False, "reason": "supabase_write_failed", "error": str(exc)}


def load_supabase_dashboard(user_email: str | None) -> dict:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"courses": [], "assignments": [], "documents": [], "recommendations": []}

    email = (user_email or "alex@example.com").strip().lower()
    client = get_supabase_client()
    user_response = client.table("users").select("*").eq("email", email).limit(1).execute()
    user_rows = user_response.data or []
    if not user_rows:
        return {"courses": [], "assignments": [], "documents": [], "recommendations": []}

    user = user_rows[0]
    course_response = client.table("courses").select("*").eq("user_id", user["id"]).order("created_at", desc=True).execute()
    course_rows = course_response.data or []
    upload_response = client.table("syllabus_uploads").select("*").eq("user_id", user["id"]).order("created_at", desc=True).execute()
    upload_rows = upload_response.data or []
    task_response = client.table("tasks").select("*").eq("user_id", user["id"]).order("due_date", desc=False).execute()
    task_rows = task_response.data or []

    course_map = {course["id"]: course for course in course_rows}
    courses = [
        {
            "id": course["id"],
            "code": course["code"],
            "name": course["name"],
            "institution": course.get("institution"),
            "term": course.get("term"),
            "instructor": course.get("instructor"),
            "meeting_times": course.get("meeting_times"),
        }
        for course in course_rows
    ]

    documents = [
        {
            "id": upload["id"],
            "name": upload.get("original_filename") or "syllabus-upload",
            "source": upload.get("source") or "file",
            "pageCount": upload.get("page_count") or 1,
            "pages": [],
            "mimeType": upload.get("mime_type") or "application/octet-stream",
            "size": upload.get("byte_size") or 0,
            "addedAt": upload.get("created_at") or upload.get("updated_at"),
            "taskIds": [],
        }
        for upload in upload_rows
    ]

    assignments = []
    for task in task_rows:
        due_date = task.get("due_date")
        course = course_map.get(task.get("course_id"), {})
        course_code = course.get("code") or "COURSE"
        week_label = None
        if due_date:
            try:
                from datetime import date as _date
                week_label = str(_date.fromisoformat(due_date).isocalendar().week)
            except Exception:
                week_label = None

        assignments.append({
            "id": task["id"],
            "title": task.get("title") or "Untitled task",
            "type": task.get("type") or "assignment",
            "due_date": due_date,
            "course_code": course_code,
            "course_name": course.get("name") or "Untitled course",
            "course_id": task.get("course_id"),
            "priority": task.get("priority") or "medium",
            "priority_reason": task.get("priority_reason") or "",
            "needs_review": bool(task.get("needs_review")),
            "source_quote": task.get("source_quote") or "",
            "week_label": week_label,
            "completed": bool(task.get("completed")),
        })

    return {
        "courses": courses,
        "assignments": assignments,
        "documents": documents,
        "recommendations": [],
        "user": user,
    }


@app.get("/api/supabase/dashboard")
def supabase_dashboard():
    user_email = request.args.get("user_email") or os.getenv("VITE_DEMO_USER_EMAIL") or "alex@example.com"
    return jsonify(load_supabase_dashboard(user_email))


@app.post("/api/ocr")
@app.post("/api/extract-text")
def extract_text():
    file = request.files.get("image") or request.files.get("file")

    if file is None or file.filename == "":
        return jsonify({"error": "No file uploaded."}), 400

    file_bytes = file.read()
    mimetype = file.mimetype or ""
    form_values = request.form.to_dict()
    user_email = form_values.get("user_email") or request.args.get("user_email")
    course_code = form_values.get("course_code")
    course_name = form_values.get("course_name")
    term = form_values.get("term")
    institution = form_values.get("institution")
    instructor = form_values.get("instructor")
    meeting_times = form_values.get("meeting_times")
    model = form_values.get("model") or "tesseract"
    pipeline_path = form_values.get("pipeline_path") or "native_text"

    try:
        if mimetype == "application/pdf":
            text = extract_text_from_pdf(file_bytes)
            save_result = autosave_ocr_result(
                file_bytes=file_bytes,
                file_name=file.filename,
                mime_type=mimetype,
                extracted_text=text,
                user_email=user_email,
                course_code=course_code,
                course_name=course_name,
                term=term,
                institution=institution,
                instructor=instructor,
                meeting_times=meeting_times,
                model=model,
                pipeline_path=pipeline_path,
                page_count=1,
            )
            return jsonify({
                "filename": file.filename,
                "text": text,
                "type": "pdf",
                "saved_to_supabase": save_result.get("saved", False),
                "supabase_save": save_result,
            })

        if not mimetype.startswith("image/"):
            return jsonify({"error": "Uploaded file must be an image or PDF."}), 400

        text = extract_text_from_image(file_bytes)
        save_result = autosave_ocr_result(
            file_bytes=file_bytes,
            file_name=file.filename,
            mime_type=mimetype,
            extracted_text=text,
            user_email=user_email,
            course_code=course_code,
            course_name=course_name,
            term=term,
            institution=institution,
            instructor=instructor,
            meeting_times=meeting_times,
            model=model,
            pipeline_path=pipeline_path,
            page_count=1,
        )
        return jsonify({
            "filename": file.filename,
            "text": text,
            "type": "image",
            "saved_to_supabase": save_result.get("saved", False),
            "supabase_save": save_result,
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/syllabus/save")
def save_syllabus_extract():
    payload = request.get_json(silent=True) or {}
    user_email = payload.get("user_email") or request.form.get("user_email") or "unknown@local.dev"
    course_code = payload.get("course_code")
    course_name = payload.get("course_name")
    extracted_text = payload.get("text") or payload.get("extracted_text")

    if not extracted_text:
        return jsonify({"error": "Missing extracted text to save."}), 400

    file_name = payload.get("filename") or "syllabus-upload.txt"
    mime_type = payload.get("mime_type") or "text/plain"
    file_bytes = payload.get("file_bytes")
    if isinstance(file_bytes, str):
        file_bytes = file_bytes.encode("utf-8")
    else:
        file_bytes = payload.get("file_bytes") or extracted_text.encode("utf-8")

    try:
        result = save_extracted_syllabus_to_supabase(
            user_email=user_email,
            filename=file_name,
            mime_type=mime_type,
            file_bytes=file_bytes,
            extracted_text=extracted_text,
            source=payload.get("source", "file"),
            course_code=course_code,
            course_name=course_name,
            term=payload.get("term"),
            institution=payload.get("institution"),
            instructor=payload.get("instructor"),
            meeting_times=payload.get("meeting_times"),
            model=payload.get("model", "tesseract"),
            pipeline_path=payload.get("pipeline_path", "native_text"),
            page_count=payload.get("page_count", 1),
        )
        return jsonify({"status": "ok", "data": result}), 200
    except Exception as exc:  # pragma: no cover - depends on Supabase setup
        return jsonify({"status": "error", "message": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)