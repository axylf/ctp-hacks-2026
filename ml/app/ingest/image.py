"""Stage 3: turn a phone photo of a syllabus into something a vision model can read.

Order matters. Find the page and flatten it first, THEN measure skew — running
deskew on an un-warped photo estimates the angle of the desk, not the text.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from ..config import settings


@dataclass
class PreprocessResult:
    image: np.ndarray
    blur_score: float
    document_found: bool
    skew_corrected_deg: float
    warnings: list[str] = field(default_factory=list)

    @property
    def too_blurry(self) -> bool:
        return self.blur_score < settings.blur_reject_below

    def to_png(self) -> bytes:
        ok, buf = cv2.imencode(".png", self.image)
        if not ok:
            raise ValueError("failed to encode preprocessed image")
        return buf.tobytes()


def decode(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image (unsupported or corrupt format)")
    return img


def _gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


# --- 1. blur gate ----------------------------------------------------------

def blur_score(img: np.ndarray) -> float:
    """Laplacian variance. Low = out of focus. Checked BEFORE any API call so a
    bad shot costs nothing but a retake prompt."""
    return float(cv2.Laplacian(_gray(img), cv2.CV_64F).var())


# --- 2. document detection + perspective ----------------------------------

def find_document_quad(img: np.ndarray, min_area_ratio: float | None = None) -> np.ndarray | None:
    """Largest convex 4-gon that plausibly is the page. None if the photo is
    already a flat scan (or we simply can't find one) — callers just skip the warp."""
    min_area_ratio = min_area_ratio if min_area_ratio is not None else settings.min_document_area_ratio
    gray = _gray(img)
    h, w = gray.shape[:2]

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    # Close small gaps so a page border broken by glare still forms one contour.
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
        area = cv2.contourArea(contour)
        if area < min_area_ratio * w * h:
            break
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return approx.reshape(4, 2).astype("float32")
    return None


def order_quad(pts: np.ndarray) -> np.ndarray:
    """Order corners tl, tr, br, bl — the sum/diff trick."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0], rect[2] = pts[np.argmin(s)], pts[np.argmax(s)]
    d = np.diff(pts, axis=1).ravel()
    rect[1], rect[3] = pts[np.argmin(d)], pts[np.argmax(d)]
    return rect


def four_point_transform(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = order_quad(quad)
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    width, height = max(width, 1), max(height, 1)
    dst = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32"
    )
    matrix = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl], dtype="float32"), dst)
    return cv2.warpPerspective(img, matrix, (width, height))


# --- 3. deskew -------------------------------------------------------------

def _binary_for_skew(gray: np.ndarray) -> np.ndarray:
    small = gray
    scale = 700 / max(gray.shape[:2])
    if scale < 1:
        small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    _, bw = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return bw


def _projection_score(bw: np.ndarray, angle: float) -> float:
    """Rotate, then sum each row. Text lines align into sharp peaks when the
    angle is right, so the variance of the row profile peaks at true skew."""
    h, w = bw.shape
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(bw, matrix, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    profile = rotated.sum(axis=1, dtype=np.float64)
    return float(((profile[1:] - profile[:-1]) ** 2).sum())


def estimate_skew(img: np.ndarray, limit: float | None = None) -> float:
    """Degrees to rotate the image by to level the text. Coarse then fine sweep —
    a projection profile beats minAreaRect on real pages, where the text block
    isn't the same shape as its bounding box."""
    limit = limit if limit is not None else settings.max_skew_search_deg
    bw = _binary_for_skew(_gray(img))
    if bw.sum() == 0:
        return 0.0

    coarse = np.arange(-limit, limit + 0.5, 1.0)
    best = max(coarse, key=lambda a: _projection_score(bw, a))
    fine = np.arange(best - 1.0, best + 1.0 + 0.05, 0.1)
    return float(max(fine, key=lambda a: _projection_score(bw, a)))


def rotate(img: np.ndarray, angle: float) -> np.ndarray:
    if abs(angle) < 0.05:
        return img
    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    border = cv2.BORDER_REPLICATE
    return cv2.warpAffine(img, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=border)


# --- 4/5. clean up + upscale ----------------------------------------------

def enhance(img: np.ndarray) -> np.ndarray:
    """Even out phone-camera lighting without destroying thin glyph strokes.

    CLAHE rather than a hard binarization: vision models read greyscale fine,
    and adaptive thresholding tends to eat the light strokes in small type.

    bilateralFilter rather than fastNlMeansDenoising: measured on a 1600px
    page, non-local means costs 2900ms against bilateral's 52ms -- 97% of the
    whole camera pipeline for one stage. Bilateral is also the better fit
    here, because it preserves the edges that glyph strokes are made of
    rather than smoothing across them.
    """
    gray = _gray(img)
    gray = cv2.bilateralFilter(gray, d=5, sigmaColor=40, sigmaSpace=40)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def upscale(img: np.ndarray, target_short_edge: int | None = None) -> np.ndarray:
    """Small text is the leading cause of vision misreads."""
    target = target_short_edge or settings.target_short_edge_px
    short = min(img.shape[:2])
    if short >= target:
        return img
    scale = min(target / short, 4.0)
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def fit_short_edge(img: np.ndarray, target_short_edge: int | None = None) -> np.ndarray:
    """Scale to the target short edge in EITHER direction.

    Modern phone cameras hand us 12MP frames. Denoising one of those costs
    seconds, and the extra pixels buy nothing: the vision model resizes them
    down anyway, and the upload gets needlessly large. Fit first, clean second.
    """
    target = target_short_edge or settings.target_short_edge_px
    short = min(img.shape[:2])
    if short == target:
        return img
    scale = min(target / short, 4.0)
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=interpolation)


# --- the pipeline ----------------------------------------------------------

def preprocess(data: bytes) -> PreprocessResult:
    img = decode(data)
    warnings: list[str] = []

    quad = find_document_quad(img)
    if quad is not None:
        img = four_point_transform(img, quad)
    else:
        warnings.append("no page border detected; using the frame as-is")

    angle = estimate_skew(img)
    if abs(angle) >= 0.1:
        img = rotate(img, angle)

    # Blur is measured on the original pixels -- resizing changes the score.
    score = blur_score(img)
    img = enhance(fit_short_edge(img))

    return PreprocessResult(
        image=img,
        blur_score=score,
        document_found=quad is not None,
        skew_corrected_deg=angle,
        warnings=warnings,
    )
