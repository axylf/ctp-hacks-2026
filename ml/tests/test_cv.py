"""Stage 3: the camera path. These are the tests that make 'scan with camera'
more than a file picker with a different icon."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from ml.app.ingest.image import (
    blur_score,
    decode,
    estimate_skew,
    find_document_quad,
    four_point_transform,
    preprocess,
    rotate,
    upscale,
)
from ml.tests.conftest import encode, make_page_image


def test_decode_rejects_garbage():
    with pytest.raises(ValueError, match="could not decode"):
        decode(b"this is not an image")


def test_cv_deskew(page_image):
    """A 12-degree tilt must come back under 1 degree of residual skew."""
    tilted = rotate(page_image, 12.0)
    estimated = estimate_skew(tilted)
    assert estimated == pytest.approx(-12.0, abs=1.0), f"estimated {estimated}"

    corrected = rotate(tilted, estimated)
    assert abs(estimate_skew(corrected)) < 1.0


@pytest.mark.parametrize("angle", [-7.5, -3.0, 0.0, 4.25, 9.0])
def test_cv_deskew_various_angles(page_image, angle):
    assert estimate_skew(rotate(page_image, angle)) == pytest.approx(-angle, abs=1.0)


def test_cv_skew_of_flat_page_is_zero(page_image):
    assert abs(estimate_skew(page_image)) < 0.5


def test_cv_perspective(page_image):
    """A page photographed at an angle warps back to a rectangle."""
    h, w = page_image.shape[:2]
    scene = np.full((h + 200, w + 200, 3), 30, dtype=np.uint8)

    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    # Trapezoid: the far edge of the page is smaller, as in a real photo.
    dst = np.float32([[190, 110], [w - 20, 60], [w + 60, h + 130], [110, h + 60]])
    warped = cv2.warpPerspective(page_image, cv2.getPerspectiveTransform(src, dst),
                                 (scene.shape[1], scene.shape[0]),
                                 dst=scene, borderMode=cv2.BORDER_TRANSPARENT)

    quad = find_document_quad(warped)
    assert quad is not None, "failed to find the page in the photo"

    flat = four_point_transform(warped, quad)
    recovered = flat.shape[1] / flat.shape[0]
    original = w / h
    assert recovered == pytest.approx(original, rel=0.18), (
        f"aspect {recovered:.3f} vs expected {original:.3f}"
    )


def test_cv_no_quad_on_a_flat_scan(page_image):
    """A borderless scan has no page edge to find; callers must handle None
    rather than crashing."""
    assert find_document_quad(page_image[100:-100, 100:-100]) is None


def test_cv_blur_gate(page_image):
    sharp = preprocess(encode(page_image))
    assert not sharp.too_blurry, f"sharp page scored {sharp.blur_score}"

    blurred = cv2.GaussianBlur(page_image, (31, 31), 12)
    soft = preprocess(encode(blurred))
    assert soft.too_blurry, f"blurred page scored {soft.blur_score}"
    assert soft.blur_score < sharp.blur_score


def test_upscale_raises_small_text():
    small = make_page_image(width=500, height=650)
    assert min(upscale(small).shape[:2]) >= 1600


def test_upscale_leaves_large_images_alone():
    big = make_page_image(width=2000, height=2600)
    assert upscale(big).shape == big.shape


def test_preprocess_reports_what_it_did(page_image):
    tilted = rotate(page_image, 6.0)
    result = preprocess(encode(tilted))
    assert abs(result.skew_corrected_deg + 6.0) < 1.5
    assert result.to_png().startswith(b"\x89PNG")
    assert min(result.image.shape[:2]) >= 1600
