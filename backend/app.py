import os
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from flask import Flask, jsonify, request
from flask_cors import CORS

# Running ``python backend/app.py`` puts only ``backend/`` on Python's import
# path. Add the repository root so this service can host the ML blueprint.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ml.app.config import settings
from ml.app.routes import syllabus_bp


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

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_bytes
CORS(app, resources={r"/api/*": {"origins": "*"}})
app.register_blueprint(syllabus_bp)


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


@app.post("/api/ocr")
@app.post("/api/extract-text")
def extract_text():
    file = request.files.get("image") or request.files.get("file")

    if file is None or file.filename == "":
        return jsonify({"error": "No image uploaded."}), 400

    if not file.mimetype or not file.mimetype.startswith("image/"):
        return jsonify({"error": "Uploaded file must be an image."}), 400

    image_bytes = file.read()

    try:
        text = extract_text_from_image(image_bytes)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "filename": file.filename,
        "text": text,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
