"""Stage 2: decide whether to read the text layer or look at pixels."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import settings
from ..schemas import PipelinePath
from .pdf import PdfDocument


@dataclass
class RoutingDecision:
    path: PipelinePath
    reason: str
    chars_per_page: float
    vision_pages: list[int]   # 1-indexed pages that need rasterizing


def decide_path(doc: PdfDocument, threshold: int | None = None) -> RoutingDecision:
    threshold = threshold if threshold is not None else settings.text_density_threshold

    if doc.n_pages == 0:
        return RoutingDecision(PipelinePath.VISION, "no pages found", 0.0, [])

    thin = [p.number for p in doc.pages if len(p.text) < threshold]

    if not thin:
        return RoutingDecision(
            PipelinePath.NATIVE_TEXT,
            f"{doc.chars_per_page:.0f} chars/page >= {threshold}",
            doc.chars_per_page,
            [],
        )

    if len(thin) == doc.n_pages:
        return RoutingDecision(
            PipelinePath.VISION,
            f"no usable text layer ({doc.chars_per_page:.0f} chars/page < {threshold})",
            doc.chars_per_page,
            thin,
        )

    # Some pages have text, some don't — a scanned appendix stapled to a
    # digital syllabus. Read what we can, rasterize the rest.
    return RoutingDecision(
        PipelinePath.HYBRID,
        f"{len(thin)} of {doc.n_pages} pages lack a text layer",
        doc.chars_per_page,
        thin,
    )


def decide_path_for_images(n_images: int) -> RoutingDecision:
    """Camera frames are always pixels."""
    return RoutingDecision(
        PipelinePath.VISION, f"{n_images} camera frame(s)", 0.0, list(range(1, n_images + 1))
    )
