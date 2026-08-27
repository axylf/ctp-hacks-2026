import os
import shutil

import cv2
import numpy as np
import pytesseract
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

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})


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
        return jsonify({"error": "No file uploaded."}), 400

    file_bytes = file.read()
    mimetype = file.mimetype or ""

    if mimetype == "application/pdf":
        try:
            text = extract_text_from_pdf(file_bytes)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        return jsonify({
            "filename": file.filename,
            "text": text,
            "type": "pdf",
        })

    if not mimetype.startswith("image/"):
        return jsonify({"error": "Uploaded file must be an image or PDF."}), 400

    try:
        text = extract_text_from_image(file_bytes)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "filename": file.filename,
        "text": text,
        "type": "image",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
